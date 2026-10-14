import { expect, test } from '../support/guard'
import { openUnlockedAudit } from './support'

// #520: refused agent requests appear in a "Needs a look" panel with plain
// reasons. With the seeded data the panel shows both groups and the plain
// reasons without opening any event; every reason code has a plain sentence,
// with a fallback for unknown codes.
// Seed: B1 Backend on #101 (3 refusals) and B2 Backend on #102 (2 refusals,
// one with the unknown code "e2e_unknown_reason_code").
// Design reference: screens 16 (unlocked) and 17 (locked) of the Audit page.

test('@active Needs a look shows both groups of refused requests with plain reasons', async ({ page }) => {
  await openUnlockedAudit(page)
  const panel = page.getByRole('region', { name: /Needs a look/i })
  await expect(panel).toBeVisible()
  await expect(panel).toContainText('B1 Backend')
  await expect(panel).toContainText('#101')
  await expect(panel).toContainText('B2 Backend')
  await expect(panel).toContainText('#102')
  await expect(panel).not.toContainText(/continuation_[a-z_]+/)
  await expect(panel).toContainText(/file paths|actions are not allowed|budget/i)
})

test('@active an unknown reason code gets the fallback sentence', async ({ page }) => {
  await openUnlockedAudit(page)
  const panel = page.getByRole('region', { name: /Needs a look/i })
  await expect(panel).toBeVisible()
  await expect(panel).not.toContainText('e2e_unknown_reason_code')
  await expect(panel).toContainText(/reason (is )?(not known|unknown)|no plain reason|other reason/i)
})
