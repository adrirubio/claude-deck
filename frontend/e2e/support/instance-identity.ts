// A run must test its own instance. Another agent's instance, or any other
// server, can answer on the chosen port; a run against it would test foreign
// data and source. The instance reports its run token on /health (only when
// TEST_INSTANCE is set). The messages never print the token or the root.

export class ForeignInstanceError extends Error {}

/** Refuse unless the server at baseURL is the test instance of this run. */
export async function verifyInstance(baseURL: string, token: string | undefined): Promise<void> {
  if (!token) throw new ForeignInstanceError('E2E refused: E2E_RUN_TOKEN is not set; run the journeys through playwright.config.ts')
  let body: unknown
  try {
    const response = await fetch(`${baseURL}/health`)
    body = await response.json()
  } catch {
    throw new ForeignInstanceError(`E2E refused: no Deck test instance answers ${baseURL}/health`)
  }
  const reported = (body as { test_instance?: { token?: unknown } } | null)?.test_instance
  if (!reported || typeof reported !== 'object') {
    throw new ForeignInstanceError(
      `E2E refused: the server on ${baseURL} is not a Deck test instance. Another server uses this port; stop it or choose another E2E_PORT.`,
    )
  }
  if (reported.token !== token) {
    throw new ForeignInstanceError(
      `E2E refused: the test instance on ${baseURL} belongs to another run (its run token does not match). Stop it or choose another E2E_PORT.`,
    )
  }
}
