import { expect, test } from '../support/guard'

// #546: loading any page with no active project logs no console error. The
// seed sets no active project. The guard fails a journey on any console error
// and on any unexpected 4xx, for example a 404 from GET /api/v1/projects/active.
// #546 is merged. These journeys are active.

const ROUTES = [
  '/', '/work', '/repositories', '/teams', '/agent-bridge', '/agent-mail', '/audit',
  '/harnesses', '/harnesses/claude-code', '/harnesses/claude-code/config', '/projects',
]

for (const route of ROUTES) {
  test(`@active ${route} loads with no active project and no console error`, async ({ page, guard }) => {
    await page.goto(route)
    await expect(page.locator('main')).toBeVisible()
    await page.waitForLoadState('networkidle').catch(() => undefined)
    const activeProject = guard.clientErrorKeys().filter(key => key.includes('/projects/active'))
    expect(activeProject, 'no 4xx for the active project').toEqual([])
  })
}
