/**
 * Hook for session transcript API operations
 */
import { useCallback } from 'react'
import { apiClient, buildEndpoint } from '@/lib/api'
import type {
  SessionListResponse,
  SessionProjectListResponse,
  SessionDetailResponse,
  SessionStatsResponse,
} from '@/types/sessions'

export function useSessionsApi() {
  const listProjects = useCallback(async () => {
    return apiClient<SessionProjectListResponse>('sessions/projects')
  }, [])

  const listSessions = useCallback(async (params?: {
    project_folder?: string
    limit?: number
    sort_by?: string
    sort_order?: string
  }) => {
    return apiClient<SessionListResponse>(buildEndpoint('sessions', params))
  }, [])

  const getSessionDetail = useCallback(async (
    projectFolder: string,
    sessionId: string,
    page: number = 1
  ) => {
    return apiClient<SessionDetailResponse>(
      `sessions/${projectFolder}/${sessionId}?page=${page}`
    )
  }, [])

  const getDashboardStats = useCallback(async () => {
    return apiClient<SessionStatsResponse>('sessions/dashboard/stats')
  }, [])

  return {
    listProjects,
    listSessions,
    getSessionDetail,
    getDashboardStats,
  }
}
