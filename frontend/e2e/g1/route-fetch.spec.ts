import type { APIResponse, Route } from '@playwright/test'
import { routeFetch, summaryRoute } from '../support/route-fetch'
import { expect, test } from '../support/guard'

// Self-test of the connection-reset retry (#916). The retry belongs to the
// unmeasured stabilization of the flicker journey only. These tests use a fake
// route, so a reset happens exactly when the test says.

const reset = () => new Error('route.fetch: read ECONNRESET')

type Step = Error | { body: unknown }

/** A route whose fetch plays `steps` in order and counts its calls. */
function fakeRoute(steps: Step[]) {
  const calls = { fetch: 0, fulfilled: [] as unknown[] }
  const route = {
    fetch: async () => {
      const step = steps[calls.fetch++]
      if (step instanceof Error) throw step
      return { json: async () => structuredClone(step.body) } as unknown as APIResponse
    },
    fulfill: async (options: unknown) => { calls.fulfilled.push(options) },
  } as unknown as Route
  return { route, calls }
}

const SUMMARY = { human_actions: [1], attention: [2], reminder_attention: [3], keep: 'x' }

test('@active one reset is retried and the second answer is returned', async () => {
  const { route, calls } = fakeRoute([reset(), { body: SUMMARY }])
  const response = await routeFetch(route, () => true)
  expect(await response.json()).toEqual(SUMMARY)
  expect(calls.fetch).toBe(2)
})

test('@active a second reset is thrown after one retry', async () => {
  const { route, calls } = fakeRoute([reset(), new Error('route.fetch: socket hang up'), { body: SUMMARY }])
  await expect(routeFetch(route, () => true)).rejects.toThrow('socket hang up')
  expect(calls.fetch).toBe(2)
})

test('@active an error that is not a reset is thrown without a retry', async () => {
  const { route, calls } = fakeRoute([new Error('route.fetch: connect ECONNREFUSED'), { body: SUMMARY }])
  await expect(routeFetch(route, () => true)).rejects.toThrow('ECONNREFUSED')
  expect(calls.fetch).toBe(1)
})

test('@active a reset is not retried when the caller refuses the retry', async () => {
  const { route, calls } = fakeRoute([reset(), { body: SUMMARY }])
  await expect(routeFetch(route, () => false)).rejects.toThrow('ECONNRESET')
  expect(calls.fetch).toBe(1)
})

// The wiring of the real summary handler to the phase of the journey.

test('@active the summary handler retries a reset before the measured windows', async () => {
  const phase = { measured: false }
  const { route, calls } = fakeRoute([reset(), { body: SUMMARY }])
  await summaryRoute(phase)(route)
  expect(calls.fetch).toBe(2)
  expect(calls.fulfilled).toEqual([{ response: expect.anything(), json: { ...SUMMARY, human_actions: [], attention: [], reminder_attention: [] } }])
})

test('@active the summary handler fails on a reset in the measured windows', async () => {
  const phase = { measured: true }
  const { route, calls } = fakeRoute([reset(), { body: SUMMARY }])
  await expect(summaryRoute(phase)(route)).rejects.toThrow('ECONNRESET')
  expect(calls.fetch).toBe(1)
  expect(calls.fulfilled).toEqual([])
})

test('@active a reset that lands after the measured windows began is not retried', async () => {
  // The phase flips while the first fetch is in flight, as in a real journey.
  const phase = { measured: false }
  const { route, calls } = fakeRoute([reset(), { body: SUMMARY }])
  const first = route.fetch.bind(route)
  route.fetch = async () => {
    try { return await first() } finally { phase.measured = true }
  }
  await expect(summaryRoute(phase)(route)).rejects.toThrow('ECONNRESET')
  expect(calls.fetch).toBe(1)
})

test('@active the measured summary handler passes the real answer through unchanged', async () => {
  const phase = { measured: true }
  const { route, calls } = fakeRoute([{ body: SUMMARY }])
  await summaryRoute(phase)(route)
  expect(calls.fulfilled).toEqual([{ response: expect.anything() }])
})
