export const categories = {
  all: "All work",
  queued: "Queued",
  active: "In progress",
  review: "Needs review",
  attention: "Needs attention",
  finished: "Finished",
  unknown: "Unknown",
};
// The plain word for the state of one work item. Merged work reads "Merged".
export function stateLabel(work: {
  category: keyof typeof categories;
  item: { dispatch_status: string };
}) {
  return work.item.dispatch_status === "merged"
    ? "Merged"
    : categories[work.category];
}
export const harnesses = {
  "claude-code": "Claude Code",
  "codex-cli": "Codex CLI",
  "copilot-cli": "Copilot CLI",
  "opencode-cli": "OpenCode",
  "pi-cli": "Pi",
};
export function factoryQuery(params: URLSearchParams, category = false) {
  const result = new URLSearchParams();
  for (const key of [
    "team_id",
    "scope_id",
    "provider",
    ...(category ? ["category"] : []),
  ]) {
    const value = params.get(key);
    if (value) result.set(key, value);
  }
  return result.toString();
}
export function workLink(params: URLSearchParams, category: string) {
  const next = new URLSearchParams(factoryQuery(params));
  next.set("category", category);
  return `/work?${next}`;
}

// The plain state of a watched repository: On, Off or Needs attention. The
// reason is the one line that Deck gives for the intake state.
export function repositoryState(r: {
  configured_enabled: boolean;
  team_automation_enabled: boolean;
  intake: { state: string; summary: string };
}): { label: "On" | "Off" | "Needs attention"; reason: string } {
  if (!r.configured_enabled || !r.team_automation_enabled)
    return { label: "Off", reason: r.intake.summary };
  if (r.intake.state === "eligible") return { label: "On", reason: r.intake.summary };
  return { label: "Needs attention", reason: r.intake.summary };
}
