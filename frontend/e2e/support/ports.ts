import net from 'node:net'

// Each run chooses its own free ports, so parallel runs on one host do not
// collide. E2E_PORT and E2E_ISOLATION_PORT override the choice.

/** A port that is free now on 127.0.0.1 (the kernel chooses it). */
export function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.unref()
    server.on('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : 0
      server.close(() => (port ? resolve(port) : reject(new Error('no free port'))))
    })
  })
}

function parsePort(name: string, value: string): number {
  const port = Number(value)
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error(`${name} is not a port: ${value}`)
  return port
}

/** The instance port and the isolation-probe port: overrides, or two free ports. */
export async function resolvePorts(env: NodeJS.ProcessEnv): Promise<{ port: number; isolationPort: number }> {
  const port = env.E2E_PORT ? parsePort('E2E_PORT', env.E2E_PORT) : await freePort()
  let isolationPort = env.E2E_ISOLATION_PORT
    ? parsePort('E2E_ISOLATION_PORT', env.E2E_ISOLATION_PORT)
    : await freePort()
  while (!env.E2E_ISOLATION_PORT && isolationPort === port) isolationPort = await freePort()
  return { port, isolationPort }
}
