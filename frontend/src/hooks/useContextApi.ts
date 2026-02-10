/**
 * Hook for context window analysis API operations
 */
import { useCallback } from 'react'
import { apiClient } from '@/lib/api'
import type { ActiveSessionsResponse, ContextAnalysisResponse } from '@/types/context'

export function useContextApi() {
  const getActiveSessions = useCallback(async () => {
    return apiClient<ActiveSessionsResponse>('context/active')
  }, [])

  const getSessionContext = useCallback(async (
    projectFolder: string,
    sessionId: string
  ) => {
    return apiClient<ContextAnalysisResponse>(
      `context/${projectFolder}/${sessionId}`
    )
  }, [])

  return {
    getActiveSessions,
    getSessionContext,
  }
}
