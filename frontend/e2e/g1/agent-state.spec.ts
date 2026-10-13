import type { Locator, Page } from '@playwright/test'
import { expect, test } from '../support/guard'

// #540: one agent shows the same online and wake state on every screen.
// The seeded agent is "F2 Frontend" (IDLE_AGENT_SLOT in scripts/e2e/scenarios.py):
// a live fake pane, a live MCP session and an observation 3 hours old.
// The words come from #540: Online / Offline, Working / Idle, and
// Can be woken / Cannot be woken. An old observation alone is "Idle", not "stale".

const AGENT = 'F2 Frontend'
const ONLINE = /\b(Online|Offline)\b/
const WAKE = /\b(Can be woken|Cannot be woken)\b/

/** The smallest block on the page that names the agent and an online state. */
async function agentBlock(page: Page): Promise<Locator> {
  const name = page.getByText(AGENT, { exact: true }).first()
  await expect(name).toBeVisible()
  const block = name.locator('xpath=ancestor::*[self::li or self::tr or self::article or @role="listitem" or contains(@class,"border")][1]')
  return (await block.count()) ? block : page.locator('main')
}

async function stateOf(page: Page): Promise<{ online: string; wake: string; text: string }> {
  const block = await agentBlock(page)
  await expect(block).toContainText(ONLINE)
  const text = (await block.innerText()).replace(/\s+/g, ' ')
  const online = ONLINE.exec(text)?.[1] ?? ''
  const wake = WAKE.exec(text)?.[1] ?? ''
  expect(wake, `a wake state for ${AGENT}: ${text}`).not.toBe('')
  expect(text, `no "stale" for ${AGENT}`).not.toMatch(/\bstale\b/i)
  return { online, wake, text }
}

test('@active one agent shows the same online and wake state on Agent Mail, Live sessions and Teams', async ({ page }) => {
  test.skip(process.env.E2E_NO_TMUX === '1', 'E2E_NO_TMUX=1: the agent has no live pane')

  await page.goto('/agent-mail')
  await expect(page.getByRole('heading', { name: 'Agent Mail', exact: true })).toBeVisible()
  const mail = await stateOf(page)

  await page.goto('/agent-bridge')
  await expect(page.getByRole('heading', { name: 'Live sessions', exact: true })).toBeVisible()
  const live = await stateOf(page)

  await page.goto('/teams/1?tab=roster')
  await expect(page.getByRole('heading', { name: 'Teams', exact: true })).toBeVisible()
  const teams = await stateOf(page)

  const states = { mail, live, teams }
  expect(new Set([mail.online, live.online, teams.online]).size, JSON.stringify(states)).toBe(1)
  expect(new Set([mail.wake, live.wake, teams.wake]).size, JSON.stringify(states)).toBe(1)
  // A live MCP session means the agent is online.
  expect(mail.online).toBe('Online')
})
