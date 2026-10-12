import { expect, test } from '../support/guard'

// #526: no control on a Harnesses page has no effect, and old links such as
// /mcp open the matching harness page.
// @pending until #526 merges.

test('@pending the harness preference select is absent on harness pages, or it changes the page', async ({ page }) => {
  await page.goto('/harnesses/claude-code/mcp')
  await expect(page.locator('main')).toBeVisible()
  const preference = page.getByLabel(/Saved native harness preference/i)
  if ((await preference.count()) === 0) return
  const before = page.url()
  await preference.selectOption({ label: 'Codex' })
  await expect.poll(() => page.url(), 'the page follows the chosen harness').not.toBe(before)
  await expect(page).toHaveURL(/\/harnesses\/codex-cli/)
})

for (const surface of ['mcp', 'hooks', 'config', 'agents', 'plugins']) {
  test(`@pending the old link /${surface} opens the matching harness page`, async ({ page }) => {
    await page.goto(`/${surface}`)
    await expect(page).toHaveURL(new RegExp(`/harnesses/[a-z-]+/${surface}$`))
    await expect(page.locator('main')).toBeVisible()
  })
}
