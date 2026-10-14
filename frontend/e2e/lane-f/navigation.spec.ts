import type { Page } from '@playwright/test'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #522: from any native page, one click reaches the harness page and one more
// reaches all harnesses; one click reaches any other native page of the same
// harness; each native page has its own heading and tab title.
// Design reference: screens 19 (harness page) and 20 (settings page).
// @active since #522 merged.

const HARNESSES = ['claude-code', 'codex-cli']

/** The native page links that the harness page lists, as paths. */
async function nativePages(page: Page, harness: string): Promise<string[]> {
  await page.goto(`/harnesses/${harness}`)
  await expect(page.locator('main')).toBeVisible()
  // The tiles appear after the registry and the catalog load (the skeleton card shows first).
  await expect(page.locator(`main a[href^="/harnesses/${harness}/"]`).first()).toBeVisible()
  const hrefs = await page.locator(`main a[href^="/harnesses/${harness}/"]`).evaluateAll(
    links => links.map(link => link.getAttribute('href') ?? ''),
  )
  return [...new Set(hrefs.map(href => href.split('?')[0]))]
}

for (const harness of HARNESSES) {
  test(`@active ${harness}: breadcrumbs reach the harness page, then all harnesses`, async ({ page }) => {
    const pages = await nativePages(page, harness)
    expect(pages.length).toBeGreaterThan(0)
    await page.goto(pages[0])
    const breadcrumb = page.getByRole('navigation', { name: /breadcrumb/i })
    await expect(breadcrumb).toBeVisible()
    await breadcrumb.locator(`a[href="/harnesses/${harness}"]`).click()
    await expect(page).toHaveURL(new RegExp(`/harnesses/${harness}$`))
    await page.getByRole('navigation', { name: /breadcrumb/i }).locator('a[href="/harnesses"]').click()
    await expect(page).toHaveURL(/\/harnesses$/)
  })

  test(`@active ${harness}: a native page links to every other native page of the harness`, async ({ page }) => {
    const pages = await nativePages(page, harness)
    await page.goto(pages[0])
    const subnav = page.getByRole('navigation', { name: new RegExp(harness.replace('-cli', '') + '|pages|settings', 'i') })
      .filter({ hasNot: page.getByRole('link', { name: 'Overview', exact: true }) })
    await expect(subnav.first()).toBeVisible()
    const linked = await subnav.first().locator('a').evaluateAll(links => links.map(link => (link.getAttribute('href') ?? '').split('?')[0]))
    for (const other of pages.slice(1)) expect(linked, `a link to ${other}`).toContain(other)
  })

  test(`@active ${harness}: each native page has its own heading and tab title`, async ({ page }) => {
    const pages = await nativePages(page, harness)
    const titles: string[] = []
    const headings: string[] = []
    for (const path of pages) {
      await page.goto(path)
      const heading = page.locator('main').getByRole('heading').first()
      await expect(heading).toBeVisible()
      headings.push((await heading.innerText()).trim())
      titles.push(await page.title())
    }
    expect(new Set(titles).size, `distinct tab titles: ${JSON.stringify(titles)}`).toBe(pages.length)
    expect(new Set(headings).size, `distinct headings: ${JSON.stringify(headings)}`).toBe(pages.length)
    expect(titles.filter(title => title === 'Claude Deck'), 'no page keeps the bare app title').toEqual([])
  })
}

test('@active the breadcrumbs and sub-navigation are keyboard reachable', async ({ page }) => {
  await page.goto('/harnesses/claude-code/mcp')
  await expectKeyboardReachable(page, page.getByRole('navigation', { name: /breadcrumb/i }), 2)
})
