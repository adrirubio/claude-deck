import { expect, test } from '../support/guard'

// #526: an old native link opens the matching Harnesses page, and no control
// on a Harnesses page is a no-op. The sidebar has no harness select.
// @active

for (const [from, surface, heading] of [
  ['/config', 'config', 'Configuration'],
  ['/mcp', 'mcp', /MCP/],
] as const) {
  test(`@active the old link ${from} opens the matching Harnesses page`, async ({ page }) => {
    await page.goto(from)
    await expect(page).toHaveURL(new RegExp(`/harnesses/[a-z-]+/${surface}$`))
    await expect(page.getByRole('heading', { name: heading }).first()).toBeVisible()
  })
}

test('@active the old link keeps the project choice in the query string', async ({ page }) => {
  await page.goto('/config?project=%2Fnot%2Fa%2Fknown%2Ffolder')
  await expect(page).toHaveURL(/\/harnesses\/[a-z-]+\/config\?project=%2Fnot%2Fa%2Fknown%2Ffolder$/)
})

test('@active the sidebar has no harness preference select on a Harnesses page', async ({ page }) => {
  await page.goto('/harnesses')
  await expect(page.getByRole('heading', { name: /Harnesses/ }).first()).toBeVisible()
  await expect(page.getByLabel('Saved native harness preference')).toHaveCount(0)
})
