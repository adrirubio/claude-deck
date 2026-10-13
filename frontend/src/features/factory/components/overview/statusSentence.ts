import type { OverviewResponse } from "@/types/factory";

// One sentence that answers "Is anyone watching?". The detail is behind a disclosure.
export function statusSentence(data: OverviewResponse, teams: number | null) {
  const { automation, counts } = data;
  const open = counts.active + counts.review + counts.attention + counts.queued;
  const repos = (n: number) => `${n} ${n === 1 ? "repository" : "repositories"}`;
  if (automation.configured_scopes === 0)
    return { tone: "off", text: "No repositories are set up yet." };
  // With every repository off, nothing is taking in work, so "paused" comes first.
  // The scheduler and recovery-only details stay in the automation details.
  if (automation.enabled_scopes > 0 && automation.runtime.mode === "recovery_only")
    return { tone: "warn", text: "Recovery-only mode. Deck blocks normal intake." };
  if (automation.enabled_scopes > 0 && automation.runtime.scheduler_state === "stopped")
    return { tone: "warn", text: "The scheduler is stopped. Deck blocks normal intake." };
  if (automation.enabled_scopes === 0) {
    const all = automation.configured_scopes === 1 ? "The" : "All";
    return {
      tone: "off",
      text: open === 0
        ? `Factory idle and paused. ${all} ${repos(automation.configured_scopes)} ${automation.configured_scopes === 1 ? "is" : "are"} off. Nothing is queued.`
        : `Factory paused. ${all} ${repos(automation.configured_scopes)} ${automation.configured_scopes === 1 ? "is" : "are"} off. ${open} ${open === 1 ? "item is" : "items are"} still open.`,
    };
  }
  return {
    tone: "on",
    text: `Factory running. ${teams === null ? "" : `${teams} ${teams === 1 ? "team" : "teams"} · `}${automation.enabled_scopes} of ${repos(automation.configured_scopes)} on.`,
  };
}
