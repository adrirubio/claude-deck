/**
 * Hook for plan history browser API operations
 */
import { useCallback } from 'react'
import { apiClient, buildEndpoint } from '@/lib/api'
import { useProjectContext } from '@/contexts/ProjectContext'
import { useProviderContext } from '@/contexts/ProviderContext'
import type {
  PlanListResponse,
  PlanDetailResponse,
  PlanSearchResponse,
  PlanStatsResponse,
} from '@/types/plans'

export function usePlansApi() {
  const { activeProject } = useProjectContext()
  const { selectedProviderId } = useProviderContext()

  const listPlans = useCallback(async () => {
    return apiClient<PlanListResponse>(
      buildEndpoint('plans', {
        project_path: activeProject?.path,
        provider: selectedProviderId,
      })
    )
  }, [activeProject?.path, selectedProviderId])

  const getPlan = useCallback(async (filename: string) => {
    return apiClient<PlanDetailResponse>(
      buildEndpoint(`plans/${encodeURIComponent(filename)}`, {
        project_path: activeProject?.path,
        provider: selectedProviderId,
      })
    )
  }, [activeProject?.path, selectedProviderId])

  const searchPlans = useCallback(async (query: string) => {
    return apiClient<PlanSearchResponse>(
      buildEndpoint('plans/search', {
        q: query,
        project_path: activeProject?.path,
        provider: selectedProviderId,
      })
    )
  }, [activeProject?.path, selectedProviderId])

  const getStats = useCallback(async () => {
    return apiClient<PlanStatsResponse>(
      buildEndpoint('plans/stats', {
        project_path: activeProject?.path,
        provider: selectedProviderId,
      })
    )
  }, [activeProject?.path, selectedProviderId])

  return {
    listPlans,
    getPlan,
    searchPlans,
    getStats,
  }
}
