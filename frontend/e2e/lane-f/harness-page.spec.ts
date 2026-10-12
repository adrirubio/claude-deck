import type { Locator } from '@playwright/test'
import { contrastFailures, useTheme, type Theme } from '../support/contrast'
import { expect, test } from '../support/guard'
import { expectKeyboardReachable } from '../support/keyboard'

// #524: every native page has a plain name and a one-line purpose on the
// harness page; no code name or access code is visible outside "Technical
// details"; the summary URL no longer shows a second harness picker.
// Design reference: screen 19 (harness page).
// @pending until #524 merges.

// Code names of the native surfaces, and access codes. A plain name such as
// "MCP servers" or "Settings" is fine; the lowercase code name is not.
const CODE_NAMES = /\b(config|mcp|plugins|commands|hooks|permissions|agents|skills|memory|backup|output-styles|output styles|statusline|sessions|plans|context|usage|summary)\b/
const ACCESS_CODES = /write capable|read only|write_capable|read_only/i

async function plainText(region: Locator): Promise<string> {
  return region.evaluate(root => {
    const clone = root.cloneNode(true) as Element
    clone.querySelectorAll('details').forEach(details => {
      if (/technical details/i.test(details.querySelector('summary')?.textContent ?? '')) details.remove()
    })
    return (clone.textContent ?? '').replace(/\s+/g, ' ')
  })
}

for (const harness of ['claude-code', 'codex-cli']) {
  test(`@pending ${harness}: each native page has a plain name and a one-line purpose`, async ({ page }) => {
    await page.goto(`/harnesses/${harness}`)
    const links = page.locator(`main a[href^="/harnesses/${harness}/"]`)
    await expect(links.first()).toBeVisible()
    for (const link of await links.all()) {
      const name = (await link.innerText()).trim()
      expect(name, 'a plain name starts with a capital letter').toMatch(/^[A-Z]/)
      expect(name).not.toMatch(ACCESS_CODES)
      const entry = link.locator('xpath=ancestor::*[self::li or self::article or contains(@class,"border")][1]')
      const purpose = (await entry.innerText()).replace(name, '').trim()
      expect(purpose.length, `a one-line purpose for ${name}`).toBeGreaterThan(10)
    }
  })

  test(`@pending ${harness}: no code name or access code outside Technical details`, async ({ page }) => {
    await page.goto(`/harnesses/${harness}`)
    await expect(page.locator('main')).toBeVisible()
    const text = await plainText(page.locator('main'))
    expect(text).not.toMatch(CODE_NAMES)
    expect(text).not.toMatch(ACCESS_CODES)
  })
}

test('@pending the summary URL shows no second harness picker', async ({ page }) => {
  await page.goto('/harnesses/claude-code/summary')
  await expect(page.locator('main')).toBeVisible()
  // Today the summary repeats an "Agent Providers" picker: one button for each
  // harness, the current one marked "Selected". The harness is already chosen.
  const otherHarness = /Codex|GitHub Copilot CLI|OpenCode CLI|^Pi\b/
  await expect(page.locator('main').getByRole('button', { name: otherHarness })).toHaveCount(0)
  await expect(page.locator('main select, main [role="combobox"]').filter({ hasText: otherHarness })).toHaveCount(0)
  await expect(page.locator('main').getByText('Selected', { exact: true })).toHaveCount(0)
})

for (const theme of ['light', 'dark'] as Theme[]) {
  test(`@pending the harness page meets AA contrast and is keyboard reachable in the ${theme} theme`, async ({ page }) => {
    await useTheme(page, theme)
    await page.goto('/harnesses/claude-code')
    await expect(page.locator('main a[href^="/harnesses/claude-code/"]').first()).toBeVisible()
    const failures = await contrastFailures(page.locator('main'))
    expect(failures, JSON.stringify(failures)).toEqual([])
    await expectKeyboardReachable(page, page.locator('main'), 3)
  })
}
