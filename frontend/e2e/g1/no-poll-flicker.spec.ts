import type { Page, Response } from '@playwright/test'
import { expect, test } from '../support/guard'
import { summaryRoute, type FlickerPhase } from '../support/route-fetch'

// #698: a routine background refresh must not change a Factory screen. The
// shared read store polls every 5 seconds. With data already shown, nothing
// may appear and then disappear, nothing may shift, and nothing may be
// announced to a screen reader.
// The seed has no user input here, so every layout shift counts. The limit is
// 0.001 in total. Only the text of relative times may change between polls.
// Text that changes and then changes back is a flicker too, for example labels
// that briefly read "Previous phase" while a refresh is in flight.

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
    // Each text node's values in this window. Digits are masked, so clocks and
    // relative times that tick are one value.
    const texts = new WeakMap<Node, string[]>()
    const mask = (value: string | null) => (value ?? '').replace(/\d/g, '#').trim()
    const noteText = (node: Node, before: string | null) => {
      const seen = texts.get(node) ?? [mask(before)]
      const now = mask(node.textContent)
      if (now === seen[seen.length - 1]) return
      if (seen.includes(now)) state.transient.push(`text "${seen[seen.length - 1].slice(0, 60)}"`)
      seen.push(now)
      texts.set(node, seen)
    }
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
        if (record.type === 'characterData') { noteText(record.target, record.oldValue); continue }
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
    mutations.observe(document.body, { childList: true, subtree: true, characterData: true, characterDataOldValue: true })
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

/** The last masked body seen for each API read on one page. */
type BodyBaseline = Map<string, string>

/**
 * Collect the masked body of every API read until `stop()` is called. The
 * collection starts from `baseline`, the last body seen for each read before
 * this window, and keeps it updated: a read whose body differs from what the
 * previous window rendered is therefore reported as changed data, even when
 * it only arrives once, on the first poll of this window.
 */
function trackBodies(page: Page, baseline: BodyBaseline) {
  const bodies = new Map([...baseline].map(([key, body]) => [key, new Set([body])]))
  const onResponse = async (response: Response) => {
    const request = response.request()
    if (request.method() !== 'GET' || !response.url().includes('/api/v1/') || response.status() !== 200) return
    const body = await response.text().catch(() => null)
    if (body === null) return
    const key = new URL(response.url()).pathname + new URL(response.url()).search
    const masked = body.replace(TIME, 'T')
    baseline.set(key, masked)
    bodies.set(key, (bodies.get(key) ?? new Set()).add(masked))
  }
  page.on('response', onResponse)
  return { bodies, stop: () => page.off('response', onResponse) }
}

/** One unmeasured poll cycle, as a comparable snapshot of its masked bodies. */
async function pollCycleSnapshot(page: Page, baseline: BodyBaseline): Promise<string> {
  const { bodies, stop } = trackBodies(page, baseline)
  await page.waitForTimeout(WATCH_MS)
  stop()
  return [...bodies]
    .map(([key, set]) => `${key}\n${[...set].sort().join('\n')}`)
    .sort()
    .join('\n---\n')
}

// Measuring from the first render is not enough: a slow first read can still
// complete at the first background poll, and that new data correctly grows the
// page and shifts what is below it (#847). So first wait for a stable state:
// fonts settled, then unmeasured poll cycles until two consecutive cycles
// produce identical masked body sets. Masking can only hide timestamp/elapsed
// fields, so a change in any other field breaks the equality and keeps the
// cycles running. If the cycles never agree, stop anyway: the measured window
// then runs and its changed-data assertion reports the changing data instead
// of passing quietly. The baseline of last-seen bodies is kept across
// stabilization and every measured window, so a body that only completes on
// the first measured poll still counts as changed data and that window is
// re-watched instead of blaming its shift on the poll.
async function stabilize(page: Page, baseline: BodyBaseline): Promise<void> {
  await page.evaluate(() => document.fonts.ready.then(() => undefined))
  let previous: string | null = null
  for (let cycle = 0; cycle < ATTEMPTS; cycle++) {
    const current = await pollCycleSnapshot(page, baseline)
    if (current === previous) break
    previous = current
  }
  // Let the last cycle's answers render before the observers start.
  await page.waitForLoadState('networkidle')
}

