import { expect, test } from '../support/guard'

// #545: a project-scoped Harness page points at a team member's folder without
// typing a path. The choice lives in the page URL. It is not shared with
// another browser, and the server-wide active project is never written.
// Folders are the seeded synthetic paths.
// @active

test.describe('Project selector on a Harness page', () => {
  test('@active a team member\'s folder scopes the page without typing a path', async ({ page, browser, baseURL }) => {
    const writes: string[] = []
    page.on('request', request => {
      if (request.method() !== 'GET' && /\/api\/v1\/projects\/active/.test(request.url())) writes.push(`${request.method()} ${request.url()}`)
    })

    await page.goto('/harnesses/claude-code/config')
    await expect(page.getByRole('heading', { name: 'Configuration' })).toBeVisible()
    const select = page.getByLabel('Project', { exact: true })
    await expect(select).toHaveValue('')

    const teamOptions = select.locator('optgroup[label="Team members\' folders"] option')
    await expect(teamOptions.first()).toBeAttached()
    const folder = await teamOptions.first().getAttribute('value')
    expect(folder, 'a seeded team folder').toBeTruthy()

    await select.selectOption(folder!)
    await expect(page).toHaveURL(new RegExp(`[?&]project=${encodeURIComponent(folder!).replaceAll('.', '\\.')}`))
    await expect(select).toHaveValue(folder!)
    await expect(page.getByRole('heading', { name: 'Configuration' })).toBeVisible()
    expect(writes, 'no server-wide active project write').toEqual([])

    // Another browser opens the same page and sees no project.
    const other = await browser.newContext({ baseURL })
    try {
      const otherPage = await other.newPage()
      await otherPage.goto('/harnesses/claude-code/config')
      await expect(otherPage.getByLabel('Project', { exact: true })).toHaveValue('')
    } finally {
      await other.close()
    }
  })

  test('@active the main navigation has no Local projects entry', async ({ page }) => {
    await page.goto('/')
    const nav = page.getByRole('navigation', { name: 'Main navigation' })
    await expect(nav.getByRole('link', { name: 'Work' })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'Local projects' })).toHaveCount(0)
  })

  test('@active an unknown project value shows no project and no error', async ({ page }) => {
    await page.goto('/harnesses/claude-code/config?project=%2Fnot%2Fa%2Fknown%2Ffolder')
    await expect(page.getByRole('heading', { name: 'Configuration' })).toBeVisible()
    await expect(page.getByLabel('Project', { exact: true })).toHaveValue('')
  })

  test('@active Folders Deck knows about explains what the folders do', async ({ page }) => {
    await page.goto('/harnesses/folders')
    await expect(page.getByRole('heading', { name: 'Folders Deck knows about' })).toBeVisible()
    await expect(page.getByText(/scope project-level native settings/)).toBeVisible()
  })
})
