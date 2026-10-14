import { ACTION_TEXT, ATTENTION_TEXT } from "@/features/agent-teams/summaryText";
import { parseReminders, reminderAge, reminderSentence } from "@/features/agent-teams/reminderText";
import { waitingText } from "@/features/agent-teams/supervisorText";
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
    // A member waits at an interactive screen. Only the fixed reason is shown.
    const names = Object.fromEntries(preset.slots.map((slot) => [slot.id, slot.display_name]));
    for (const entry of summary.waiting_input ?? []) {
      rows.push({
        key: `${preset.id}-waiting-${entry.slot_id}`,
        title: "Waiting for input",
        detail: waitingText(entry, names),
        team: preset.name,
        href: "/agent-bridge",
        cta: "Open live sessions",
      });
    }
    const overdue = summary.supervisor_observation?.attention;
    if (overdue) {
      rows.push({
        key: `${preset.id}-supervisor`,
        title: overdue,
        detail: `supervisor is ${summary.supervisor_observation!.status}`,
        team: preset.name,
        href: `/teams/${preset.id}`,
        cta: "Open the team",
      });
    }
    // One row for each unanswered-reminder signal. The wire is parsed defensively.
    for (const row of parseReminders(summary.reminder_attention)) {
      rows.push({
        key: `${preset.id}-reminder-${row.kind}-${row.workItemId ?? row.issueNumbers.join("-")}`,
        title: reminderSentence(row),
        detail: `reminder ${Math.min(row.count, row.cap)} of ${row.cap}${row.elapsedSeconds !== null ? ` · waiting ${reminderAge(row.elapsedSeconds)}` : ""}`,
        team: preset.name,
        href: row.kind === "workspace_release" && row.workItemId ? `/work/${row.workItemId}` : `/teams/${preset.id}`,
        cta: row.kind === "workspace_release" && row.issueNumber ? `Open #${row.issueNumber}` : "Open the team",
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
