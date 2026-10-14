import { toast } from 'sonner'

import type {
  TeamGithubContinuationPolicyUpdate,
  TeamGithubScope,
  TeamGithubScopeUpdate,
} from '@/types/agentTeams'
import {
  deleteTeamGithubScope,
  updateTeamGithubContinuationPolicy,
  updateTeamGithubScope,
} from './api'
import { useOperatorTokenFlow } from './useOperatorTokenFlow'

/**
 * The settings handlers of one watched repository. Every request, Director key
 * prompt and message is the one the Autonomy tab used before they moved here (#536).
 */
export function useScopeSettings({ refresh }: { refresh: () => Promise<void> }) {
  const { withOperatorToken, tokenDialog } = useOperatorTokenFlow('to change autonomy or recovery settings')

  const saveScope = (scopeId: number, input: TeamGithubScopeUpdate) =>
    withOperatorToken(async (operatorToken) => {
      try {
        await updateTeamGithubScope(scopeId, input, operatorToken)
        await refresh()
        toast.success('Watched repo saved')
      } catch (error) {
        toast.error(error instanceof Error ? error.message : 'Failed to save watched repo')
        throw error
      }
    })

  const savePolicy = (scopeId: number, input: TeamGithubContinuationPolicyUpdate) =>
    withOperatorToken(async (operatorToken) => {
      try {
        await updateTeamGithubContinuationPolicy(scopeId, input, operatorToken)
        await refresh()
        toast.success('Attempt recovery policy saved')
      } catch (error) {
        toast.error(error instanceof Error ? error.message : 'Failed to save recovery policy')
        throw error
      }
    })

  const removeScope = (scope: TeamGithubScope) =>
    withOperatorToken(async (operatorToken) => {
      try {
        await deleteTeamGithubScope(scope.id, operatorToken)
        await refresh()
        toast.success('Watched repo removed')
      } catch (error) {
        toast.error(error instanceof Error ? error.message : 'Failed to remove watched repo')
        throw error
      }
    })

  return { saveScope, savePolicy, removeScope, tokenDialog }
}
