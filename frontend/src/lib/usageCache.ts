// Cache configuration
const CACHE_KEY_PREFIX = 'usage_cache_'
const CACHE_VERSION = 'v1'
const CACHE_TTL_MS = 2 * 60 * 1000 // 2 minutes

interface CacheEntry<T> {
  data: T
  timestamp: number
  version: string
}

export function getCacheKey(projectPath: string | null): string {
  return `${CACHE_KEY_PREFIX}${projectPath ?? 'all'}`
}

export function getFromCache<T>(projectPath: string | null): T | null {
  const key = getCacheKey(projectPath)
  const raw = localStorage.getItem(key)
  if (!raw) return null

  try {
    const entry: CacheEntry<T> = JSON.parse(raw)
    if (entry.version !== CACHE_VERSION) return null
    return entry.data
  } catch {
    return null
  }
}

export function isCacheStale(projectPath: string | null): boolean {
  const key = getCacheKey(projectPath)
  const raw = localStorage.getItem(key)
  if (!raw) return true

  try {
    const entry = JSON.parse(raw)
    return Date.now() - entry.timestamp > CACHE_TTL_MS
  } catch {
    return true
  }
}

export function saveToCache<T>(projectPath: string | null, data: T): void {
  const key = getCacheKey(projectPath)
  const entry: CacheEntry<T> = {
    data,
    timestamp: Date.now(),
    version: CACHE_VERSION
  }
  try {
    localStorage.setItem(key, JSON.stringify(entry))
  } catch {
    // localStorage might be full - clear old caches and retry
    invalidateCache()
    try {
      localStorage.setItem(key, JSON.stringify(entry))
    } catch {
      // If still fails, ignore silently
    }
  }
}

export function invalidateCache(projectPath?: string | null): void {
  if (projectPath === undefined) {
    // Clear all usage caches
    Object.keys(localStorage)
      .filter(k => k.startsWith(CACHE_KEY_PREFIX))
      .forEach(k => localStorage.removeItem(k))
  } else {
    localStorage.removeItem(getCacheKey(projectPath))
  }
}
