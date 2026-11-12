import type { Page } from '@playwright/test'
import { expect, test } from '../support/guard'

// #865: the app header fits on one row at 390 px, so the theme toggle stays next
// to the logo. At 1440 px the header keeps its layout. No header item overlaps
// another or leaves the viewport, whatever the status state. The container
// warning stays reachable by touch and keyboard when its text is hidden.

type StatusState = 'loaded' | 'long-name' | 'cli-warning' | 'unloaded'

const LONG_NAME = 'a-very-long-instance-name-for-this-host-01'
const WARNING_LABEL = 'Container cannot see host agent CLIs'
const WARNING = 'Host agent CLIs are not visible from this container. Run Albiex Synth City on the host.'

interface Box { name: string; left: number; right: number; top: number; bottom: number }

/** Serve /api/v1/status in the given state. `unloaded` holds the answer until `release()`. */
async function serveStatus(page: Page, state: StatusState): Promise<() => void> {
  let release = () => {}
  const held = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/v1/status', async route => {
    if (state === 'unloaded') await held
    const response = await route.fetch()
    const body = await response.json()
    if (state === 'long-name' || state === 'cli-warning') {
      body.instance = { ...body.instance, name: LONG_NAME }
    }
    if (state === 'cli-warning') {
      body.environment = { ...body.environment, agent_cli_warning: WARNING }
    }
    await route.fulfill({ response, json: body })
  })
  return release
}

/** The visible items of the header: the logo, the subtitle and the badges. The toggle has its own box. */
async function headerBoxes(page: Page): Promise<{ boxes: Box[]; headerHeight: number }> {
  return page.locator('header').first().evaluate(header => {
    const row = header.firstElementChild as HTMLElement
    const items = [...row.children].flatMap(group => [...group.children]) as HTMLElement[]
    const boxes = items.flatMap(item => {
      if (item.matches('button[title^="Switch to"]') || item.querySelector('button[title^="Switch to"]')) return []
      const box = item.getBoundingClientRect()
      if (box.width === 0 || box.height === 0) return []
      const name = item.getAttribute('alt') ?? item.getAttribute('title') ?? item.textContent?.trim() ?? item.tagName
      return [{ name: name.slice(0, 40), left: box.left, right: box.right, top: box.top, bottom: box.bottom }]
    })
    return { boxes, headerHeight: header.getBoundingClientRect().height }
  })
}

/** The theme button itself, found by its accessible name, with its real bounding box. */
async function toggleBox(page: Page): Promise<Box> {
  const box = await page.getByRole('button', { name: 'Toggle theme' }).boundingBox()
  expect(box, 'the theme toggle button has a bounding box').not.toBeNull()
  return { name: 'Toggle theme', left: box!.x, right: box!.x + box!.width, top: box!.y, bottom: box!.y + box!.height }
}

function overlaps(a: Box, b: Box): boolean {
  return a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5
}

function centre(box: Box): number {
  return (box.top + box.bottom) / 2
}

async function expectOneRowWithoutOverlap(page: Page, width: number): Promise<Box[]> {
  const { boxes: items, headerHeight } = await headerBoxes(page)
  const toggle = await toggleBox(page)
  const boxes = [...items, toggle]
  const detail = JSON.stringify(boxes)
  const logo = items.find(box => box.name === 'Albiex Synth City')
  expect(logo, detail).toBeDefined()
  // One row: the toggle and the logo vertically overlap, and the header is one row high.
  expect(Math.abs(centre(toggle) - centre(logo!)), detail).toBeLessThanOrEqual(8)
  expect(headerHeight, detail).toBeLessThanOrEqual(70)
  for (const box of boxes) {
    expect(box.left, detail).toBeGreaterThanOrEqual(0)
    expect(box.right, detail).toBeLessThanOrEqual(width)
  }
  for (const [index, first] of boxes.entries()) {
    for (const second of boxes.slice(index + 1)) {
      expect(overlaps(first, second), `${first.name} overlaps ${second.name}: ${detail}`).toBe(false)
    }
  }
  return boxes
}

async function openHeader(page: Page, state: StatusState): Promise<void> {
  await page.goto('/')
  await expect(page.locator('header').first()).toBeVisible()
  if (state !== 'unloaded') {
    await expect(page.locator('header [title^="Albiex Synth City instance"]')).toBeVisible()
  }
}

const STATES: StatusState[] = ['loaded', 'long-name', 'cli-warning', 'unloaded']

for (const width of [390, 320]) {
  test.describe(`at ${width} px`, () => {
    test.use({ viewport: { width, height: 844 } })

    for (const state of STATES) {
      test(`@active the header is one row with the toggle beside the logo (${state})`, async ({ page }) => {
        const release = await serveStatus(page, state)
        try {
          await openHeader(page, state)
          await expectOneRowWithoutOverlap(page, width)
          if (state === 'loaded' && width === 390) {
            // The default instance name fits at 390 px. Only a long name may truncate.
            const clipped = await page.locator('header [title^="Albiex Synth City instance"] span.truncate')
              .evaluate(name => name.scrollWidth > name.clientWidth)
            expect(clipped, 'the default instance name is clipped').toBe(false)
          }
        } finally {
          release()
        }
      })
    }
  })
}

for (const width of [390, 320]) {
  test.describe(`the container warning at ${width} px`, () => {
    test.use({ viewport: { width, height: 844 }, hasTouch: true })

    test('@active opens by keyboard and by touch, and shows the full text', async ({ page }) => {
      await serveStatus(page, 'cli-warning')
      await openHeader(page, 'cli-warning')
      const warning = page.locator('header').getByRole('button', { name: new RegExp(WARNING_LABEL) })
      await expect(warning).toBeVisible()
      const box = await warning.boundingBox()
      expect(box!.width, 'the warning control has a visible box').toBeGreaterThanOrEqual(16)
      await expect(warning).toHaveAccessibleName(`${WARNING_LABEL}. ${WARNING}`)

      await warning.focus()
      await page.keyboard.press('Enter')
      const dialog = page.getByRole('dialog')
      await expect(dialog).toContainText(WARNING)
      await page.keyboard.press('Escape')
      await expect(dialog).toBeHidden()

      await warning.focus()
      await page.keyboard.press('Space')
      await expect(dialog).toContainText(WARNING)
      await page.keyboard.press('Escape')
      await expect(dialog).toBeHidden()
      await expect(warning, 'focus returns to the warning button').toBeFocused()

      await warning.tap()
      await expect(dialog).toContainText(WARNING)
      await page.keyboard.press('Escape')
      await expect(dialog).toBeHidden()
    })
  })
}

test.describe('at 1440 px', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  for (const state of STATES) {
    test(`@active the header keeps its desktop layout (${state})`, async ({ page }) => {
      const release = await serveStatus(page, state)
      try {
        await openHeader(page, state)
        const boxes = await expectOneRowWithoutOverlap(page, 1440)
        // The baseline: logo at the left padding (24 px), subtitle beside it, toggle at the right padding.
        const byName = (name: string) => boxes.find(box => box.name === name)
        expect(byName('Albiex Synth City')!.left).toBe(24)
        expect(byName('Your local agent command centre')).toBeDefined()
        expect(byName('Toggle theme')!.right).toBe(1440 - 24)
        if (state === 'cli-warning') {
          // From sm up the warning keeps its text.
          await expect(page.locator('header').getByRole('button', { name: new RegExp(WARNING_LABEL) })).toContainText(WARNING_LABEL)
        }
      } finally {
        release()
      }
    })
  }
})
