import type { Page } from '@playwright/test'
import { expect, test } from '../support/guard'

// #865: the app header fits on one row at 390 px, so the theme toggle stays next
// to the logo. At 1440 px the header keeps its layout. No header item overlaps
// another or leaves the viewport, whatever the status state.

type StatusState = 'loaded' | 'long-name' | 'cli-warning' | 'unloaded'

const LONG_NAME = 'a-very-long-instance-name-for-this-host-01'

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
      body.environment = { ...body.environment, agent_cli_warning: 'Container cannot see host agent CLIs' }
    }
    await route.fulfill({ response, json: body })
  })
  return release
}

/** The visible items of the header: the logo, the subtitle, the badges and the toggle. */
async function headerBoxes(page: Page): Promise<{ boxes: Box[]; headerHeight: number }> {
  return page.locator('header').first().evaluate(header => {
    const row = header.firstElementChild as HTMLElement
    const items = [...row.children].flatMap(group => [...group.children]) as HTMLElement[]
    const boxes = items.flatMap(item => {
      const box = item.getBoundingClientRect()
      if (box.width === 0 || box.height === 0) return []
      const name = item.getAttribute('alt') ?? item.getAttribute('title') ?? item.textContent?.trim() ?? item.tagName
      return [{ name: name.slice(0, 40), left: box.left, right: box.right, top: box.top, bottom: box.bottom }]
    })
    return { boxes, headerHeight: header.getBoundingClientRect().height }
  })
}

function overlaps(a: Box, b: Box): boolean {
  return a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5
}

async function expectOneRowWithoutOverlap(page: Page, width: number): Promise<Box[]> {
  const { boxes, headerHeight } = await headerBoxes(page)
  const detail = JSON.stringify(boxes)
  const toggle = boxes.find(box => box.name === 'Toggle theme')
  const logo = boxes.find(box => box.name === 'Albiex Synth City')
  expect(logo, detail).toBeDefined()
  expect(toggle, detail).toBeDefined()
  // One row: the toggle and the logo vertically overlap, and the header is one row high.
  expect(Math.abs(centre(toggle!) - centre(logo!)), detail).toBeLessThanOrEqual(8)
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

function centre(box: Box): number {
  return (box.top + box.bottom) / 2
}

const STATES: StatusState[] = ['loaded', 'long-name', 'cli-warning', 'unloaded']

test.describe('at 390 px', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  for (const state of STATES) {
    test(`@active the header is one row with the toggle beside the logo (${state})`, async ({ page }) => {
      const release = await serveStatus(page, state)
      try {
        await page.goto('/')
        await expect(page.locator('header').first()).toBeVisible()
        if (state !== 'unloaded') {
          await expect(page.locator('header [title^="Albiex Synth City instance"]')).toBeVisible()
        }
        await expectOneRowWithoutOverlap(page, 390)
        if (state === 'loaded') {
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

test.describe('at 1440 px', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  for (const state of STATES) {
    test(`@active the header keeps its desktop layout (${state})`, async ({ page }) => {
      const release = await serveStatus(page, state)
      try {
        await page.goto('/')
        await expect(page.locator('header').first()).toBeVisible()
        if (state !== 'unloaded') {
          await expect(page.locator('header [title^="Albiex Synth City instance"]')).toBeVisible()
        }
        const boxes = await expectOneRowWithoutOverlap(page, 1440)
        // The baseline: logo at the left padding (24 px), subtitle beside it, toggle at the right padding.
        const byName = (name: string) => boxes.find(box => box.name === name)
        expect(byName('Albiex Synth City')!.left).toBe(24)
        expect(byName('Your local agent command centre')).toBeDefined()
        const toggle = byName('Toggle theme')!
        expect(toggle.right).toBe(1440 - 24)
      } finally {
        release()
      }
    })
  }
})
