import type { Page } from '@playwright/test'
import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'
import { inView, openAgentMail, scrollTop, showMailSetUp } from './mail-page'

// #530 (merged, PR #670): a compact roster by team in place of the 8,600 px
// participant cards. At 1440 × 900 all members of two teams are visible
// without scrolling; no charter text shows until a row is expanded; each row
// has one action menu; members in no team form one collapsed group.
// Seed: "Docs crew" (4 members) and "Quiet team" (2 members) are the first
// two team groups; every mail member has a synthetic charter (#669).
// Design reference: screen 15 (Agent Mail members).
// @active since #530 merged into release/v3.1 (PR #670).

test.use({ viewport: { width: 1440, height: 900 } })

const TWO_TEAMS = ['D2 Docs lead', 'D3 Writer', 'D4 Editor', 'D5 Reviewer', 'Q1 Leader', 'Q2 Implementer']

function row(page: Page, member: string) {
  return page.getByTestId('roster-row').filter({ hasText: member })
}

// The fit journey shows Agent Mail as set up (showMailSetUp): the #552 rule
// keeps the instance without Agent Mail setup, and the "Agent setup required"
// banner (about 134 px) is not on a Director's set-up page.
// @pending: the "Waiting on someone" panel of #529 (136 px with 3 items) is
// above the tabs now, so the last Quiet team row ends at 910 px, 10 px below
// the viewport. #530 passed before #529 merged. Reported to L1 (#669); a
// gate-fix issue for F2 activates this journey.
test('@active at 1440 × 900 all members of two teams are visible without scrolling', async ({ page }) => {
  await showMailSetUp(page)
  await openAgentMail(page, 'Team')
  await expect(page.getByText('Agent setup required')).toHaveCount(0)
  await expect(row(page, 'Q2 Implementer')).toBeVisible()
  expect(await scrollTop(page)).toBe(0)
  for (const member of TWO_TEAMS) {
    expect(await inView(page, row(page, member)), `${member} is in view`).toBe(true)
  }
})

test('@active no charter text shows until a row is expanded', async ({ page }) => {
  await openAgentMail(page, 'Team')
  await expect(row(page, 'D3 Writer')).toBeVisible()
  await expect(page.locator('main').getByText(/Synthetic charter for/)).toHaveCount(0)
  await page.getByRole('button', { name: 'Show details of D3 Writer' }).click()
  await expect(row(page, 'D3 Writer').getByText('Synthetic charter for D3 Writer.')).toBeVisible()
  await expect(page.locator('main').getByText(/Synthetic charter for/)).toHaveCount(1)
})

test('@active each row has one action menu, and members in no team start collapsed', async ({ page }) => {
  await openAgentMail(page, 'Team')
  await expect(row(page, 'D3 Writer')).toBeVisible()
  for (const member of TWO_TEAMS) {
    const buttons = row(page, member).getByRole('button')
    await expect(buttons, member).toHaveCount(2)
    await expect(row(page, member).getByRole('button', { name: `Actions for ${member}` })).toHaveCount(1)
    await expect(row(page, member).getByRole('button', { name: /^(Message|Edit|Request context|Handoff)$/ })).toHaveCount(0)
  }
  await page.getByRole('button', { name: 'Actions for D3 Writer' }).click()
  await expect(page.getByRole('menuitem', { name: 'Message' })).toBeVisible()
  await page.keyboard.press('Escape')
  // "Other sessions (not in a team)" holds the seeded repository participant.
  await expect(page.getByText(/Other sessions \(not in a team\) · 1/)).toBeVisible()
  await expect(row(page, 'sample-app')).toHaveCount(0)
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active the roster meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await openAgentMail(page, 'Team')
    const roster = page.getByRole('tabpanel')
    await expect(row(page, 'D3 Writer')).toBeVisible()
    const failures = await contrastFailures(roster)
    expect(failures, JSON.stringify(failures)).toEqual([])
    await expectKeyboardReachable(page, roster, 3)
  })
}
