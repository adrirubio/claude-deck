import { expect, test } from '../support/guard'

// #509: a default installation never shows a red identity, and the tab title
// is "Claude Deck" unless a name is configured. The E2E instance sets no
// instance name (no CLAUDE_DECK_INSTANCE_NAME), so it is a default installation.
// @pending until #509 merges.

/** True when a CSS colour is red-dominant (an alarm colour). */
function isRed(css: string): boolean {
  const [r, g, b, a = 1] = (css.match(/[\d.]+/g) ?? []).map(Number)
  return a > 0 && r >= 150 && r - Math.max(g, b) >= 80
}

for (const route of ['/', '/work', '/teams']) {
  test(`@pending ${route} shows no red identity on a default installation`, async ({ page }) => {
    await page.goto(route)
    const header = page.locator('header').first()
    await expect(header).toBeVisible()
    const colours = await header.locator('*').evaluateAll(elements => elements.flatMap(element => {
      const style = getComputedStyle(element)
      const box = element.getBoundingClientRect()
      if (box.width === 0 || box.height === 0) return []
      return [style.color, style.backgroundColor, style.borderColor].map(colour => ({
        colour, element: `${element.tagName.toLowerCase()} "${(element.textContent ?? '').trim().slice(0, 30)}"`,
      }))
    }))
    const red = colours.filter(({ colour }) => isRed(colour))
    expect(red, JSON.stringify(red)).toEqual([])
  })
}

test('@pending the tab title is "Claude Deck" on a default installation', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  await expect(page).toHaveTitle('Claude Deck')
})
