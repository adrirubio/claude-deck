/** Convert browser-owned names once, retaining every value until its copy exists. */
export const PRODUCT_STORAGE_KEYS = {
  provider: 'albiex-synth-city:selected-provider',
  operator: 'albiex-synth-city.agent-teams.operator-token',
  actorKey: 'albiex-synth-city-agent-mail-actor-key',
  actorToken: 'albiex-synth-city-agent-mail-actor-token',
} as const

const LEGACY_STORAGE_KEYS = {
  provider: 'claude-deck:selected-provider',
  operator: 'claude-deck.agent-teams.operator-token',
  actorKey: 'deck-agent-mail-actor-key',
  actorToken: 'deck-agent-mail-actor-token',
} as const

type StorageKey = keyof typeof PRODUCT_STORAGE_KEYS
type MigrationResult = Record<StorageKey, 'complete' | 'pending'>

const completed = new WeakMap<Storage, Set<string>>()

function completedKeys(storage: Storage): Set<string> {
  let done = completed.get(storage)
  if (!done) { done = new Set(); completed.set(storage, done) }
  return done
}

function convert(storage: Storage, names: readonly StorageKey[], result: MigrationResult) {
  const done = completedKeys(storage)
  for (const name of names) {
    const oldKey = LEGACY_STORAGE_KEYS[name]
    const newKey = PRODUCT_STORAGE_KEYS[name]
    if (done.has(newKey)) { result[name] = 'complete'; continue }
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
      result[name] = 'complete'
    } catch {
      // Keep the old value and retry this unfinished conversion on a later access.
    }
  }
}

export function migrateBrowserStorage(): MigrationResult {
  const result: MigrationResult = { provider: 'pending', operator: 'pending', actorKey: 'pending', actorToken: 'pending' }
  if (typeof window === 'undefined') return result
  try {
    convert(window.localStorage, ['provider'], result)
  } catch { /* Storage can be unavailable for this origin. */ }
  try {
    convert(window.sessionStorage, ['operator', 'actorKey', 'actorToken'], result)
  } catch { /* Storage can be unavailable for this tab. */ }
  return result
}

/** Explicit resets cancel conversion too, so a retained credential cannot return. */
export function clearSessionStorageValue(name: Exclude<StorageKey, 'provider'>): void {
  if (typeof window === 'undefined') return
  const storage = window.sessionStorage
  storage.removeItem(LEGACY_STORAGE_KEYS[name])
  storage.removeItem(PRODUCT_STORAGE_KEYS[name])
  completedKeys(storage).add(PRODUCT_STORAGE_KEYS[name])
}
