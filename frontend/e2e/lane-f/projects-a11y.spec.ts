import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #545 (merged, PR #607): its "Done when" is covered by
// g1/project-selector.spec.ts. This file adds the lane F contrast and keyboard
// checks on the changed screen: the project choice on a settings page.
// @active since #545 merged into release/v3.1.

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@active the project choice meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await page.goto('/harnesses/claude-code/config')
    const select = page.getByLabel('Project', { exact: true })
    await expect(select).toBeVisible()
    // The label, the select and the add-folder control (ProjectSelector.tsx).
    const region = select.locator('xpath=../..')
    const failures = await contrastFailures(region)
    expect(failures, JSON.stringify(failures)).toEqual([])
    await expectKeyboardReachable(page, region, 1)
  })
}
