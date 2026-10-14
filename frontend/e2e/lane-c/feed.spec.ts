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
const FEED_ROW = 'main [role="feed"] article, main [data-testid="audit-feed-row"]'

test('@active every row names its team, its subject and its actor in plain words', async ({ page }) => {
  await openUnlockedAudit(page)
  const rows = page.locator(FEED_ROW)
  await expect(rows.first()).toBeVisible()
  // #676: every row of the page, not the first 8 that happen to sort first.
  const all = await page.locator('main [data-testid="audit-feed-row"]').all()
  expect(all.length, 'the feed shows more than 8 rows').toBeGreaterThan(8)
  for (const row of all) {
    const text = await plainText(row)
    expect(text, 'a team name').toMatch(/Release crew|Quiet team|Retired crew/)
    expect(text, 'a subject (issue or team)').toMatch(/#\d+|team|scope|repository/i)
    expect(text, 'an actor in plain words').toMatch(/Director|Deck|scheduler|B1 Backend|B2 Backend|Leader|Backend|Frontend/i)
    expect(text, 'no null, no code name, no ISO time').not.toMatch(new RegExp(`\\bnull\\b|${CODE_NAMES.source}|\\d{4}-\\d{2}-\\d{2}T`))
  }
})

test('@active both refusal groups name their member, in the panel and in the feed rows', async ({ page }) => {
  await openUnlockedAudit(page)
  const main = page.locator('main')
  await expect(main.getByText(/requests from B1 Backend were refused on sample-app #101/)).toBeVisible()
  await expect(main.getByText(/requests from B2 Backend were refused on sample-app #102/)).toBeVisible()
  const refusalRows = page.locator(FEED_ROW).filter({ hasText: /Request refused/ })
  const texts = await refusalRows.evaluateAll(rows => rows.map(row => (row.textContent ?? '').replace(/\s+/g, ' ')))
  expect(texts.length, 'the refusal rows of both groups').toBeGreaterThanOrEqual(4)
  for (const text of texts) {
    expect(text).toMatch(/B1 Backend|B2 Backend/)
    expect(text).not.toMatch(/\bmember \d+\b/i)
  }
  expect(texts.some(text => /B1 Backend/.test(text) && /#101/.test(text))).toBe(true)
  expect(texts.some(text => /B2 Backend/.test(text) && /#102/.test(text))).toBe(true)
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

// #676: the names come from a separate read. A slow or failed read must never
// put `member <id>` in a row. The rows wait for the read, then show the names.
test('@active a slow member-name read never shows "member <id>" in the feed or the refusals', async ({ page }) => {
  await page.route('**/api/v1/agent-mail/team*', async route => {
    await new Promise(resolve => setTimeout(resolve, 2500))
    await route.continue()
  })
  const seen: string[] = []
  await openUnlockedAudit(page)
  for (let step = 0; step < 12; step += 1) {
    seen.push(await page.locator('main').innerText())
    await page.waitForTimeout(250)
  }
  for (const text of seen) expect(text).not.toMatch(/\bmember \d+\b/i)
  await expect(page.locator(FEED_ROW).first()).toBeVisible()
  await expect(page.locator('main')).toContainText('B2 Backend')
})

test('@active a failed member-name read shows "An agent", never "member <id>"', async ({ page, guard }) => {
  guard.expectStatus('GET', /\/api\/v1\/agent-mail\/team/, 503)
  await page.route('**/api/v1/agent-mail/team*', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"down"}' }))
  await openUnlockedAudit(page)
  await expect(page.locator(FEED_ROW).first()).toBeVisible()
  const text = await page.locator('main').innerText()
  expect(text).not.toMatch(/\bmember \d+\b/i)
  expect(text).toMatch(/An agent|an agent/)
})
