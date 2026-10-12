import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { chmodSync, existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

// Harness safety journeys. They start a second instance, or try to, with
// scripts/e2e-instance.sh. They need no page and no seeded UI state.

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..')
const script = path.join(repoRoot, 'scripts', 'e2e-instance.sh')
const port = Number(process.env.E2E_ISOLATION_PORT || 18766)

function alive(child: ChildProcess): boolean {
  return child.exitCode === null && child.signalCode === null
}

/** The caller environment without any Deck endpoint or credential. */
function baseEnv(extra: Record<string, string>): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {}
  for (const [key, value] of Object.entries(process.env)) {
    if (!key.startsWith('CLAUDE_DECK_')) env[key] = value
  }
  return { ...env, E2E_PORT: String(port), E2E_SKIP_BUILD: '1', ...extra }
}

/** Run the instance script that must refuse; return its exit status and stderr. */
function runRefused(env: NodeJS.ProcessEnv): { status: number | null; stderr: string } {
  const result = spawnSync('bash', [script], { env, encoding: 'utf8', timeout: 30_000 })
  return { status: result.status, stderr: result.stderr }
}

async function waitForHealth(url: string, deadlineMs: number): Promise<void> {
  const until = Date.now() + deadlineMs
  while (Date.now() < until) {
    try {
      const res = await fetch(url)
      if (res.ok) return
    } catch {
      // not up yet
    }
    await new Promise(r => setTimeout(r, 250))
  }
  throw new Error(`instance did not answer ${url}`)
}

async function waitForExit(child: ChildProcess, deadlineMs: number): Promise<void> {
  if (!alive(child)) return
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('instance did not stop')), deadlineMs)
    child.once('exit', () => {
      clearTimeout(timer)
      resolve()
    })
  })
}

test.describe('instance isolation', () => {
  let scratch: string
  test.beforeEach(() => {
    scratch = mkdtempSync(path.join(tmpdir(), 'deck-e2e-isolation-'))
  })
  test.afterEach(() => {
    rmSync(scratch, { recursive: true, force: true })
  })

  // The start-up relay cleanup sends SIGTERM to every process whose command
  // line matches "tmux attach-session". A test instance must not run it.
  test('@active an instance never signals tmux clients outside its own server', async () => {
    test.setTimeout(90_000)
    const decoy = spawn('bash', ['-c', 'exec -a "tmux attach-session -t e2e-decoy" sleep 600'], {
      stdio: 'ignore',
    })
    const root = path.join(scratch, 'root')
    let instance: ChildProcess | undefined
    try {
      expect(alive(decoy)).toBe(true)
      instance = spawn('bash', [script], {
        env: baseEnv({ E2E_ROOT: root }),
        stdio: ['ignore', 'ignore', 'pipe'],
      })
      let stderr = ''
      instance.stderr?.on('data', chunk => {
        stderr += String(chunk)
      })
      await waitForHealth(`http://127.0.0.1:${port}/health`, 60_000).catch(err => {
        throw new Error(`${err.message}\n${stderr}`)
      })
      expect(alive(decoy), 'decoy survives instance start-up').toBe(true)

      instance.kill('SIGTERM')
      await waitForExit(instance, 20_000)
      expect(alive(decoy), 'decoy survives instance shutdown').toBe(true)
      expect(existsSync(root), 'teardown removes the temporary root').toBe(false)
    } finally {
      if (instance && alive(instance)) instance.kill('SIGKILL')
      decoy.kill('SIGKILL')
    }
  })

  // A launcher script in front of tmux can force the shared team socket. The
  // instance must refuse it without running it.
  test('@active an instance refuses a tmux that can use the team socket', () => {
    const marker = path.join(scratch, 'wrapper-ran')
    const wrapper = path.join(scratch, 'tmux')
    writeFileSync(wrapper, `#!/bin/sh\ntouch '${marker}'\nexec tmux -S /tmp/team.sock "$@"\n`)
    chmodSync(wrapper, 0o755)
    const { status, stderr } = runRefused(baseEnv({ E2E_TMUX: wrapper }))
    expect(status).toBe(2)
    expect(stderr).toContain('is not a tmux executable')
    expect(existsSync(marker), 'the wrapper never runs').toBe(false)
  })

  test('@active an instance refuses a Deck endpoint in its environment', () => {
    const { status, stderr } = runRefused(baseEnv({ CLAUDE_DECK_URL: 'http://127.0.0.1:9' }))
    expect(status).toBe(2)
    expect(stderr).toContain('CLAUDE_DECK_URL names another Deck')
  })

  test('@active an instance refuses a Deck Mail credential in its environment', () => {
    const { status, stderr } = runRefused(baseEnv({ CLAUDE_DECK_MAIL_TOKEN: 'synthetic' }))
    expect(status).toBe(2)
    expect(stderr).toContain('a Deck Mail credential must not reach the E2E instance')
  })

  test('@active an instance refuses an Agent Mail MCP configuration in its HOME', () => {
    const root = path.join(scratch, 'root')
    mkdirSync(path.join(root, 'home'), { recursive: true })
    writeFileSync(path.join(root, '.deck-e2e-root'), '')
    writeFileSync(
      path.join(root, 'home', '.claude.json'),
      JSON.stringify({ mcpServers: { 'claude-deck-mail': { command: 'synthetic' } } }),
    )
    const { status, stderr } = runRefused(baseEnv({ E2E_ROOT: root }))
    expect(status).toBe(2)
    expect(stderr).toContain('Agent Mail MCP configuration')
  })

  test('@active an instance never deletes an unmarked E2E_ROOT', () => {
    const root = path.join(scratch, 'not-a-root')
    mkdirSync(root)
    writeFileSync(path.join(root, 'keep.txt'), 'keep')
    const { status, stderr } = runRefused(baseEnv({ E2E_ROOT: root }))
    expect(status).toBe(2)
    expect(stderr).toContain('is not empty')
    expect(existsSync(path.join(root, 'keep.txt'))).toBe(true)
  })
})
