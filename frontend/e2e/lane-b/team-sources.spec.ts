import type { Page, Request } from '@playwright/test'
import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { enterDirectorKey } from '../support/director-key'
import { expect, test, type Guard } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #543 (merged, PR #665): From Bridge and From Mail create a team only from
// the sessions and members that the person sees and selects; sessions that
// already belong to a team are clearly marked.
// Every create request is intercepted in the browser and answered with 503,
// so the journey writes nothing to the instance.
// Seed: four fake panes of "Release crew" (deck-e2e-1, -2, -3, -5); the Mail
// members are offline or in a temporary folder.
// Design reference: screen 06 (Teams).
// @active since #543 merged into release/v3.1 (PR #665).

const CREATE = /\/api\/v1\/agent-teams\/presets(\/from-agent-mail)?$/
const OLD_BRIDGE_CREATE = /\/api\/v1\/agent-teams\/presets\/from-agent-bridge/

/** Answer every create request with 503 and keep its body. */
async function interceptCreates(page: Page, guard: Guard): Promise<{ bodies: unknown[]; oldBridge: string[] }> {
  const seen = { bodies: [] as unknown[], oldBridge: [] as string[] }
  guard.expectStatus('POST', CREATE, 503)
  await page.route(OLD_BRIDGE_CREATE, async route => {
    seen.oldBridge.push(route.request().url())
    await route.fulfill({ status: 503, body: '{}' })
  })
  await page.route(CREATE, async route => {
    const request: Request = route.request()
    if (request.method() !== 'POST') return route.fallback()
    seen.bodies.push(request.postDataJSON())
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'e2e: create intercepted' }) })
  })
  return seen
}

async function openDialog(page: Page, source: 'From Bridge' | 'From Mail') {
  await page.goto('/teams')
  await page.getByRole('button', { name: source, exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  return dialog
}

test('@active From Bridge marks sessions of another team and preselects none of them', async ({ page }) => {
  const dialog = await openDialog(page, 'From Bridge')
  await expect(dialog.getByText(/Already in Release crew/i)).toBeVisible()
  const boxes = dialog.getByRole('checkbox')
  await expect(boxes).toHaveCount(4)
  for (const box of await boxes.all()) await expect(box).not.toBeChecked()
  const create = dialog.getByRole('button', { name: /^Create team with/ })
  await expect(create).toHaveText('Create team with 0 members')
  await expect(create).toBeDisabled()
})

test('@active From Bridge creates a team from exactly the selected session', async ({ page, guard }) => {
  const seen = await interceptCreates(page, guard)
  const dialog = await openDialog(page, 'From Bridge')
  await dialog.locator('#team-name').fill('E2E picked team')
  await dialog.getByRole('checkbox', { name: /deck-e2e-2/ }).check()
  const create = dialog.getByRole('button', { name: /^Create team with/ })
  await expect(create).toHaveText('Create team with 1 member')
  await create.click()
  await enterDirectorKey(page)
  await expect.poll(() => seen.bodies.length, 'one create request').toBe(1)
  const body = seen.bodies[0] as { name?: string; slots?: unknown[] }
  expect(body.name).toBe('E2E picked team')
  expect(body.slots, 'exactly the selected session').toHaveLength(1)
  expect(JSON.stringify(body.slots)).not.toMatch(/deck-e2e-(1|3|5)\b/)
  expect(seen.oldBridge, 'no create from every live session').toEqual([])
  // A failed create keeps the dialog open.
  await expect(page.getByRole('dialog').filter({ hasText: /Create From Agent Bridge/ })).toBeVisible()
})

test('@active From Mail hides offline and temporary members until asked, then creates from the selection', async ({ page, guard }) => {
  const seen = await interceptCreates(page, guard)
  const dialog = await openDialog(page, 'From Mail')
  await expect(dialog.getByText('No Agent Mail members to show.')).toBeVisible()
  await dialog.getByRole('checkbox', { name: 'Show offline and temporary' }).check()
  await expect(dialog.getByText(/Already in (Release crew|Quiet team)/i).first()).toBeVisible()
  const memberBoxes = (await dialog.getByRole('checkbox').all()).slice(1)
  expect(memberBoxes.length, 'members appear after the toggle').toBeGreaterThan(1)
  for (const box of memberBoxes) await expect(box).not.toBeChecked()
  await memberBoxes[0].check()
  await dialog.locator('#team-name').fill('E2E mail team')
  await dialog.getByRole('button', { name: 'Create team with 1 member' }).click()
  await enterDirectorKey(page)
  await expect.poll(() => seen.bodies.length, 'one create request').toBe(1)
  const body = seen.bodies[0] as { member_ids?: unknown[]; slots?: unknown[] }
  const chosen = body.member_ids ?? body.slots
  expect(chosen, 'exactly the selected member').toHaveLength(1)
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active the From Bridge dialog meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    const dialog = await openDialog(page, 'From Bridge')
    await expect(dialog.getByRole('checkbox').first()).toBeVisible()
    const failures = await contrastFailures(dialog)
    expect(failures, JSON.stringify(failures)).toEqual([])
    await expectKeyboardReachable(page, dialog, 3)
  })
}
