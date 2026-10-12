import { expect, test } from '../support/guard'

// #538: a page for an ID that does not exist stops polling after its 404 or
// 422. The guard fails the journey on any repeated request after a 4xx.
// @active since #538 merged into release/v3.1 (PR #568).

// Two 5-second polling intervals: a page that keeps polling repeats in this time.
const POLL_WINDOW_MS = 11_000

const cases = [
  { route: '/work/999999', api: /\/api\/v1\/factory\/work-items\/999999$/, status: 404 },
  { route: '/repositories/999999', api: /\/api\/v1\/factory\/repositories\/999999$/, status: 404 },
  { route: '/work/not-a-number', api: /\/api\/v1\/factory\/work-items\/not-a-number$/, status: 422 },
]

for (const { route, api, status } of cases) {
  test(`@active ${route} sends no request again after its ${status}`, async ({ page, guard }) => {
    guard.expectStatus('GET', api, status)
    const answered = page.waitForResponse(r => api.test(r.url()) && r.status() === status)
    await page.goto(route)
    await answered
    await page.waitForTimeout(POLL_WINDOW_MS)
    expect(guard.clientErrorKeys().length).toBeGreaterThan(0)
  })
}
