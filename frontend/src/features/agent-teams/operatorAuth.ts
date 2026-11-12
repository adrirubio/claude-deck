import { clearSessionStorageValue, migrateBrowserStorage, PRODUCT_STORAGE_KEYS } from '@/lib/browserStorageMigration'

const OPERATOR_TOKEN_KEY = PRODUCT_STORAGE_KEYS.operator

function storage(): Storage | null {
  migrateBrowserStorage()
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage
  } catch {
    return null
  }
}

export function getOperatorToken(): string | null {
  try {
    return storage()?.getItem(OPERATOR_TOKEN_KEY)?.trim() || null
  } catch {
    return null
  }
}

export function setOperatorToken(token: string): void {
  const normalized = token.trim()
  if (!normalized) {
    clearOperatorToken()
    return
  }
  try {
    storage()?.setItem(OPERATOR_TOKEN_KEY, normalized)
  } catch {
    return
  }
}

export function clearOperatorToken(): void {
  try {
    clearSessionStorageValue('operator')
  } catch {
    return
  }
}
