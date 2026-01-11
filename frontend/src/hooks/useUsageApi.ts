/**
 * Hook for usage tracking API operations
 */
import { useCallback } from 'react'
import { apiClient, buildEndpoint } from '@/lib/api'
import type {
  UsageSummaryResponse,
  DailyUsageListResponse,
  SessionUsageListResponse,
  MonthlyUsageListResponse,
  BlockUsageListResponse,
} from '@/types/usage'

export function useUsageApi() {
  const getSummary = useCallback(async (params?: {
    project_path?: string
  }) => {
    return apiClient<UsageSummaryResponse>(buildEndpoint('usage/summary', params))
  }, [])

  const getDaily = useCallback(async (params?: {
    project_path?: string
    start_date?: string
    end_date?: string
  }) => {
    return apiClient<DailyUsageListResponse>(buildEndpoint('usage/daily', params))
  }, [])

  const getSessions = useCallback(async (params?: {
    project_path?: string
    limit?: number
  }) => {
    return apiClient<SessionUsageListResponse>(buildEndpoint('usage/sessions', params))
  }, [])

  const getMonthly = useCallback(async (params?: {
    project_path?: string
    start_month?: string
    end_month?: string
  }) => {
    return apiClient<MonthlyUsageListResponse>(buildEndpoint('usage/monthly', params))
  }, [])

  const getBlocks = useCallback(async (params?: {
    project_path?: string
    recent?: boolean
    active?: boolean
  }) => {
    return apiClient<BlockUsageListResponse>(buildEndpoint('usage/blocks', params))
  }, [])

  const invalidateCache = useCallback(async (params?: {
    cache_type?: string
    project_path?: string
  }) => {
    return apiClient<{ status: string; message: string }>(
      buildEndpoint('usage/cache/invalidate', params),
      { method: 'POST' }
    )
  }, [])

  return {
    getSummary,
    getDaily,
    getSessions,
    getMonthly,
    getBlocks,
    invalidateCache,
  }
}
