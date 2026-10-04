import { apiClient } from '@/lib/api'
import type {
  AgentTeamActivityResponse,
  AgentTeamCreateFromBridgeRequest,
  AgentTeamCreateFromMailRequest,
  AgentTeamLaunchPlan,
  AgentTeamLaunchRequest,
  AgentTeamLaunchResult,
  AgentTeamPreset,
  AgentTeamPresetInput,
  AgentTeamPresetListResponse,
  AgentTeamPresetUpdate,
  AgentTeamSlotInput,
  AgentTeamSlotUpdate,
  GithubWorkItem,
  GithubWorkItemListResponse,
  GithubApprovalRequest,
  GithubScopeRevision,
  GithubRecoveryGate,
  GithubWorkspace,
  TeamGithubContinuationPolicyUpdate,
  TeamGithubScope,
  TeamGithubScopeInput,
  TeamGithubScopeListResponse,
  TeamGithubScopeUpdate,
} from '@/types/agentTeams'

export function fetchAgentTeamActivity(presetId: number, signal: AbortSignal): Promise<AgentTeamActivityResponse> {
  return apiClient<AgentTeamActivityResponse>(`agent-teams/presets/${presetId}/activity`, {
    signal,
    cache: 'no-store',
  })
}

export function fetchAgentTeamPresets(): Promise<AgentTeamPresetListResponse> {
  return apiClient<AgentTeamPresetListResponse>('agent-teams/presets')
}

