import type { APIResponse, Route } from '@playwright/test'

// route.fetch runs in Playwright's own HTTP client, over a pooled keep-alive
// socket. The browser retries a request on a reset socket by itself; the
// client does not. A reset that lands on a poll then fails the journey with
// "route.fetch: read ECONNRESET" (#916).

const CONNECTION_RESET = /ECONNRESET|socket hang up/i

export function isConnectionReset(error: unknown): boolean {
  return error instanceof Error && CONNECTION_RESET.test(error.message)
}

/**
 * Fetch the real answer for a routed request. One connection reset is retried
 * when `canRetry()` is true at the time of the reset. A second reset, and every
 * other error, is thrown unchanged.
 */
export async function routeFetch(route: Route, canRetry: () => boolean): Promise<APIResponse> {
  try {
    return await route.fetch()
  } catch (error) {
    if (!isConnectionReset(error) || !canRetry()) throw error
    return route.fetch()
  }
}

/** Which part of a flicker journey is running. */
export type FlickerPhase = { measured: boolean }

/**
 * Route handler for the summary reads of the Overview journey. Until the
 * measured windows start it serves emptied summaries, so the real summaries
 * complete exactly on the first measured poll (#847 F1). A reset is retried
 * only in that unmeasured phase. Once `phase.measured` is true a reset fails
 * the journey, because measured polling must stay strict.
 */
export function summaryRoute(phase: FlickerPhase): (route: Route) => Promise<void> {
  return async route => {
    const response = await routeFetch(route, () => !phase.measured)
    if (phase.measured) {
      await route.fulfill({ response })
      return
    }
    const body = await response.json() as Record<string, unknown>
    body.human_actions = []
    body.attention = []
    body.reminder_attention = []
    await route.fulfill({ response, json: body })
  }
}