async function watchWindow(page: Page, screen: (typeof SCREENS)[number], baseline: BodyBaseline) {
  const { bodies, stop } = trackBodies(page, baseline)
  await watch(page)
  if (screen.name === 'Work item') await watchProgressButton(page)
  // The Work item page reads its progress every 15 seconds. Wait for one.
  const progress = screen.name === 'Work item'
    ? page.waitForResponse(response => /\/progress$/.test(response.url()), { timeout: 20_000 })
    : Promise.resolve(null)
  await page.waitForTimeout(WATCH_MS)
  // Read after the page has rendered the progress answer, not the moment it arrives.
  if (await progress) await page.waitForTimeout(1_000)
  const result = await read(page)
  const buttons = screen.name === 'Work item' ? await readProgressButton(page) : null
  stop()
  const changed = [...bodies].filter(([, set]) => set.size > 1).map(([key]) => key)
  return { result, buttons, changed }
}

async function expectNoFlicker(page: Page, screen: (typeof SCREENS)[number], beforeMeasured?: () => void) {
  await page.goto(screen.route)
  await expect(page.getByRole('heading', { name: screen.heading, exact: typeof screen.heading === 'string' }).first()).toBeVisible()
  // Settled: no loading text, and the first reads are done.
  await expect(page.locator('main').getByText(/^Loading/)).toHaveCount(0)
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(1_500)
  // Stable: the same masked data has rendered through two whole poll cycles.
  // The baseline starts empty for this page and is carried into every window.
  const baseline: BodyBaseline = new Map()
  await stabilize(page, baseline)
  beforeMeasured?.()

  let watched = await watchWindow(page, screen, baseline)
  for (let attempt = 1; attempt < ATTEMPTS && watched.changed.length; attempt++) watched = await watchWindow(page, screen, baseline)
  const { result, buttons, changed } = watched

  expect.soft(changed, `the polled data kept changing in ${ATTEMPTS} windows on ${screen.route}`).toEqual([])
  expect.soft(result.transient, `elements that appeared and then disappeared on ${screen.route}`).toEqual([])
  expect.soft(result.announced, `text added to a live region on ${screen.route}`).toEqual([])
  expect.soft(result.shift, `layout shift on ${screen.route}`).toBeLessThanOrEqual(SHIFT_LIMIT)
  // An automatic poll leaves the button label and state alone.
  if (buttons) expect.soft(buttons, 'labels and states of the Refresh progress button').toEqual(['Refresh progress|enabled'])
}

for (const screen of SCREENS) {
  test(`@active ${screen.name} shows no flicker during two background polls`, async ({ page }) => {
    // Stabilization adds up to ATTEMPTS unmeasured poll cycles before the
    // measured windows, so the journey needs a larger time budget than before.
    test.setTimeout(240_000)
    await expectNoFlicker(page, screen)
  })
}

// Regression for #847 F1: a summary that only completes on the first measured
// poll changes the data, so that window proves nothing and must be re-watched
// instead of reporting its legitimate data-driven shift as flicker. The route
// below serves emptied summaries until the measured windows start, then serves
// the real summaries, so the completion lands exactly on the first measured poll.
test('@active Overview re-watches when a summary completes on the first measured poll', async ({ page }) => {
  test.setTimeout(240_000)
  // One reset of the summary read is retried before the measured windows only
  // (#916). In the measured windows a reset fails the journey.
  const phase: FlickerPhase = { measured: false }
  await page.route('**/api/v1/agent-teams/presets/*/summary', summaryRoute(phase))
  await expectNoFlicker(page, SCREENS[0], () => { phase.measured = true })
})
