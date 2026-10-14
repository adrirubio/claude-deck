import type { Page } from '@playwright/test'
import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #541 (merged, PR #658): the new-session dialog has no token field and needs
// no typed path; it uses the shared Director key prompt. A cancelled prompt
// and a refused key start no session. The journeys never use the correct key,
// so no session starts on the instance.
// Design reference: screen 11 (new session).
// @active since #541 merged into release/v3.1 (PR #658).

const SPAWN = /\/api\/v1\/agent-bridge\/sessions(\?|$)/
const WRONG_KEY = 'e2e-wrong-director-key-000000000000'

async function sessionCount(page: Page): Promise<number> {
  const response = await page.request.get('/api/v1/agent-bridge/sessions')
  const body = await response.json() as unknown[] | { sessions?: unknown[] }
  return (Array.isArray(body) ? body : body.sessions ?? []).length
}

async function openDialog(page: Page) {
  await page.goto('/agent-bridge')
  await expect(page.getByText('Sessions (8)')).toBeVisible()
  await page.getByRole('button', { name: 'New session' }).click()
  const dialog = page.getByRole('dialog', { name: /New session/ })
  await expect(dialog).toBeVisible()
  return dialog
}

async function chooseFolder(page: Page, dialog: import('@playwright/test').Locator): Promise<void> {
  // The folder is a choice (a select of the known folders), not a text box.
  await dialog.getByRole('combobox', { name: 'Folder' }).click()
  await page.getByRole('option', { name: /sample-app/ }).first().click()
}

function spawnRequests(page: Page): string[] {
  const seen: string[] = []
  page.on('request', request => {
    if (request.method() === 'POST' && SPAWN.test(request.url())) seen.push(request.url())
  })
  return seen
}

test('@active the dialog has no token field and needs no typed path', async ({ page }) => {
  const dialog = await openDialog(page)
  await expect(dialog.locator('input[type="password"]')).toHaveCount(0)
  await expect(dialog.getByLabel(/token|key/i)).toHaveCount(0)
  await expect(dialog.getByRole('textbox', { name: /path|folder|directory/i })).toHaveCount(0)
  await chooseFolder(page, dialog)
  await expect(dialog.getByRole('combobox', { name: 'Folder' })).toContainText('sample-app')
})

test('@active a cancelled key prompt starts no session', async ({ page }) => {
  const before = await sessionCount(page)
  const spawns = spawnRequests(page)
  const dialog = await openDialog(page)
  await chooseFolder(page, dialog)
  await dialog.getByRole('button', { name: 'Start session' }).click()
  const prompt = page.getByRole('dialog', { name: /Director key/ })
  await expect(prompt).toBeVisible()
  await prompt.getByRole('button', { name: /cancel/i }).click()
  await expect(prompt).toHaveCount(0)
  await page.waitForTimeout(500)
  expect(spawns, 'no spawn request').toEqual([])
  expect(await sessionCount(page)).toBe(before)
})

test('@active a refused key starts no session', async ({ page, guard }) => {
  guard.expectStatus('POST', SPAWN, 401)
  const before = await sessionCount(page)
  const dialog = await openDialog(page)
  await chooseFolder(page, dialog)
  await dialog.getByRole('button', { name: 'Start session' }).click()
  const prompt = page.getByRole('dialog', { name: /Director key/ })
  await expect(prompt).toBeVisible()
  await prompt.locator('input:not([type=checkbox]):not([type=hidden])').first().fill(WRONG_KEY)
  const refused = page.waitForResponse(response => SPAWN.test(response.url()) && response.request().method() === 'POST')
  await prompt.getByRole('button', { name: /use|unlock|continue/i }).click()
  expect((await refused).status()).toBe(401)
  await expect(page.locator('body')).toContainText(/refused|rejected|not accepted|wrong|invalid/i)
  expect(await sessionCount(page)).toBe(before)
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active the new-session dialog meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    const dialog = await openDialog(page)
    const failures = await contrastFailures(dialog)
    expect(failures, JSON.stringify(failures)).toEqual([])
    await expectKeyboardReachable(page, dialog, 3)
  })
}
