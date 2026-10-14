import type { Page, Response } from '@playwright/test'
import { expect, test } from '../support/guard'

// #698: a routine background refresh must not change a Factory screen. The
// shared read store polls every 5 seconds. With data already shown, nothing
// may appear and then disappear, nothing may shift, and nothing may be
// announced to a screen reader.
// The seed has no user input here, so every layout shift counts. The limit is
// 0.001 in total. Only the text of relative times may change between polls.

const SCREENS = [
  { name: 'Overview', route: '/', heading: 'Overview' },
  { name: 'Work', route: '/work', heading: 'Work' },
  // Item 1 is #101: a dispatched item, so the page shows the progress panel.
  { name: 'Work item', route: '/work/1', heading: /#101/ },
  { name: 'Repositories', route: '/repositories', heading: 'Repositories' },
  { name: 'Repository', route: '/repositories/1', heading: /example-org\/sample-app/ },
] as const

const SHIFT_LIMIT = 0.001
// Two full poll cycles of 5 seconds, and a margin for the request time.
const WATCH_MS = 11_500

type Watched = { shift: number; transient: string[]; announced: string[] }

/** Start the observers in the page. Call `read()` later to get the result. */
async function watch(page: Page): Promise<void> {
  await page.evaluate(() => {
    const previous = window as unknown as { __flickerStop?: () => void }
    previous.__flickerStop?.()
    const state = { shift: 0, transient: [] as string[], announced: [] as string[] }
    const added = new WeakSet<Node>()
    const describe = (element: Element) => {
      const text = (element.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 60)
      return `<${element.tagName.toLowerCase()}> "${text}"`
    }
    const each = (node: Node, visit: (element: Element) => void) => {
      if (node.nodeType !== Node.ELEMENT_NODE) return
      visit(node as Element)
      ;(node as Element).querySelectorAll('*').forEach(visit)
    }
    const shifts = new PerformanceObserver(list => {
      for (const entry of list.getEntries() as unknown as { value: number; hadRecentInput: boolean }[]) {
        if (!entry.hadRecentInput) state.shift += entry.value
      }
    })
    shifts.observe({ type: 'layout-shift', buffered: false })
    const mutations = new MutationObserver(records => {
      for (const record of records) {
        record.addedNodes.forEach(node => {
          each(node, element => {
            added.add(element)
            // A polite live region announces the text that appears in it.
            const live = element.closest('[aria-live]:not([aria-live="off"]), [role="status"], [role="alert"]')
            const role = live?.getAttribute('role')
            if (live && role !== 'alert') state.announced.push(describe(element))
          })
          if (node.nodeType === Node.TEXT_NODE && node.parentElement) {
            const live = node.parentElement.closest('[aria-live]:not([aria-live="off"]), [role="status"]')
            if (live) state.announced.push(`text "${(node.textContent ?? '').trim().slice(0, 60)}"`)
          }
        })
        record.removedNodes.forEach(node => {
          each(node, element => {
            if (added.has(element)) state.transient.push(describe(element))
          })
        })
      }
    })
    mutations.observe(document.body, { childList: true, subtree: true })
    previous.__flickerStop = () => { shifts.disconnect(); mutations.disconnect() }
    ;(window as unknown as { __flicker: typeof state }).__flicker = state
  })
}

/** Record every label and disabled state of the "Refresh progress" button. */
async function watchProgressButton(page: Page): Promise<void> {
  await page.evaluate(() => {
    const button = [...document.querySelectorAll('main button')]
      .find(element => /^Refresh(ing)?/.test(element.textContent ?? ''))
    if (!button) throw new Error('The Refresh progress button is missing')
    const stop = window as unknown as { __buttonStop?: () => void }
    stop.__buttonStop?.()
    const seen = new Set<string>()
    const note = () => seen.add(`${(button.textContent ?? '').trim()}|${(button as HTMLButtonElement).disabled ? 'disabled' : 'enabled'}`)
    note()
    const mutations = new MutationObserver(note)
    mutations.observe(button, { childList: true, subtree: true, characterData: true, attributes: true })
    stop.__buttonStop = () => mutations.disconnect()
    ;(window as unknown as { __button: Set<string> }).__button = seen
  })
}

async function readProgressButton(page: Page): Promise<string[]> {
  return page.evaluate(() => [...(window as unknown as { __button: Set<string> }).__button])
}

async function read(page: Page): Promise<Watched> {
  return page.evaluate(() => (window as unknown as { __flicker: Watched }).__flicker)
}

// A flicker is a visible change that a refresh causes when the data is the same.
// If a polled answer itself changed during the window (for example a slow host
// made one summary report itself incomplete), the page shows the new data and
// that is correct. Such a window proves nothing, so the journey watches again.
const ATTEMPTS = 3
// Timestamps and the seconds counter of a relative time change by themselves.
const TIME = /\d{4}-\d\d-\d\d[T ][\d:.]+(?:Z|[+-]\d\d:\d\d)?|"elapsed_seconds":\s*\d+/g

async function watchWindow(page: Page, screen: (typeof SCREENS)[number]) {
  const bodies = new Map<string, Set<string>>()
  const onResponse = async (response: Response) => {
    const request = response.request()
    if (request.method() !== 'GET' || !response.url().includes('/api/v1/') || response.status() !== 200) return
    const body = await response.text().catch(() => null)
    if (body === null) return
    const key = new URL(response.url()).pathname + new URL(response.url()).search
    bodies.set(key, (bodies.get(key) ?? new Set()).add(body.replace(TIME, 'T')))
  }
  page.on('response', onResponse)
  await watch(page)
  if (screen.name === 'Work item') await watchProgressButton(page)
  // The Work item page reads its progress every 15 seconds. Wait for one.
  const progress = screen.name === 'Work item'
    ? page.waitForResponse(response => /\/progress$/.test(response.url()), { timeout: 20_000 })
    : Promise.resolve(null)
  await page.waitForTimeout(WATCH_MS)
  await progress
  const result = await read(page)
  const buttons = screen.name === 'Work item' ? await readProgressButton(page) : null
  page.off('response', onResponse)
  const changed = [...bodies].filter(([, set]) => set.size > 1).map(([key]) => key)
  return { result, buttons, changed }
}

for (const screen of SCREENS) {
  test(`@active ${screen.name} shows no flicker during two background polls`, async ({ page }) => {
    test.setTimeout(100_000)
    await page.goto(screen.route)
    await expect(page.getByRole('heading', { name: screen.heading, exact: typeof screen.heading === 'string' }).first()).toBeVisible()
    // Settled: no loading text, and the first reads are done.
    await expect(page.locator('main').getByText(/^Loading/)).toHaveCount(0)
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(1_500)

    let watched = await watchWindow(page, screen)
    for (let attempt = 1; attempt < ATTEMPTS && watched.changed.length; attempt++) watched = await watchWindow(page, screen)
    const { result, buttons, changed } = watched

    expect.soft(changed, `the polled data kept changing in ${ATTEMPTS} windows on ${screen.route}`).toEqual([])
    expect.soft(result.transient, `elements that appeared and then disappeared on ${screen.route}`).toEqual([])
    expect.soft(result.announced, `text added to a live region on ${screen.route}`).toEqual([])
    expect.soft(result.shift, `layout shift on ${screen.route}`).toBeLessThanOrEqual(SHIFT_LIMIT)
    // An automatic poll leaves the button label and state alone.
    if (buttons) expect.soft(buttons, 'labels and states of the Refresh progress button').toEqual(['Refresh progress|enabled'])
  })
}
