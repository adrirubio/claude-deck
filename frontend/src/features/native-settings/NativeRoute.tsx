import { Link, useNavigate, useParams } from "react-router-dom";
import {
  useProviderContext,
  NativeProviderScope,
} from "@/contexts/ProviderContext";
import { DashboardProvider } from "@/contexts/DashboardContext";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { ConfigViewerPage } from "@/features/config/ConfigViewerPage";
import { MCPServersPage } from "@/features/mcp/MCPServersPage";
import { PluginsPage } from "@/features/plugins/PluginsPage";
import { CommandsPage } from "@/features/commands/CommandsPage";
import { HooksPage } from "@/features/hooks/HooksPage";
import { PermissionsPage } from "@/features/permissions/PermissionsPage";
import { AgentsPage } from "@/features/agents/AgentsPage";
import { SkillsPage } from "@/features/skills/SkillsPage";
import { MemoryPage } from "@/features/memory/MemoryPage";
import { BackupPage } from "@/features/backup/BackupPage";
import { OutputStylesPage } from "@/features/output-styles/OutputStylesPage";
import { StatusLinePage } from "@/features/statusline/StatusLinePage";
import { SessionsPage } from "@/features/sessions/SessionsPage";
import { SessionViewPage } from "@/features/sessions/SessionViewPage";
import { PlansPage } from "@/features/plans/PlansPage";
import { PlanDetailPage } from "@/features/plans/PlanDetailPage";
import { ContextPage } from "@/features/context/ContextPage";
import { UsagePage } from "@/features/usage/UsagePage";
import type { AgentProviderId } from "@/types/providers";
import { nativeAdapter, nativeAccess } from "./surfaceRegistry";
const pages = {
  summary: DashboardPage,
  config: ConfigViewerPage,
  mcp: MCPServersPage,
  plugins: PluginsPage,
  commands: CommandsPage,
  hooks: HooksPage,
  permissions: PermissionsPage,
  agents: AgentsPage,
  skills: SkillsPage,
  memory: MemoryPage,
  backup: BackupPage,
  "output-styles": OutputStylesPage,
  statusline: StatusLinePage,
  sessions: SessionsPage,
  plans: PlansPage,
  context: ContextPage,
  usage: UsagePage,
};
export function NativeRoute({
  surface: legacySurface,
  detail,
}: {
  surface?: string;
  detail?: "session" | "plan";
}) {
  const params = useParams();
  const context = useProviderContext();
  const navigate = useNavigate();
  const provider = params.providerId ?? context.selectedProviderId;
  const surface = legacySurface ?? params.surface ?? "summary";
  const metadata = context.providers.find((p) => p.id === provider);
  const entry = nativeAdapter(provider, surface);
  const access = nativeAccess(provider, surface, metadata);
  const Page = pages[surface as keyof typeof pages];
  if (context.loading) return <p role="status">Loading harness registry…</p>;
  if (!entry || !Page || !access || context.error || !metadata)
    return (
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Native page unavailable</h2>
        <p>
          {provider}/{surface} has no available matching native page adapter.
          CLI or Agent Mail integration capabilities do not enable a settings
          editor.
        </p>
        {context.error && <p role="alert">{context.error}</p>}
        <Link className="text-primary underline" to="/harnesses">
          Open Harnesses
        </Link>
        <p>
          <Link className="text-primary underline" to="/agent-bridge">
            Inspect live sessions
          </Link>
        </p>
      </section>
    );
  // Writable legacy editors do not implement a read-only presentation. Never expose their writes.
  if (access === "read_only" && entry.access === "write_capable")
    return (
      <section>
        <h2 className="text-xl font-semibold">Native settings are read-only</h2>
        <p>
          This legacy editor has no read-only adapter. Writes are unavailable.
        </p>
        <Link className="text-primary underline" to="/harnesses">
          Open Harnesses
        </Link>
      </section>
    );
  return (
    <NativeProviderScope
      providerId={provider as AgentProviderId}
      onSelect={(id) => navigate(`/harnesses/${id}/${surface}`)}
    >
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Native configuration · {metadata.display_name} ·{" "}
          {access.replaceAll("_", " ")} · independent of delivery filters
        </p>
        {surface === "summary" ? (
          <DashboardProvider>
            <DashboardPage />
          </DashboardProvider>
        ) : detail === "session" ? (
          <SessionViewPage />
        ) : detail === "plan" ? (
          <PlanDetailPage />
        ) : (
          <Page />
        )}
      </div>
    </NativeProviderScope>
  );
}
