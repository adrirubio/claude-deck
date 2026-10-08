import type { AgentTeamSlot } from '@/types/agentTeams'

export function autonomousLeaderSlotId(
  leaderSlotId: number | null,
  slots: Pick<AgentTeamSlot, 'id' | 'enabled'>[]
): number | null {
  return slots.some((slot) => slot.id === leaderSlotId && slot.enabled) ? leaderSlotId : null
}
