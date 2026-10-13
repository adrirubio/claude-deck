import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'
import { openUnlockedAudit, plainText } from './support'

// #519: the event table becomes a readable activity feed. Every row names its
// team, its subject and its actor in plain words; events of a deleted team
// show "(deleted)" with no broken links; no row shows `null`, a code name or a
// raw ISO timestamp outside "Technical detail"; a notification never has its
// own row; opening a detail does not move it away from its row.
// Design reference: screens 16 and 17 (Audit).

const CODE_NAMES = /\b(work_lifecycle|continuation_request|scope_policy_change|team_delete|approval_decision|revision_outcome)\b/
const FEED_ROW = 'main [role="feed"] article, main [data-testid="audit-feed-row"], main ol li'

test('@active every row names its team, its subject and its actor in plain words', async ({ page }) => {
  await openUnlockedAudit(page)
  const rows = page.locator(FEED_ROW)
  await expect(rows.first()).toBeVisible()
  for (const row of (await rows.all()).slice(0, 8)) {
    const text = await plainText(row)
    expect(text, 'a team name').toMatch(/Release crew|Quiet team|Retired crew/)
    expect(text, 'a subject (issue or team)').toMatch(/#\d+|team|scope|repository/i)
    expect(text, 'an actor in plain words').toMatch(/Director|Deck|scheduler|B1 Backend|B2 Backend|Leader|Backend|Frontend/i)
    expect(text, 'no null, no code name, no ISO time').not.toMatch(new RegExp(`\\bnull\\b|${CODE_NAMES.source}|\\d{4}-\\d{2}-\\d{2}T`))
  }
})

test('@active events of the deleted team show "(deleted)" with no broken links', async ({ page }) => {
  await openUnlockedAudit(page)
  const deletedRows = page.locator(FEED_ROW).filter({ hasText: /Retired crew/ }).filter({ hasText: /\(deleted\)/ })
  await expect(deletedRows.first()).toBeVisible()
  for (const href of await deletedRows.locator('a[href]').evaluateAll(links => links.map(link => link.getAttribute('href') ?? ''))) {
    expect(href, 'no link to a deleted team page').not.toMatch(/^\/teams\/3\b/)
  }
})

test('@active opening a detail keeps it at its row', async ({ page }) => {
  await openUnlockedAudit(page)
  const row = page.locator(FEED_ROW).first()
  // Scroll first: the box is relative to the viewport, and the click would scroll it.
  await row.scrollIntoViewIfNeeded()
  const before = await row.boundingBox()
  await row.getByRole('button', { name: /detail/i }).first().click()
  const after = await row.boundingBox()
  expect(Math.abs((after?.y ?? 0) - (before?.y ?? 0)), 'the row stays in place').toBeLessThanOrEqual(2)
  const detail = row.locator('details[open], [data-state="open"], [aria-expanded="true"]')
  await expect(detail.first()).toBeVisible()
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active the activity feed meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await openUnlockedAudit(page)
    await expect(page.locator(FEED_ROW).first()).toBeVisible()
    const failures = await contrastFailures(page.locator('main'))
    expect(failures, JSON.stringify(failures)).toEqual([])
    await expectKeyboardReachable(page, page.locator('main'), 3)
  })
}
