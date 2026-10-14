import type { Page } from '@playwright/test'
import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test, type Guard } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'
import { INSTALL_WRITE } from './mail-page'
import { enterDirectorKey } from '../support/director-key'

// #531 (merged, PR #664): Agent Mail setup lives on each harness page. Agent
// Mail has no setup tab; each harness page shows its Agent Mail state in one
// line with Set up or Remove, and keeps paths under "Technical details".
// Cancel sends no write, and a failed action keeps the dialog open.
// The browser answers every install write with 503, so nothing is written.
// Seed: the instance HOME has no Agent Mail setup, so each managed harness
// shows "Not set up".
// Design reference: screens 14 (Agent Mail) and 19 (harness page).
// @active since #531 merged into release/v3.1 (PR #664).

const MANAGED = ['claude-code', 'codex-cli', 'copilot-cli', 'opencode-cli', 'muse-cli']
const PATH = /(^|\s)(\/|~\/)[\w.-]+/

/** Answer every install write with 503 and count the writes. */
async function failWrites(page: Page, guard: Guard): Promise<string[]> {
  const writes: string[] = []
  guard.expectStatus('POST', INSTALL_WRITE, 503)
  await page.route(INSTALL_WRITE, async route => {
    writes.push(route.request().url())
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'e2e: install intercepted' }) })
  })
  return writes
}

async function openHarness(page: Page, harness: string) {
  if (page.url() === 'about:blank'
    || !await page.evaluate(() => sessionStorage.getItem('claude-deck.agent-teams.operator-token'))) {
    await page.goto('/agent-mail')
    await enterDirectorKey(page)
  }
  await page.goto(`/harnesses/${harness}`)
  const line = page.getByRole('region', { name: 'Agent Mail', exact: true })
  await expect(line).toContainText(/Agent Mail: \S/)
  await expect(line).not.toContainText('Checking the setup')
  return line
}

test('@active Agent Mail has no setup tab and links to Harnesses', async ({ page }) => {
  // The real instance state, with no rewrite: Agent Mail is not set up.
  await page.goto('/agent-mail')
  await enterDirectorKey(page)
  await expect(page.getByRole('heading', { name: 'Agent Mail', exact: true })).toBeVisible()
  await expect(page.getByRole('tab')).toHaveText(['Team', 'Conversations'])
  await expect(page.getByText('Agent setup required')).toBeVisible()
  await expect(page.locator('main a[href="/harnesses"]').filter({ hasText: 'Set up in Harnesses' })).toBeVisible()
})

test('@active each harness page shows one Agent Mail line with no path', async ({ page }) => {
  for (const harness of [...MANAGED, 'pi-cli']) {
    const line = await openHarness(page, harness)
    await expect(line, harness).toHaveCount(1)
    expect(await line.innerText(), harness).not.toMatch(PATH)
    const setUp = line.getByRole('button', { name: 'Set up', exact: true })
    await expect(setUp, harness).toHaveCount(MANAGED.includes(harness) ? 1 : 0)
  }
  // The paths are folded away under "Technical details".
  await openHarness(page, 'claude-code')
  const details = page.locator('details').filter({ has: page.locator('summary', { hasText: 'Technical details' }) })
  await expect(details.getByText('Hooks file')).toBeAttached()
  expect(await details.first().evaluate(element => (element as HTMLDetailsElement).open)).toBe(false)
})

test('@active Cancel sends no write', async ({ page, guard }) => {
  const writes = await failWrites(page, guard)
  const line = await openHarness(page, 'claude-code')
  await line.getByRole('button', { name: 'Set up', exact: true }).click()
  const dialog = page.getByRole('alertdialog')
  await expect(dialog).toContainText('Install Agent Mail for Claude Code')
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toHaveCount(0)
  await page.waitForTimeout(500)
  expect(writes, 'no install write').toEqual([])
})

test('@active a failed action keeps the dialog open', async ({ page, guard }) => {
  const writes = await failWrites(page, guard)
  const line = await openHarness(page, 'claude-code')
  await line.getByRole('button', { name: 'Set up', exact: true }).click()
  const dialog = page.getByRole('alertdialog')
  await dialog.getByRole('button', { name: 'Confirm' }).click()
  await expect.poll(() => writes.length, 'one install write').toBe(1)
  await expect(page.getByText('e2e: install intercepted')).toBeVisible()
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Confirm' })).toBeEnabled()
  // The page behind the open dialog is hidden from the accessibility tree.
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(line).toContainText('Not set up')
  expect(writes, 'still one install write').toHaveLength(1)
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active the harness page Agent Mail line meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    const line = await openHarness(page, 'claude-code')
    const failures = await contrastFailures(line)
    expect(failures, JSON.stringify(failures)).toEqual([])
    await expectKeyboardReachable(page, page.locator('main'), 3)
  })

  test(`@active the Agent Mail confirm dialog meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page, guard }) => {
    await failWrites(page, guard)
    await useTheme(page, theme)
    const line = await openHarness(page, 'claude-code')
    await line.getByRole('button', { name: 'Set up', exact: true }).click()
    const dialog = page.getByRole('alertdialog')
    await expect(dialog).toBeVisible()
    const failures = await contrastFailures(dialog)
    expect(failures, JSON.stringify(failures)).toEqual([])
    await expectKeyboardReachable(page, dialog, 2)
  })
}
