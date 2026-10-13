import { contrastFailures } from '../support/contrast'
import { expect, test } from '../support/guard'

// #528: at the reminder cap, the Director sees one attention item that names
// the agent, the item and the duration. The cap itself ("at most the capped
// number of messages per day") is scheduler logic; the test instance runs no
// scheduler, so the #528 backend tests cover it.
// Seed (scripts/e2e/scenarios.py, seed_lane_g): merged item #104 holds a
// workspace lease; its owner "B1 Backend" has 4 unanswered release reminders.
// LANE_G_REMINDERS matches the backend cap.
// Active since #678 (the frontend part of #528).

const AGENT = 'B1 Backend'
const DURATION = /\b\d+\s?(min|minutes?|h|hours?)\b/i

test('@active Overview shows one attention item for the unanswered release reminders', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  const items = page.locator('main').getByText(/release/i).filter({ hasText: '#104' })
  await expect(items, 'one attention item for the held workspace').toHaveCount(1)
  const item = items.first()
  await expect(item).toContainText(AGENT)
  await expect(item).toContainText(DURATION)
  const failures = await contrastFailures(page.locator('main'))
  expect(failures, JSON.stringify(failures)).toEqual([])
})
