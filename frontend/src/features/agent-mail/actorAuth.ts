import { API_BASE_URL } from '@/lib/constants'

const KEY_STORAGE_KEY = 'deck-agent-mail-actor-key'
const TOKEN_STORAGE_KEY = 'deck-agent-mail-actor-token'

/**
 * One external-actor row per browser tab.
 *
 * TWO values, not one, and the split is the whole point. `actor_key` is the
 * tab's durable identity; the token is only a rotating credential for it.
 * `create_actor` SELECTs on actor_key: a hit rotates token_hash on the same
 * row, a miss INSERTs a new row with a new id
 * (external_agent_mail_service.py:88-105). So re-provisioning the SAME key
 * rotates the credential and keeps the identity, and re-provisioning a NEW key
 * abandons it -- along with every thread this tab created, because the
 * ownership guard then sees a different actor and refuses with 400.
 *
 * sessionStorage, not localStorage: both values die with the tab, and per-tab
 * keys mean two tabs cannot rotate each other's credential. The cost is one
 * actor row per tab, which is why the key is random rather than fixed.
 */
function actorKey(): string {
  const existing = sessionStorage.getItem(KEY_STORAGE_KEY)
  if (existing) return existing
  const created = `deck-ui-${crypto.randomUUID().slice(0, 8)}`
  sessionStorage.setItem(KEY_STORAGE_KEY, created)
  return created
}

async function provision(): Promise<string> {
  const response = await fetch(`${API_BASE_URL}external/agent-mail/actors`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      actor_key: actorKey(),
      display_name: 'Deck UI',
      kind: 'supervisor',
      description: 'Claude Deck browser session',
    }),
  })
  if (!response.ok) {
    throw new Error(`Could not provision an Agent Mail credential (HTTP ${response.status})`)
  }
  const token = (await response.json()).token as string
  sessionStorage.setItem(TOKEN_STORAGE_KEY, token)
  return token
}

async function token(): Promise<string> {
  return sessionStorage.getItem(TOKEN_STORAGE_KEY) ?? (await provision())
}

/**
 * Discard the credential, keep the identity. This is the ONLY reset
 * authentication recovery may call.
 */
export function resetActorToken(): void {
  sessionStorage.removeItem(TOKEN_STORAGE_KEY)
}

/**
 * Become a different actor. Nothing in PR0 calls this; it exists so that a
 * later "start a fresh operator identity" affordance has one obvious place to
 * live, and so that nobody reaches for `resetActorToken` and adds the key
 * removal to it. Adding `KEY_STORAGE_KEY` to `resetActorToken` is the exact
 * regression Step 1's recovery test and Step 15's item 7 exist to catch.
 */
export function resetActorIdentity(): void {
  sessionStorage.removeItem(KEY_STORAGE_KEY)
  sessionStorage.removeItem(TOKEN_STORAGE_KEY)
}

/**
 * Fetch through the actor credential, re-provisioning ONCE on 401 and on
 * nothing else.
 *
 * The bound matters: a pruned actor row is a 401 and is worth one retry, but a
 * 403 or a 500 retried in a loop is indistinguishable from a hung UI. This is
 * also why these calls do not go through apiClient -- it throws
 * `new Error(message)` and discards response.status (lib/api.ts:117-122), so
 * 401 could not be told apart from 403.
 */
export async function actorFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const send = async (bearer: string) =>
    fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...init?.headers,
        Authorization: `Bearer ${bearer}`,
      },
    })

  let response = await send(await token())
  if (response.status === 401) {
    // The token is gone; the key is not. provision() re-POSTs the stored key,
    // so this rotates the credential on the tab's existing actor row.
    resetActorToken()
    response = await send(await provision())
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    const message =
      typeof detail?.detail === 'string' ? detail.detail : `HTTP ${response.status}`
    throw new Error(response.status === 429 ? `Sending too fast — ${message}` : message)
  }
  return response.json() as Promise<T>
}
