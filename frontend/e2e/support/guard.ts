import { test as base, expect, type Page, type Request, type Response } from '@playwright/test'
import { verifyInstance } from './instance-identity'

/**
 * Every journey fails on:
 * - a console error or an uncaught page error;
 * - a failed request, or a 4xx/5xx response that the journey did not expect;
 * - a request to any origin other than the isolated instance;
 * - a repeated request (same method and URL) after a 4xx response.
 * A journey declares an expected status with `guard.expectStatus()`.
 */

type ExpectedStatus = { method: string; url: RegExp; status: number }

export class Guard {
  readonly violations: string[] = []
  private readonly expected: ExpectedStatus[] = []
  private readonly clientErrors = new Map<string, number>()
  private readonly origin: string

  constructor(baseURL: string) {
    this.origin = new URL(baseURL).origin
  }

  /** Declare that `method url` may answer `status`. A repeat after a 4xx still fails. */
  expectStatus(method: string, url: RegExp, status: number): void {
    this.expected.push({ method: method.toUpperCase(), url, status })
  }

  /** Requests that answered 4xx, keyed by `METHOD path?query`. */
  clientErrorKeys(): string[] {
    return [...this.clientErrors.keys()]
  }

  isExpected(method: string, url: string, status: number): boolean {
    return this.expected.some(e => e.method === method && e.status === status && e.url.test(url))
  }

  isLocal(url: string): boolean {
    return url.startsWith('data:') || url.startsWith('blob:') || url.startsWith(`${this.origin}/`) || url === this.origin
  }

  key(request: Request): string {
    const url = new URL(request.url())
    return `${request.method()} ${url.pathname}${url.search}`
  }

  onRequest(request: Request): void {
    const key = this.key(request)
    if (this.clientErrors.has(key)) {
      this.violations.push(`repeated request after ${this.clientErrors.get(key)}: ${key}`)
    }
  }

  onResponse(response: Response): void {
    const request = response.request()
    const status = response.status()
    if (status < 400 || !this.isLocal(request.url())) return
    const key = this.key(request)
    if (status < 500) this.clientErrors.set(key, status)
    if (!this.isExpected(request.method(), request.url(), status)) {
      this.violations.push(`unexpected ${status}: ${key}`)
    }
  }

  onRequestFailed(request: Request): void {
    const failure = request.failure()?.errorText ?? 'unknown'
    // The browser aborts in-flight polling when a journey navigates away.
    if (failure.includes('ERR_ABORTED')) return
    if (!this.isLocal(request.url())) return // reported by the route block
    this.violations.push(`failed request (${failure}): ${this.key(request)}`)
  }

  onConsoleError(text: string, locationUrl: string): void {
    // Chromium logs each 4xx/5xx resource load; onResponse already judged it.
    if (text.startsWith('Failed to load resource') && this.isLocal(locationUrl)) return
    this.violations.push(`console error: ${text}`)
  }
}

export async function attachGuard(page: Page, guard: Guard): Promise<void> {
  await page.context().route('**/*', route => {
    const url = route.request().url()
    if (guard.isLocal(url)) return route.continue()
    guard.violations.push(`request outside the instance: ${route.request().method()} ${url}`)
    return route.abort('blockedbyclient')
  })
  page.on('request', r => guard.onRequest(r))
  page.on('response', r => guard.onResponse(r))
  page.on('requestfailed', r => guard.onRequestFailed(r))
  page.on('console', msg => {
    if (msg.type() === 'error') guard.onConsoleError(msg.text(), msg.location().url)
  })
  page.on('pageerror', err => guard.violations.push(`page error: ${err.message}`))
}

export const test = base.extend<{ guard: Guard }, { ownInstance: void }>({
  // Before the first journey of each worker: refuse a server that is not this
  // run's test instance (#590).
  // eslint-disable-next-line no-empty-pattern
  ownInstance: [async ({}, use, workerInfo) => {
    await verifyInstance(String(workerInfo.project.use.baseURL), process.env.E2E_RUN_TOKEN)
    await use()
  }, { scope: 'worker', auto: true }],
  guard: [async ({ page, baseURL }, use, testInfo) => {
    const guard = new Guard(baseURL ?? 'http://127.0.0.1')
    await attachGuard(page, guard)
    await use(guard)
    // Let polling and late responses arrive before the final judgment.
    await page.waitForLoadState('networkidle').catch(() => undefined)
    if (guard.violations.length) {
      await testInfo.attach('guard-violations', {
        body: guard.violations.join('\n'),
        contentType: 'text/plain',
      })
    }
    expect(guard.violations, 'guard violations').toEqual([])
  }, { auto: true }],
})

export { expect }
