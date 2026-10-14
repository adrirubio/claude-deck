import type { Locator, Page } from '@playwright/test'
import { expect } from '../support/guard'
import { enterDirectorKey } from '../support/director-key'

// Shared steps for the lane D (Agent Mail) journeys.

export const INSTALL_STATUS = /\/api\/v1\/agent-mail\/install\/status$/
export const INSTALL_WRITE = /\/api\/v1\/agent-mail\/install\/[a-z-]+\/(apply|uninstall)$/

/**
 * Show Agent Mail as set up for Claude Code. The instance HOME has no Agent
 * Mail configuration (#552), so the page shows "Agent setup required". This
 * rewrites only the answer of the status read in the browser; nothing is
 * written.
 */
export async function showMailSetUp(page: Page): Promise<void> {
  await page.route(INSTALL_STATUS, async route => {
    const response = await route.fetch()
    const status = await response.json() as Record<string, unknown>
    status.claude_code_hooks = [
      ...(status.claude_code_hooks as string[]),
      ...(status.claude_code_hooks_missing as string[]),
    ]
    status.claude_code_hooks_missing = []
    status.claude_code_mcp_installed = true
    await route.fulfill({ response, json: status })
  })
}

export async function openAgentMail(page: Page, tab: 'Team' | 'Conversations'): Promise<void> {
  await page.goto('/agent-mail')
  await enterDirectorKey(page)
  await expect(page.getByRole('heading', { name: 'Agent Mail', exact: true })).toBeVisible()
  await page.getByRole('tab', { name: tab, exact: true }).click()
  await expect(page.getByRole('tab', { name: tab, exact: true })).toHaveAttribute('aria-selected', 'true')
}

/** True when the whole element is inside the viewport, with the page at its top. */
export async function inView(page: Page, element: Locator): Promise<boolean> {
  const box = await element.boundingBox()
  const viewport = page.viewportSize()
  if (!box || !viewport) return false
  return box.y >= 0 && box.y + box.height <= viewport.height
}

/** The scroll position of the page and of its scrolling main region. */
export async function scrollTop(page: Page): Promise<number> {
  return page.evaluate(() => window.scrollY + (document.querySelector('main')?.scrollTop ?? 0))
}
