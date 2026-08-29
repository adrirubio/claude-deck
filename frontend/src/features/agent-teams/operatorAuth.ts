const OPERATOR_TOKEN_KEY = 'claude-deck.agent-teams.operator-token'

function storage(): Storage | null {
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
    storage()?.removeItem(OPERATOR_TOKEN_KEY)
  } catch {
    return
  }
}
