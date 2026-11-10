/** Convert browser-owned names once, retaining every value until its copy exists. */
export const PRODUCT_STORAGE_KEYS = {
  provider: 'albiex-synth-city:selected-provider',
  operator: 'albiex-synth-city.agent-teams.operator-token',
  actorKey: 'albiex-synth-city-agent-mail-actor-key',
  actorToken: 'albiex-synth-city-agent-mail-actor-token',
} as const

const completed = new WeakMap<Storage, Set<string>>()

function convert(storage: Storage, pairs: ReadonlyArray<readonly [string, string]>) {
  let done = completed.get(storage)
  if (!done) { done = new Set(); completed.set(storage, done) }
  for (const [oldKey, newKey] of pairs) {
    if (done.has(newKey)) continue
    try {
      if (storage.getItem(newKey) === null) {
        const previous = storage.getItem(oldKey)
        if (previous !== null) {
          storage.setItem(newKey, previous)
          // Never delete the source of a refused or silently failed write.
          if (storage.getItem(newKey) !== previous) continue
        }
      }
      storage.removeItem(oldKey)
      done.add(newKey)
    } catch {
      // Keep the old value and retry this unfinished conversion on a later access.
    }
  }
}

export function migrateBrowserStorage(): void {
  if (typeof window === 'undefined') return
  try {
    convert(window.localStorage, [['claude-deck:selected-provider', PRODUCT_STORAGE_KEYS.provider]])
  } catch { /* Storage can be unavailable for this origin. */ }
  try {
    convert(window.sessionStorage, [
      ['claude-deck.agent-teams.operator-token', PRODUCT_STORAGE_KEYS.operator],
      ['deck-agent-mail-actor-key', PRODUCT_STORAGE_KEYS.actorKey],
      ['deck-agent-mail-actor-token', PRODUCT_STORAGE_KEYS.actorToken],
    ])
  } catch { /* Storage can be unavailable for this tab. */ }
}
