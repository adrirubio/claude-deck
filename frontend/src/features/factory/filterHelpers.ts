export const categories = {
  all: "All work",
  queued: "Queued",
  active: "In progress",
  review: "Needs review",
  attention: "Needs attention",
  finished: "Finished",
  unknown: "Unknown",
};
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
