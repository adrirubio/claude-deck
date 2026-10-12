import { spawn, type ChildProcess } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { expect, test } from '@playwright/test'

// The start-up relay cleanup sends SIGTERM to every process whose command line
// matches "tmux attach-session". A test instance must not run it. This journey
// starts a decoy that matches that pattern, then starts and stops a second
// isolated instance, and checks that the decoy survives both.

const repoRoot = path.resolve(__dirname, '..', '..', '..')
const port = Number(process.env.E2E_ISOLATION_PORT || 18766)

function alive(child: ChildProcess): boolean {
  return child.exitCode === null && child.signalCode === null
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

test('@active an instance never signals tmux clients outside its own server', async () => {
  test.setTimeout(90_000)
  const decoy = spawn('bash', ['-c', 'exec -a "tmux attach-session -t e2e-decoy" sleep 600'], {
    stdio: 'ignore',
  })
  const root = mkdtempSync(path.join(tmpdir(), 'deck-e2e-isolation-'))
  let instance: ChildProcess | undefined
  try {
    expect(alive(decoy)).toBe(true)
    instance = spawn('bash', [path.join(repoRoot, 'scripts', 'e2e-instance.sh')], {
      env: { ...process.env, E2E_PORT: String(port), E2E_ROOT: root, E2E_SKIP_BUILD: '1' },
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
    expect(existsSync(root), 'instance removes its temporary root').toBe(false)
  } finally {
    if (instance && alive(instance)) instance.kill('SIGKILL')
    decoy.kill('SIGKILL')
    rmSync(root, { recursive: true, force: true })
  }
})
