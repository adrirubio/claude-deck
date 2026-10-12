import { expect, test } from '../support/guard'

// Self-test of the guard fixture: each rule records a violation. Each journey
// clears the violations it caused on purpose, so the fixture passes after it.

test('@active the guard records an unexpected 4xx', async ({ page, guard }) => {
  await page.goto('/')
  await page.evaluate(() => fetch('/api/v1/factory/work-items/999999'))
  await expect.poll(() => guard.violations.join('\n')).toContain('unexpected 404: GET /api/v1/factory/work-items/999999')
  guard.violations.length = 0
})

test('@active the guard accepts a declared status and fails a repeat after it', async ({ page, guard }) => {
  guard.expectStatus('GET', /\/api\/v1\/factory\/work-items\/999999$/, 404)
  await page.goto('/')
  await page.evaluate(() => fetch('/api/v1/factory/work-items/999999'))
  await expect.poll(() => guard.clientErrorKeys()).toContain('GET /api/v1/factory/work-items/999999')
  expect(guard.violations).toEqual([])
  await page.evaluate(() => fetch('/api/v1/factory/work-items/999999'))
  await expect.poll(() => guard.violations.join('\n')).toContain('repeated request after 404')
  guard.violations.length = 0
})

test('@active the guard blocks a request outside the instance', async ({ page, guard }) => {
  await page.goto('/')
  await page.evaluate(() => fetch('https://example.invalid/e2e').catch(() => undefined))
  await expect.poll(() => guard.violations.join('\n')).toContain('request outside the instance: GET https://example.invalid/e2e')
  guard.violations.length = 0
})

test('@active the guard records a console error', async ({ page, guard }) => {
  await page.goto('/')
  await page.evaluate(() => console.error('e2e guard self-test'))
  await expect.poll(() => guard.violations.join('\n')).toContain('console error: e2e guard self-test')
  guard.violations.length = 0
})
