import type { Page } from '@playwright/test'
import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #512 (merged, PR #666): Team lanes shifts through all members, four at a
// time. With 8 members, each one can be shifted into view and 4 lanes are
// visible; the member strip shows all 8 with their activity; at most 4 relays
// are open; a lane zooms to full screen and restores to the same four lanes;
// Escape restores the lanes before it exits Team lanes.
// Seed: all 8 Release crew slots have a fake pane (LIVE_SLOTS in scenarios.py).
// Design reference: screens 12 (four lanes) and 13 (one lane zoomed).
// @active since #512 merged into release/v3.1 (PR #666).

const MEMBERS = ['L1 Leader', 'B1 Backend', 'B2 Backend', 'F1 Frontend', 'F2 Frontend', 'D1 Docs', 'E1 E2E', 'V1 Verifier']

/** Count the terminal WebSockets that are open at the same time. */
function watchRelays(page: Page): { open: () => number; peak: () => number } {
  let open = 0
  let peak = 0
  page.on('websocket', socket => {
    if (!socket.url().includes('/terminal')) return
    open += 1
    peak = Math.max(peak, open)
    socket.on('close', () => { open -= 1 })
  })
  return { open: () => open, peak: () => peak }
}

async function openLanes(page: Page): Promise<void> {
  await page.goto('/agent-bridge')
  await page.getByRole('button', { name: /^Release crew \(8\)$/ }).click()
  await page.getByRole('button', { name: 'Team lanes' }).click()
  await expect(page.getByText('Release crew · 8 members')).toBeVisible()
}

function strip(page: Page) {
  return page.locator('[aria-pressed]').filter({ hasText: new RegExp(MEMBERS.join('|')) })
}

async function visibleMembers(page: Page): Promise<string[]> {
  const pressed = strip(page).and(page.locator('[aria-pressed="true"]'))
  return (await pressed.allInnerTexts()).map(text => MEMBERS.find(member => text.includes(member)) ?? text)
}

test('@active the member strip shows all 8 members, with 4 lanes visible', async ({ page }) => {
  await openLanes(page)
  await expect(strip(page)).toHaveCount(8)
  for (const member of MEMBERS) {
    await expect(strip(page).filter({ hasText: member }), member).toContainText(/Activity|Working|Idle/)
  }
  await expect(page.getByText(/Showing 1–4 of 8/)).toBeVisible()
  expect(await visibleMembers(page)).toEqual(MEMBERS.slice(0, 4))
})

test('@active each member can be shifted into view, with at most 4 relays open', async ({ page }) => {
  const relays = watchRelays(page)
  await openLanes(page)
  const next = page.getByRole('button', { name: 'Show the next member' })
  const seen = new Set(await visibleMembers(page))
  for (let step = 0; step < 4; step++) {
    await next.click()
    await expect.poll(async () => (await visibleMembers(page)).length).toBe(4)
    for (const member of await visibleMembers(page)) seen.add(member)
    expect(relays.open(), 'open relays').toBeLessThanOrEqual(4)
  }
  expect([...seen].sort()).toEqual([...MEMBERS].sort())
  // The strip brings one member straight into view.
  await strip(page).filter({ hasText: 'B2 Backend' }).click()
  await expect.poll(() => visibleMembers(page)).toContain('B2 Backend')
  await page.waitForTimeout(500)
  expect(relays.peak(), 'never more than 4 relays at once').toBeLessThanOrEqual(4)
})

test('@active a lane zooms and restores, and Escape restores the lanes before it exits', async ({ page }) => {
  await openLanes(page)
  const before = await visibleMembers(page)
  await page.getByTitle('Fullscreen').first().click()
  await expect(page.getByTitle('Fullscreen')).toHaveCount(0, { timeout: 5_000 }).catch(() => undefined)
  // The first Escape leaves the zoom and shows the same four lanes again.
  await page.keyboard.press('Escape')
  await expect(page.getByText('Release crew · 8 members')).toBeVisible()
  await expect(page.getByTitle('Fullscreen')).toHaveCount(4)
  expect(await visibleMembers(page)).toEqual(before)
  // The next Escape exits Team lanes.
  await page.keyboard.press('Escape')
  await expect(page.getByText('Release crew · 8 members')).toHaveCount(0)
})

// The light contrast journey checks the member strip's role and harness
// labels. They failed AA at 3.65:1 while they were `opacity-80` (#667). The
// journey is active since #674 (PR #684) removed the opacity.
for (const theme of ['light', 'dark'] as Theme[]) {
  const tag = '@active'
  test(`${tag} Team lanes meets AA contrast in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await openLanes(page)
    const failures = await contrastFailures(page.locator('main'))
    expect(failures, JSON.stringify(failures)).toEqual([])
  })

  test(`@active Team lanes is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await openLanes(page)
    await expectKeyboardReachable(page, page.locator('main'), 3)
  })
}