export function createAgentTeamPreset(input: AgentTeamPresetInput): Promise<AgentTeamPreset> {
  return apiClient<AgentTeamPreset>('agent-teams/presets', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function createAgentTeamFromMail(input: AgentTeamCreateFromMailRequest): Promise<AgentTeamPreset> {
  return apiClient<AgentTeamPreset>('agent-teams/presets/from-agent-mail', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function createAgentTeamFromBridge(input: AgentTeamCreateFromBridgeRequest): Promise<AgentTeamPreset> {
  return apiClient<AgentTeamPreset>('agent-teams/presets/from-agent-bridge', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function updateAgentTeamPreset(
  presetId: number,
  input: AgentTeamPresetUpdate,
  operatorToken: string
): Promise<AgentTeamPreset> {
  return apiClient<AgentTeamPreset>(`agent-teams/presets/${presetId}`, {
    method: 'PATCH',
    headers: operatorHeaders(operatorToken),
    body: JSON.stringify(input),
  })
}

export function deleteAgentTeamPreset(presetId: number, operatorToken: string): Promise<Record<string, never>> {
  return apiClient<Record<string, never>>(`agent-teams/presets/${presetId}`, {
    method: 'DELETE',
    headers: operatorHeaders(operatorToken),
  })
}

export function duplicateAgentTeamPreset(
  presetId: number,
  input: AgentTeamPresetUpdate
): Promise<AgentTeamPreset> {
  return apiClient<AgentTeamPreset>(`agent-teams/presets/${presetId}/duplicate`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function addAgentTeamSlot(
  presetId: number,
  input: AgentTeamSlotInput,
  operatorToken: string
): Promise<AgentTeamPreset> {
  return apiClient<AgentTeamPreset>(`agent-teams/presets/${presetId}/slots`, {
    method: 'POST',
    headers: operatorHeaders(operatorToken),
    body: JSON.stringify(input),
  })
}

export function updateAgentTeamSlot(
  slotId: number,
  input: AgentTeamSlotUpdate,
  operatorToken: string
): Promise<AgentTeamPreset> {
  return apiClient<AgentTeamPreset>(`agent-teams/slots/${slotId}`, {
    method: 'PATCH',
    headers: operatorHeaders(operatorToken),
    body: JSON.stringify(input),
  })
}

export function deleteAgentTeamSlot(slotId: number, operatorToken: string): Promise<AgentTeamPreset> {
  return apiClient<AgentTeamPreset>(`agent-teams/slots/${slotId}`, {
    method: 'DELETE',
    headers: operatorHeaders(operatorToken),
  })
}

export function reorderAgentTeamSlots(
  presetId: number,
  slotIds: number[],
  operatorToken: string
): Promise<AgentTeamPreset> {
  return apiClient<AgentTeamPreset>(`agent-teams/presets/${presetId}/slots/reorder`, {
    method: 'POST',
    headers: operatorHeaders(operatorToken),
    body: JSON.stringify({ slot_ids: slotIds }),
  })
}

export function planAgentTeamLaunch(
  presetId: number,
  input: AgentTeamLaunchRequest = {},
  operatorToken: string
): Promise<AgentTeamLaunchPlan> {
  return apiClient<AgentTeamLaunchPlan>(`agent-teams/presets/${presetId}/plan-launch`, {
    method: 'POST',
    headers: operatorHeaders(operatorToken),
    body: JSON.stringify(input),
  })
}

export function launchAgentTeam(
  presetId: number,
  input: AgentTeamLaunchRequest,
  operatorToken: string
): Promise<AgentTeamLaunchResult> {
  return apiClient<AgentTeamLaunchResult>(`agent-teams/presets/${presetId}/launch`, {
    method: 'POST',
    headers: operatorHeaders(operatorToken),
    body: JSON.stringify(input),
  })
}

export function fetchTeamGithubScopes(presetId: number): Promise<TeamGithubScopeListResponse> {
  return apiClient<TeamGithubScopeListResponse>(`agent-teams/presets/${presetId}/github-scopes`)
}

export function createTeamGithubScope(
  presetId: number,
  input: TeamGithubScopeInput,
  operatorToken: string
): Promise<TeamGithubScope> {
  return apiClient<TeamGithubScope>(`agent-teams/presets/${presetId}/github-scopes`, {
    method: 'POST',
    headers: operatorHeaders(operatorToken),
    body: JSON.stringify(input),
  })
}

export function updateTeamGithubScope(
  scopeId: number,
  input: TeamGithubScopeUpdate,
  operatorToken: string
): Promise<TeamGithubScope> {
  return apiClient<TeamGithubScope>(`agent-teams/github-scopes/${scopeId}`, {
    method: 'PATCH',
    headers: operatorHeaders(operatorToken),
    body: JSON.stringify(input),
  })
}

export function deleteTeamGithubScope(scopeId: number, operatorToken: string): Promise<Record<string, never>> {
  return apiClient<Record<string, never>>(`agent-teams/github-scopes/${scopeId}`, {
    method: 'DELETE',
    headers: operatorHeaders(operatorToken),
  })
}

function operatorHeaders(operatorToken: string): HeadersInit {
  return { 'X-Deck-Operator-Token': operatorToken }
}

export function updateTeamGithubContinuationPolicy(
  scopeId: number,
  input: TeamGithubContinuationPolicyUpdate,
  operatorToken: string
): Promise<TeamGithubScope> {
  return apiClient<TeamGithubScope>(`agent-teams/github-scopes/${scopeId}/continuation-policy`, {
    method: 'PATCH',
    headers: operatorHeaders(operatorToken),
    body: JSON.stringify(input),
  })
}

export function fetchGithubScopeRevisions(
  workItemId: number,
  operatorToken: string
): Promise<GithubScopeRevision[]> {
  return apiClient<GithubScopeRevision[]>(
    `agent-teams/github-work-items/${workItemId}/scope-revisions`,
    { headers: operatorHeaders(operatorToken) }
  )
}

export function cancelGithubContinuationRequest(
  workItemId: number,
  requestId: number,
  operatorToken: string
): Promise<GithubApprovalRequest> {
  return apiClient<GithubApprovalRequest>(
    `agent-teams/github-work-items/${workItemId}/continuation-requests/${requestId}/cancel`,
    { method: 'POST', headers: operatorHeaders(operatorToken) }
  )
}

export function fetchGithubWorkItems(presetId: number, limit = 50): Promise<GithubWorkItemListResponse> {
  return apiClient<GithubWorkItemListResponse>(
    `agent-teams/presets/${presetId}/github-work-items?limit=${limit}`
  )
}

export function retryGithubWorkItem(workItemId: number, operatorToken: string): Promise<GithubWorkItem> {
  return apiClient<GithubWorkItem>(`agent-teams/github-work-items/${workItemId}/retry`, {
    method: 'POST',
    headers: operatorHeaders(operatorToken),
  })
}

export function fetchGithubRecoveryGate(operatorToken: string): Promise<GithubRecoveryGate> {
  return apiClient<GithubRecoveryGate>('agent-teams/github-recovery-gate', {
    headers: operatorHeaders(operatorToken),
  })
}

export function fetchGithubRecoveryGateActive(): Promise<{ active: boolean }> {
  return apiClient<{ active: boolean }>('agent-teams/github-recovery-gate/active')
}

export function fetchGithubWorkspaces(scopeId: number, operatorToken: string): Promise<{ workspaces: GithubWorkspace[] }> {
  return apiClient<{ workspaces: GithubWorkspace[] }>(`agent-teams/github-scopes/${scopeId}/workspaces`, {
    headers: operatorHeaders(operatorToken),
  })
}

export function abandonGithubWorkItem(workItemId: number, reason: string, operatorToken: string): Promise<GithubWorkItem> {
  return apiClient<GithubWorkItem>(`agent-teams/github-work-items/${workItemId}/abandon`, {
    method: 'POST', headers: operatorHeaders(operatorToken), body: JSON.stringify({ reason }),
  })
}

export function resumeGithubWorkItem(presetId: number, workItemId: number, operatorToken: string, reassignToSlotId?: number): Promise<GithubWorkItem> {
  return apiClient<GithubWorkItem>(`agent-teams/presets/${presetId}/work-items/${workItemId}/resume-attempt`, {
    method: 'POST', headers: operatorHeaders(operatorToken),
    body: JSON.stringify({ resume: true, reassign_to_slot_id: reassignToSlotId ?? null }),
  })
}

export function releaseGithubRecoveryCheckpoint(
  workItemId: number,
  revision: GithubScopeRevision,
  stage: 'decision' | 'ack',
  operatorToken: string
): Promise<GithubScopeRevision> {
  return apiClient<GithubScopeRevision>(
    `agent-teams/github-work-items/${workItemId}/scope-revisions/${revision.revision}/checkpoint-release`,
    {
      method: 'POST', headers: operatorHeaders(operatorToken),
      body: JSON.stringify({ release: true, dispatch_nonce: revision.dispatch_nonce, approval_request_id: revision.approval_request_id, stage }),
    }
  )
}

export function cancelGithubActiveRevision(
  workItemId: number,
  revision: GithubScopeRevision,
  reason: string,
  operatorToken: string
): Promise<GithubWorkItem> {
  return apiClient<GithubWorkItem>(
    `agent-teams/github-work-items/${workItemId}/scope-revisions/${revision.revision}/cancel`,
    {
      method: 'POST', headers: operatorHeaders(operatorToken),
      body: JSON.stringify({ cancel: true, dispatch_nonce: revision.dispatch_nonce, reason }),
    }
  )
}

export function forceReleaseGithubWorkspace(
  scopeId: number,
  workspace: GithubWorkspace,
  reason: string,
  operatorToken: string
): Promise<{ released_item_id: number; discarded_paths?: string | null; unpushed_commits?: number | null }> {
  return apiClient(`agent-teams/github-scopes/${scopeId}/workspaces/${workspace.id}/force-release`, {
    method: 'POST', headers: operatorHeaders(operatorToken),
    body: JSON.stringify({ force: true, expected_leased_at: workspace.leased_at, reason, requested_by: 'Deck UI operator' }),
  })
}
