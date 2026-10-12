import type { Locator, Page } from '@playwright/test'
import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'

// #510: all text meets WCAG AA contrast in both themes, and each colour has
// one meaning across Overview, Work and Teams.
// @active: Overview, Work, the Teams roster with the selected team card, and
// the full Teams page with the Autonomy tab (#577 fixed AutonomyPanel.tsx).

const THEMES: Theme[] = ['light', 'dark']

const ACTIVE_ROUTES = [
  { name: 'Overview', route: '/', ready: 'Overview' },
  { name: 'Work', route: '/work', ready: 'Work' },
  { name: 'the Teams roster', route: '/teams/1?tab=roster', ready: 'Agent Teams' },
]

async function open(page: Page, route: string, ready: string): Promise<void> {
  await page.goto(route)
  await expect(page.getByRole('heading', { name: ready, exact: true })).toBeVisible()
  await page.waitForLoadState('networkidle').catch(() => undefined)
}

function describeFailures(failures: Awaited<ReturnType<typeof contrastFailures>>): string {
  return failures.map(f => `"${f.text}" ${f.ratio}:1 < ${f.required}:1 (${f.color} on ${f.background})`).join('\n')
}

/** True when an rgb()/rgba() colour has no hue: the neutral accent surface. */
function isNeutral(css: string): boolean {
  const [r, g, b] = (css.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number)
  return Math.max(r, g, b) - Math.min(r, g, b) <= 6
}

async function backgroundOf(locator: Locator): Promise<string> {
  return locator.evaluate(element => getComputedStyle(element).backgroundColor)
}

for (const theme of THEMES) {
  for (const { name, route, ready } of ACTIVE_ROUTES) {
    test(`@active ${name} text meets AA contrast in the ${theme} theme`, async ({ page }) => {
      await useTheme(page, theme)
      await open(page, route, ready)
      const failures = await contrastFailures(page.locator('body'))
      expect(failures, describeFailures(failures)).toEqual([])
    })
  }

  test(`@active selected states use the neutral surface, not green, in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await open(page, '/teams/1?tab=roster', 'Agent Teams')

    // The selected team card: a neutral raised surface with a green left bar.
    const card = page.getByRole('button', { name: /Release crew/ }).first()
    await expect(card).toBeVisible()
    const cardBackground = await backgroundOf(card)
    expect(isNeutral(cardBackground), `selected team card background ${cardBackground}`).toBe(true)
    const cardFailures = await contrastFailures(card)
    expect(cardFailures, describeFailures(cardFailures)).toEqual([])

    // The active navigation entry uses the same neutral surface.
    const activeNav = page.getByRole('navigation', { name: 'Main navigation' }).locator('[aria-current="page"]')
    await expect(activeNav).toHaveCount(1)
    const navBackground = await backgroundOf(activeNav)
    expect(isNeutral(navBackground), `active navigation background ${navBackground}`).toBe(true)
  })

  test(`@active the full Teams page meets AA contrast in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await open(page, '/teams/1?tab=autonomy', 'Agent Teams')
    await expect(page.getByText('code merge:', { exact: false }).first()).toBeVisible()
    const failures = await contrastFailures(page.locator('body'))
    expect(failures, describeFailures(failures)).toEqual([])
  })
}
