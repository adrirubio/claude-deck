import { expect, type Locator, type Page } from '@playwright/test'

// Keyboard checks for a changed screen: Tab reaches the region's controls,
// and each focused control is visible and shows a focus indicator (an
// outline, a ring box-shadow, or a changed border).

export interface FocusStop {
  name: string
  visible: boolean
  indicator: boolean
}

/** Press Tab until focus enters `region`, then record `stops` focus stops in it. */
export async function tabThrough(page: Page, region: Locator, stops: number, maxTabs = 60): Promise<FocusStop[]> {
  const handle = await region.elementHandle()
  if (!handle) throw new Error('keyboard: the region is not on the page')
  const recorded: FocusStop[] = []
  for (let tab = 0; tab < maxTabs && recorded.length < stops; tab++) {
    await page.keyboard.press('Tab')
    const stop = await page.evaluate((root: Element) => {
      const active = document.activeElement as HTMLElement | null
      if (!active || active === document.body || !root.contains(active)) return null
      const style = getComputedStyle(active)
      const box = active.getBoundingClientRect()
      const outline = style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0
      const ring = style.boxShadow !== 'none' && style.boxShadow !== ''
      return {
        name: (active.getAttribute('aria-label') || active.textContent || active.tagName).trim().slice(0, 40),
        visible: box.width > 0 && box.height > 0 && style.visibility !== 'hidden',
        indicator: outline || ring,
      }
    }, handle)
    if (stop) recorded.push(stop)
  }
  return recorded
}

/** Assert that Tab reaches `stops` controls in the region, each visible and focus-marked. */
export async function expectKeyboardReachable(page: Page, region: Locator, stops = 3): Promise<void> {
  const recorded = await tabThrough(page, region, stops)
  expect(recorded.length, `Tab reaches ${stops} controls in the region: ${JSON.stringify(recorded)}`).toBe(stops)
  const hidden = recorded.filter(stop => !stop.visible || !stop.indicator)
  expect(hidden, 'each focused control is visible and shows a focus indicator').toEqual([])
}
