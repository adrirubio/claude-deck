import type { AgentProviderId, AgentProviderStatus } from "@/types/providers";

export type NativeSurface =
  | "summary"
  | "config"
  | "mcp"
  | "plugins"
  | "commands"
  | "hooks"
  | "permissions"
  | "agents"
  | "skills"
  | "memory"
  | "backup"
  | "output-styles"
  | "statusline"
  | "sessions"
  | "plans"
  | "context"
  | "usage";
export interface NativeAdapter {
  component: string;
  access: "read_only" | "write_capable";
  reads: string[];
  writes: string[];
}
const adapter = (
  component: string,
  roots: string[],
  writable = true,
): NativeAdapter => ({
  component,
  access: writable ? "write_capable" : "read_only",
  reads: roots,
  writes: writable ? roots : [],
});
const claude: Record<NativeSurface, NativeAdapter> = {
  summary: adapter("DashboardPage", [
    "config",
    "mcp",
    "commands",
    "agents",
    "skills",
    "hooks",
    "plugins",
    "permissions",
    "output-styles",
    "sessions",
    "context",
    "plans",
  ], false),
  config: adapter("ConfigViewerPage", ["config", "projects"]),
  mcp: adapter("MCPServersPage", ["mcp"]),
  plugins: adapter("PluginsPage", ["plugins"]),
  commands: adapter("CommandsPage", ["commands"]),
  hooks: adapter("HooksPage", ["hooks"]),
  permissions: adapter("PermissionsPage", ["permissions"]),
  agents: adapter("AgentsPage", ["agents"]),
  skills: adapter("SkillsPage", ["agents/skills"]),
  memory: adapter("MemoryPage", ["memory"]),
  backup: adapter("BackupPage", ["backup"]),
  "output-styles": adapter("OutputStylesPage", ["output-styles"]),
  statusline: adapter("StatusLinePage", ["statusline"]),
  sessions: adapter("SessionsPage", ["sessions"], false),
  plans: adapter("PlansPage", ["plans"], false),
  context: adapter("ContextPage", ["context"], false),
  usage: adapter("UsagePage", ["usage"], false),
};
export const surfaceRegistry: Record<
  AgentProviderId,
  Partial<Record<NativeSurface, NativeAdapter>>
> = {
  "claude-code": claude,
  "codex-cli": {
    summary: adapter("DashboardPage", [
      "codex-config",
      "providers/codex-cli",
      "agent-bridge/sessions",
      "plans",
    ], false),
    config: { ...adapter("ConfigViewerPage", [
      "codex-config",
      "providers/codex-cli/doctor",
      "providers/codex-cli/features",
      "providers/codex-cli/mcp",
      "providers/codex-cli/plugins",
    ]), writes: ["codex-config", "providers/codex-cli/mcp", "providers/codex-cli/plugins"] },
    mcp: adapter("MCPServersPage", ["providers/codex-cli/mcp"]),
    plugins: adapter("PluginsPage", ["providers/codex-cli/plugins"]),
    plans: adapter("PlansPage", ["plans"], false),
  },
  "copilot-cli": {},
  "opencode-cli": {},
  "pi-cli": {},
};
export function nativeAdapter(
  provider: string,
  surface: string,
): NativeAdapter | undefined {
  return surfaceRegistry[provider as AgentProviderId]?.[
    surface as NativeSurface
  ];
}
export function nativeAccess(
  provider: string,
  surface: string,
  metadata?: AgentProviderStatus | null,
) {
  const entry = nativeAdapter(provider, surface);
  if (!entry) return null;
  const capability = surface === "output-styles" ? "output_styles" : surface;
  const state =
    metadata?.capability_matrix?.[
      capability as keyof AgentProviderStatus["capability_matrix"]
    ]?.state;
  if (state === "unsupported" || state === "unknown") return null;
  return state === "read_only" || entry.access === "read_only"
    ? "read_only"
    : "write_capable";
}
// Applied at the API boundary in addition to mount guards. General factory/team reads are unaffected.
export function assertNativeAction(
  provider: string,
  surface: string,
  endpoint: string,
  method = "GET",
  access = nativeAdapter(provider, surface)?.access,
) {
  const entry = nativeAdapter(provider, surface);
  const path = endpoint.replace(/^\/?api\/v1\//, "").split("?")[0];
  const read = method.toUpperCase() === "GET";
  if (!read && provider === "codex-cli") {
    const allowed =
      (path === "codex-config" && method === "PATCH") ||
      (path === "providers/codex-cli/mcp" && method === "POST") ||
      (path.startsWith("providers/codex-cli/mcp/") && method === "DELETE") ||
      (path === "providers/codex-cli/plugins" && method === "POST") ||
      (path.startsWith("providers/codex-cli/plugins/") && method === "DELETE");
    if (!allowed)
      throw new Error(
        `Native ${provider}/${surface} does not permit ${method} ${path}.`,
      );
  }
  const roots = read ? entry?.reads : entry?.writes;
  if (
    !entry ||
    !roots?.some((root) => path === root || path.startsWith(`${root}/`)) ||
    (!read && access !== "write_capable")
  )
    throw new Error(
      `Native ${provider}/${surface} does not permit ${method} ${path}.`,
    );
}

let providerMetadata: AgentProviderStatus[] = [];
export function updateNativeMetadata(providers: AgentProviderStatus[]) {
  providerMetadata = providers;
}
export function assertBrowserNativeRequest(endpoint: string, method = "GET") {
  if (typeof window === "undefined") return;
  const route = window.location.pathname.split("/").filter(Boolean);
  const canonical = route[0] === "harnesses" && route.length >= 3;
  const surface = canonical ? route[2] : route[0];
  if (!surface || !Object.keys(claude).includes(surface)) return;
  const provider = canonical
    ? route[1]
    : (window.localStorage.getItem("claude-deck:selected-provider") ??
      "claude-code");
  const path = endpoint.replace(/^\/?api\/v1\//, "").split("?")[0];
  const nativeRoots = [
    "codex-config",
    "config",
    "mcp",
    "plugins",
    "commands",
    "hooks",
    "permissions",
    "agents",
    "skills",
    "memory",
    "backup",
    "output-styles",
    "statusline",
    "sessions",
    "plans",
    "context",
    "usage",
    "providers/codex-cli",
  ];
  if (!nativeRoots.some((root) => path === root || path.startsWith(`${root}/`)))
    return;
  const access = nativeAccess(
    provider,
    surface,
    providerMetadata.find((p) => p.id === provider),
  );
  if (!access) throw new Error(`Native ${provider}/${surface} unavailable.`);
  const nestedSurface =
    provider === "codex-cli" && path.startsWith("providers/codex-cli/")
      ? path.split("/")[2]
      : null;
  if (nestedSurface === "mcp" || nestedSurface === "plugins") {
    const nestedAccess = nativeAccess(
      provider,
      nestedSurface,
      providerMetadata.find((p) => p.id === provider),
    );
    if (!nestedAccess)
      throw new Error(`Native ${provider}/${nestedSurface} unavailable.`);
    assertNativeAction(provider, nestedSurface, endpoint, method, nestedAccess);
  }
  assertNativeAction(provider, surface, endpoint, method, access);
}
