import { enterDirectorKey, expectDirectorKeyDialog } from '../support/director-key'
import { expect, test } from '../support/guard'

// Gate G0: every Director route loads with no console error, no unexpected
// failed request and no repeated request after a 4xx (the guard checks this).
// Seeded names come from scripts/e2e/scenarios.py.

// Page titles use h1 or h2 depending on the page; match the exact name.
const heading = (name: string | RegExp) => ({ name, exact: typeof name === 'string' })

test('@active Overview loads', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', heading('Overview'))).toBeVisible()
  // #508: the status tiles replace the sentence "5 matching work items". The seed has one item in each state.
  for (const name of ['Needs attention', 'In progress', 'Needs review', 'Queued', 'Finished']) {
    await expect(page.getByRole('link', { name: new RegExp(`^${name}\\s*1$`) })).toBeVisible()
  }
})

test('@active Work lists the seeded items', async ({ page }) => {
  await page.goto('/work')
  await expect(page.getByRole('heading', heading('Work'))).toBeVisible()
  for (const title of ['Add the CSV export button', 'Fix the settings page layout', 'Add keyboard shortcuts']) {
    await expect(page.getByText(title).first()).toBeVisible()
  }
})

test('@active a work item loads', async ({ page }) => {
  await page.goto('/work/2')
  await expect(page.getByRole('heading', heading(/Fix the settings page layout/))).toBeVisible()
  await expect(page.getByText('Fix the settings page layout').first()).toBeVisible()
  await expect(page.getByText(/Ready for human review/).first()).toBeVisible()
})

test('@active Repositories lists the seeded scopes', async ({ page }) => {
  await page.goto('/repositories')
  await expect(page.getByRole('heading', heading('Repositories'))).toBeVisible()
  // The Repository filter select also lists these names, as options. Match the table links.
  await expect(page.getByRole('link', { name: 'example-org/sample-app' }).first()).toBeVisible()
  await expect(page.getByRole('link', { name: 'example-org/quiet-lib' }).first()).toBeVisible()
})

test('@active a repository loads', async ({ page }) => {
  await page.goto('/repositories/1')
  await expect(page.getByRole('heading', heading('example-org/sample-app'))).toBeVisible()
  await expect(page.getByText('example-org/sample-app').first()).toBeVisible()
})

test('@active Teams lists the seeded teams', async ({ page }) => {
  await page.goto('/teams')
  await expect(page.getByRole('heading', heading('Agent Teams'))).toBeVisible()
  await expect(page.getByText('Release crew').first()).toBeVisible()
  await expect(page.getByText('Quiet team').first()).toBeVisible()
})

test('@active a team shows its eight members', async ({ page }) => {
  await page.goto('/teams/1?tab=roster')
  await expect(page.getByRole('heading', heading('Agent Teams'))).toBeVisible()
  for (const member of ['L1 Leader', 'B1 Backend', 'F1 Frontend', 'V1 Verifier']) {
    await expect(page.getByText(member).first()).toBeVisible()
  }
})

test('@active Live sessions shows the fake team panes', async ({ page }) => {
  test.skip(process.env.E2E_NO_TMUX === '1', 'E2E_NO_TMUX=1: the instance has no tmux server')
  await page.goto('/agent-bridge')
  await expect(page.getByRole('heading', heading('Agent Bridge'))).toBeVisible()
  await expect(page.getByRole('button', { name: /^Release crew \(4\)$/ })).toBeVisible()
  await expect(page.getByText('tmux: deck-e2e-1:0.0')).toBeVisible()
})

test('@active Team lanes shows the release crew', async ({ page }) => {
  test.skip(process.env.E2E_NO_TMUX === '1', 'E2E_NO_TMUX=1: the instance has no tmux server')
  await page.goto('/agent-bridge')
  await page.getByRole('button', { name: /^Release crew \(4\)$/ }).click()
  await page.getByRole('button', { name: 'Team lanes' }).click()
  await expect(page.getByText('Team lanes').first()).toBeVisible()
  await expect(page.getByText(/4 shown/)).toBeVisible()
})

test('@active Agent Mail shows unacknowledged messages', async ({ page }) => {
  await page.goto('/agent-mail')
  await expect(page.getByRole('heading', heading('Agent Mail'))).toBeVisible()
  await expect(page.getByText(/\d+ unread/).first()).toBeVisible()
})

test('@active Audit is locked, then opens with the Director key', async ({ page }) => {
  await page.goto('/audit')
  await expect(page.getByRole('heading', heading('Audit coverage and delivery metrics'))).toBeVisible()
  await expectDirectorKeyDialog(page)
  await enterDirectorKey(page)
  await expect(page.getByText(/Delivery in this window/).first()).toBeVisible()
})

test('@active Harnesses lists the providers', async ({ page }) => {
  await page.goto('/harnesses')
  await expect(page.getByRole('heading', heading('Harnesses'))).toBeVisible()
  await expect(page.getByText('Claude Code').first()).toBeVisible()
})

test('@active a harness loads', async ({ page }) => {
  await page.goto('/harnesses/claude-code')
  await expect(page.getByRole('heading', heading('Claude Code'))).toBeVisible()
})

test('@active a harness settings page loads', async ({ page }) => {
  await page.goto('/harnesses/claude-code/config')
  await expect(page.getByRole('heading', heading('Configuration'))).toBeVisible()
})
