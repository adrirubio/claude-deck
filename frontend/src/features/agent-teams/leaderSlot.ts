import type { AgentTeamSlot } from '@/types/agentTeams'

export function autonomousLeaderSlotId(slots: Pick<AgentTeamSlot, 'id' | 'enabled' | 'position'>[]): number | null {
  return [...slots].filter((slot) => slot.enabled).sort((first, second) => first.position - second.position)[0]?.id ?? null
}
