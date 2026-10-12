import { expect, test } from '../support/guard'

// #535: a merged item keeps no active continuation revision, and the metrics
// report active_revisions 0 when all items with revisions are finished.
// Seed (scripts/e2e/scenarios.py, seed_lane_g): merged item #104 has a
// revision row in the "active" state. The #535 fix reconciles it through the
// supported path; the implementer runs that path in the seed if it is not
// part of the instance start.
// The item page shows the item's own revision pointer ("Active revision 0:
// none"), which is correct today; the defect is visible in the metrics.
// @pending until #535 merges.

interface Metric { name?: string; value?: number }

/** Every object with a "name" in the metrics response, at any depth. */
function metrics(node: unknown, found: Metric[] = []): Metric[] {
  if (Array.isArray(node)) node.forEach(child => metrics(child, found))
  else if (node && typeof node === 'object') {
    if ('name' in node) found.push(node as Metric)
    Object.values(node).forEach(child => metrics(child, found))
  }
  return found
}

test('@pending finished work reports no active continuation revision', async ({ request }) => {
  const end = new Date()
  const start = new Date(end.getTime() - 7 * 24 * 3600 * 1000)
  const response = await request.get('/api/v1/factory/metrics', {
    params: { window_start: start.toISOString(), window_end: end.toISOString(), filter_scope: 'all' },
  })
  expect(response.ok()).toBe(true)
  const active = metrics(await response.json()).find(metric => metric.name === 'active_revisions')
  expect(active, 'the metrics report active_revisions').toBeDefined()
  expect(active?.value).toBe(0)
})
