import type { Locator, Page } from '@playwright/test'
import { DIRECTOR_KEY } from '../support/director-key'
import { expect } from '../support/guard'

// Shared steps for the lane C (Audit) journeys.

const KEY_STORAGE = 'claude-deck.agent-teams.operator-token'

/** Open Audit with the Director key already stored, so the events load. */
export async function openUnlockedAudit(page: Page, query = ''): Promise<void> {
  await page.addInitScript(([key, value]) => window.sessionStorage.setItem(key, value), [KEY_STORAGE, DIRECTOR_KEY])
  await page.goto(`/audit${query}`)
  await expect(page.getByRole('heading', { name: /Audit/ }).first()).toBeVisible()
  await page.waitForLoadState('networkidle').catch(() => undefined)
}

/** The visible text of a region without its "Technical detail(s)" disclosures. */
export async function plainText(region: Locator): Promise<string> {
  return region.evaluate(root => {
    const clone = root.cloneNode(true) as Element
    clone.querySelectorAll('details').forEach(details => {
      if (/technical detail/i.test(details.querySelector('summary')?.textContent ?? '')) details.remove()
    })
    return (clone.textContent ?? '').replace(/\s+/g, ' ')
  })
}
