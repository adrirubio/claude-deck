import type { Page } from '@playwright/test'
import { DIRECTOR_KEY } from '../support/director-key'
import { expect, test } from '../support/guard'

// #515: ask for the Director key only to unlock events, and never show 0
// events after a refused read. Design reference: screens 16 (unlocked) and
// 17 (locked).

const KEY_STORAGE = 'claude-deck.agent-teams.operator-token'
const EVENT_COUNT = /\b\d+\s+(audit\s+)?events?\b/i

async function openAudit(page: Page): Promise<void> {
  await page.goto('/audit')
  await expect(page.getByRole('heading', { name: /Audit/ }).first()).toBeVisible()
}

test('@active Audit with no stored key shows no modal', async ({ page }) => {
  await openAudit(page)
  await page.waitForLoadState('networkidle').catch(() => undefined)
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('@active after a cancelled read, the page shows no event count and says why', async ({ page }) => {
  await openAudit(page)
  // An unlock control opens the key dialog only when the Director asks for events.
  await page.getByRole('button', { name: /unlock|show events|Director key/i }).first().click()
  await page.getByRole('dialog').getByRole('button', { name: /cancel/i }).click()
  const main = page.locator('main')
  await expect(main).not.toContainText(EVENT_COUNT)
  await expect(main).not.toContainText(/\b0 events\b/i)
  await expect(main).toContainText(/(events are|events stay) (not shown|locked|hidden)|Director key/i)
})

test('@active after a refused read, the page shows no event count and says why', async ({ page, guard }) => {
  guard.expectStatus('GET', /\/api\/v1\/factory\/audit-events/, 401)
  await openAudit(page)
  await page.getByRole('button', { name: /unlock|show events|Director key/i }).first().click()
  const dialog = page.getByRole('dialog')
  await dialog.locator('input:not([type=checkbox]):not([type=hidden])').first().fill('wrong-director-key-0000000000000')
  await dialog.getByRole('button', { name: /use|unlock|continue/i }).click()
  const main = page.locator('main')
  await expect(main).toContainText(/(refused|rejected|not accepted|wrong)/i)
  await expect(main).not.toContainText(/\b0 events\b/i)
})

test('@active with a stored key, the events load on entry', async ({ page }) => {
  await page.addInitScript(([key, value]) => window.sessionStorage.setItem(key, value), [KEY_STORAGE, DIRECTOR_KEY])
  await openAudit(page)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('main').getByText(/continuation|refused|request/i).first()).toBeVisible()
})
