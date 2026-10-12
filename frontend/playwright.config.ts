import path from 'path'
import { defineConfig, devices } from '@playwright/test'
import { E2E_LOCALE, E2E_TIMEZONE } from './e2e/support/time'

// One isolated Deck instance serves the built UI and the API on one origin.
// scripts/e2e-instance.sh owns its temporary HOME, database and tmux server.
const port = Number(process.env.E2E_PORT || 18765)
const baseURL = `http://127.0.0.1:${port}`
const repoRoot = path.resolve(__dirname, '..')

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI
    ? [['list'], ['html', { open: 'never' }], ['json', { outputFile: 'test-results/results.json' }]]
    : [['list']],
  use: {
    baseURL,
    locale: E2E_LOCALE,
    timezoneId: E2E_TIMEZONE,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    serviceWorkers: 'block',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `bash ${path.join(repoRoot, 'scripts', 'e2e-instance.sh')}`,
    url: `${baseURL}/health`,
    reuseExistingServer: !!process.env.E2E_REUSE_INSTANCE,
    timeout: 240_000,
    stdout: 'pipe',
    stderr: 'pipe',
    gracefulShutdown: { signal: 'SIGTERM', timeout: 10_000 },
    env: { E2E_PORT: String(port) },
  },
})
