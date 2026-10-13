import { contrastFailures, SETTLE_TIMEOUT_MS } from '../support/contrast'
import { expect, test } from '../support/guard'

// Self-test of the contrast helper (#644). A real low-contrast element fails;
// a colour transition is measured only after it ends; a transition that does
// not end within the settle time fails the measurement instead of hanging it.

async function addSample(page: import('@playwright/test').Page, style: string): Promise<void> {
  await page.evaluate(css => {
    const sample = document.createElement('p')
    sample.id = 'e2e-contrast-sample'
    sample.textContent = 'Contrast sample'
    sample.setAttribute('style', `font-size:14px;padding:8px;${css}`)
    document.querySelector('main')?.prepend(sample)
  }, style)
}

test('@active a low-contrast element fails the AA check', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  await addSample(page, 'color:rgb(150,150,150);background:rgb(200,200,200)')
  const failures = await contrastFailures(page.locator('#e2e-contrast-sample'))
  expect(failures.map(failure => failure.text)).toEqual(['Contrast sample'])
  expect(failures[0].ratio).toBeLessThan(4.5)
})

test('@active a colour transition is measured only after it ends', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  // Low contrast at the start, high contrast at the end, 600 ms in between.
  await addSample(page, 'color:rgb(150,150,150);background:rgb(200,200,200);transition:color 600ms linear,background-color 600ms linear')
  await page.evaluate(() => {
    const sample = document.getElementById('e2e-contrast-sample') as HTMLElement
    void sample.offsetWidth
    sample.style.color = 'rgb(10,10,10)'
    sample.style.backgroundColor = 'rgb(250,250,250)'
  })
  expect(await contrastFailures(page.locator('#e2e-contrast-sample'))).toEqual([])
})

test('@active a transition that does not end in time fails the measurement', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  await addSample(page, `color:rgb(10,10,10);transition:color ${SETTLE_TIMEOUT_MS * 4}ms linear`)
  await page.evaluate(() => {
    const sample = document.getElementById('e2e-contrast-sample') as HTMLElement
    void sample.offsetWidth
    sample.style.color = 'rgb(20,20,20)'
  })
  await expect(contrastFailures(page.locator('#e2e-contrast-sample'))).rejects.toThrow(/did not settle/)
})
