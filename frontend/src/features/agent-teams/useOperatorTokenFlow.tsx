import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiHttpError } from '@/lib/api'
import { clearOperatorToken, getOperatorToken, setOperatorToken } from './operatorAuth'
import { OperatorTokenDialog } from './OperatorTokenDialog'

/** The Director key state and prompt that the Autonomy tab and the Work item page share. */
export function useOperatorTokenFlow(reason: string) {
  const [operatorTokenStored, setOperatorTokenStored] = useState(() => Boolean(getOperatorToken()))
  const [tokenDialogOpen, setTokenDialogOpen] = useState(false)
  const [tokenInput, setTokenInput] = useState('')
  const [tokenError, setTokenError] = useState<string | null>(null)
  const tokenResolverRef = useRef<((token: string | null) => void) | null>(null)
  const tokenPromiseRef = useRef<Promise<string | null> | null>(null)
  const requestToken = useCallback((message: string | null = null): Promise<string | null> => {
    const stored = getOperatorToken()
    if (stored) return Promise.resolve(stored)
    if (tokenPromiseRef.current) return tokenPromiseRef.current
    const pending = new Promise<string | null>((resolve) => {
      tokenResolverRef.current = resolve
    })
    tokenPromiseRef.current = pending
    setTokenError(message)
    setTokenDialogOpen(true)
    return pending
  }, [])

  useEffect(() => () => {
    tokenResolverRef.current?.(null)
    tokenResolverRef.current = null
    tokenPromiseRef.current = null
  }, [])

  const settleTokenDialog = (token: string | null) => {
    tokenResolverRef.current?.(token)
    tokenResolverRef.current = null
    tokenPromiseRef.current = null
    setTokenDialogOpen(false)
    setTokenInput('')
    setTokenError(null)
  }

  const submitToken = () => {
    const token = tokenInput.trim()
    if (!token) return
    setOperatorToken(token)
    setOperatorTokenStored(true)
    settleTokenDialog(token)
  }

  const clearStoredToken = () => {
    clearOperatorToken()
    setOperatorTokenStored(false)
  }

  const withOperatorToken = useCallback(async <Result,>(
    action: (token: string) => Promise<Result>
  ): Promise<Result> => {
    for (let attempt = 0; attempt < 2; attempt++) {
      const token = await requestToken(attempt > 0 ? 'The Director key was rejected. Enter a valid key to retry.' : null)
      if (!token) throw new Error('The Director key is required for this action.')
      try {
        return await action(token)
      } catch (error) {
        if (!(error instanceof ApiHttpError) || error.status !== 401) throw error
        clearOperatorToken()
        setOperatorTokenStored(false)
        if (attempt === 1) throw error
      }
    }
    throw new Error('The Director key was rejected.')
  }, [requestToken])

  const tokenDialog = (
    <OperatorTokenDialog
      open={tokenDialogOpen}
      value={tokenInput}
      error={tokenError}
      reason={reason}
      onValueChange={setTokenInput}
      onSubmit={submitToken}
      onCancel={() => settleTokenDialog(null)}
    />
  )

  return { operatorTokenStored, requestToken, clearStoredToken, withOperatorToken, tokenDialog }
}
