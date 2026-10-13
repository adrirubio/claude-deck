import { ACTION_TEXT, ATTENTION_TEXT } from "@/features/agent-teams/summaryText";
import type { AgentTeamPreset, AgentTeamSummary } from "@/types/agentTeams";

export interface NeedsYouRow {
  key: string;
  title: string;
  detail: string;
  team: string;
  href: string;
  cta: string;
}

// Each row is one thing that a team summary reports as waiting for the Director.
// The Overview adds no action of its own.
export function needsYouRows(
  presets: AgentTeamPreset[],
  summaries: (AgentTeamSummary | null)[],
): NeedsYouRow[] {
  const rows: NeedsYouRow[] = [];
  presets.forEach((preset, index) => {
    const summary = summaries[index];
    if (!summary) return;
    const fallback = `/work?team_id=${preset.id}`;
    const actions = summary.human_actions.filter(
      (action) => action.state === "requested" || action.state === "context_pending",
    );
    for (const action of actions) {
      rows.push({
        key: `${preset.id}-action-${action.kind}-${action.scope_id}-${action.issue_number}`,
        title: `${ACTION_TEXT[action.kind]}${action.pull_request_number ? ` #${action.pull_request_number}` : ""}`,
        detail: `on #${action.issue_number}${action.state === "context_pending" ? " · details pending" : ""}`,
        team: preset.name,
        href: action.work_item_id ? `/work/${action.work_item_id}` : fallback,
        cta: `Open #${action.issue_number}`,
      });
    }
    for (const item of summary.attention) {
      if (!item.issue_number) continue;
      // An action for the same issue is already a row above: one row for each issue and reason.
      if (actions.some((action) => action.issue_number === item.issue_number)) continue;
      if (!["attempt_stopped", "recovery_decision", "human_review"].includes(item.code)) continue;
      rows.push({
        key: `${preset.id}-attention-${item.code}-${item.work_item_id ?? item.issue_number}`,
        title: ATTENTION_TEXT[item.code],
        detail: `on #${item.issue_number}`,
        team: preset.name,
        href: item.work_item_id ? `/work/${item.work_item_id}` : fallback,
        cta: `Open #${item.issue_number}`,
      });
    }
    for (const item of summary.required_ci_unreadable ?? []) {
      rows.push({
        key: `${preset.id}-ci-${item.work_item_id}`,
        title: item.label,
        detail: `on #${item.issue_number} · check GitHub access`,
        team: preset.name,
        href: `/work/${item.work_item_id}`,
        cta: `Open #${item.issue_number}`,
      });
    }
  });
  return rows;
}
