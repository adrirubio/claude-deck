import { apiClient } from '@/lib/api'
import type {
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
} from '@/types/agentTeams'

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
  input: AgentTeamPresetUpdate
): Promise<AgentTeamPreset> {
  return apiClient<AgentTeamPreset>(`agent-teams/presets/${presetId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export function deleteAgentTeamPreset(presetId: number): Promise<Record<string, never>> {
  return apiClient<Record<string, never>>(`agent-teams/presets/${presetId}`, {
    method: 'DELETE',
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
  input: AgentTeamSlotInput
): Promise<AgentTeamPreset> {
  return apiClient<AgentTeamPreset>(`agent-teams/presets/${presetId}/slots`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function updateAgentTeamSlot(
  slotId: number,
  input: AgentTeamSlotUpdate
): Promise<AgentTeamPreset> {
  return apiClient<AgentTeamPreset>(`agent-teams/slots/${slotId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export function deleteAgentTeamSlot(slotId: number): Promise<AgentTeamPreset> {
  return apiClient<AgentTeamPreset>(`agent-teams/slots/${slotId}`, {
    method: 'DELETE',
  })
}

export function reorderAgentTeamSlots(
  presetId: number,
  slotIds: number[]
): Promise<AgentTeamPreset> {
  return apiClient<AgentTeamPreset>(`agent-teams/presets/${presetId}/slots/reorder`, {
    method: 'POST',
    body: JSON.stringify({ slot_ids: slotIds }),
  })
}

export function planAgentTeamLaunch(
  presetId: number,
  input: AgentTeamLaunchRequest = {}
): Promise<AgentTeamLaunchPlan> {
  return apiClient<AgentTeamLaunchPlan>(`agent-teams/presets/${presetId}/plan-launch`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function launchAgentTeam(
  presetId: number,
  input: AgentTeamLaunchRequest
): Promise<AgentTeamLaunchResult> {
  return apiClient<AgentTeamLaunchResult>(`agent-teams/presets/${presetId}/launch`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}
