import { SessionCard } from '../src/features/sessions/SessionCard'
import type { SessionSummary } from '../src/types/sessions'
import { CodexInventoryCard } from '../src/features/config/CodexInventoryCard'
import { useEffect } from "react";
import { cleanup, screen, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ProviderProvider,
  useProviderContext,
} from "../src/contexts/ProviderContext";
import { NativeRoute } from "../src/features/native-settings/NativeRoute";
import {
  surfaceRegistry,
  nativeAccess,
  assertNativeAction,
  assertBrowserNativeRequest,
  updateNativeMetadata,
} from "../src/features/native-settings/surfaceRegistry";
import { apiClient } from "../src/lib/api";
import { BridgeEntry, MailEntry } from "../src/features/factory/ContextPages";
import { verifiedBridgeSession } from "../src/features/factory/contextLinks";
import type { AgentProviderStatus } from "../src/types/providers";
import type { CCSession } from "../src/features/cc-bridge/types";
import adapters from "./fixtures/factory/native-adapters.json";
import { resetFactoryReads } from "../src/features/factory/reads";
import {
  fixtureFetch,
  jsonResponse,
  renderRoute,
  settle,
} from "./helpers/factory";
vi.mock("../src/features/config/ConfigViewerPage", () => ({
  ConfigViewerPage: function Config() {
    const { selectedProviderId } = useProviderContext();
    useEffect(() => {
      void apiClient(
        selectedProviderId === "codex-cli" ? "codex-config" : "config",
      ).catch(() => undefined);
    }, [selectedProviderId]);
    return <p>Mounted {selectedProviderId} editor</p>;
  },
}));
vi.mock("../src/features/cc-bridge/TerminalView", () => ({
  TerminalView: ({
    forceReadOnly,
    target,
  }: {
    forceReadOnly: boolean;
    target: string;
  }) => (
    <p>
      Terminal {target}{" "}
      {forceReadOnly ? "locked readonly" : "interactive available"}
    </p>
  ),
}));
vi.mock("../src/features/cc-bridge/CCBridgePage", () => ({
  CCBridgePage: () => <p>Manual Bridge</p>,
}));
vi.mock("../src/features/agent-mail/AgentMailPage", () => ({
  AgentMailPage: () => <p>Coordination</p>,
}));
const statuses = [
  "claude-code",
  "codex-cli",
  "copilot-cli",
  "opencode-cli",
  "pi-cli",
].map((id) => ({
  id,
  display_name: id,
  installed: true,
  capabilities: { config: true, plugins: true, usage: true },
  capability_matrix: {
    config: { state: "write_capable" },
    plugins: { state: "write_capable" },
    usage: { state: "supported" },
  },
})) as AgentProviderStatus[];
beforeEach(() => {
  resetFactoryReads();
  updateNativeMetadata([]);
  localStorage.clear();
  window.history.replaceState({}, "", "/");
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
describe("native adapters", () => {
 it('shares a canonical Claude transcript link independently of a Codex saved preference', () => {
  localStorage.setItem('claude-deck:selected-provider','codex-cli')
  const open=vi.spyOn(window,'open').mockImplementation(()=>null)
  const session={id:'session/id',project_folder:'project folder',project_name:'Fixture',modified_at:'2026-09-30T12:00:00Z',size_bytes:1,summary:'Transcript fixture',total_messages:1,total_tool_calls:0} as SessionSummary
  renderRoute(<SessionCard session={session}/>,'/harnesses/claude-code/sessions','/harnesses/claude-code/sessions')
  fireEvent.click(screen.getByRole('link'),{ctrlKey:true})
  expect(open).toHaveBeenCalledWith('/harnesses/claude-code/sessions/project%20folder/session%2Fid','_blank','noopener,noreferrer')
  open.mockRestore()
 })

 it('guards nested inventory writes independently of the parent config page', async () => {
  localStorage.setItem('claude-deck:selected-provider', 'codex-cli')
  const readOnly = statuses.map(p => p.id === 'codex-cli' ? { ...p, capability_matrix: { config: { state: 'write_capable' }, mcp: { state: 'read_only' }, plugins: { state: 'read_only' } } } : p)
  const { requests } = fixtureFetch(() => jsonResponse({providers:readOnly}))
  renderRoute(<ProviderProvider><CodexInventoryCard mcp={null} plugins={null} mcpError={null} pluginError={null} loading={false} onRefresh={() => undefined} /></ProviderProvider>); await settle()
  expect(screen.getByRole('button', {name:'Add Server'})).toBeDisabled()
  expect(screen.getByRole('button', {name:'Install Plugin'})).toBeDisabled()
  window.history.replaceState({}, '', '/harnesses/codex-cli/config')
  await expect(apiClient('providers/codex-cli/mcp', {method:'POST'})).rejects.toThrow(/does not permit/)
  expect(requests).toHaveLength(1)
 })

  it("freezes implemented M1a component/API/read-write mappings", () => {
    expect(surfaceRegistry).toEqual(adapters.registry);
  });
  it.each(["copilot-cli", "opencode-cli", "pi-cli"])(
    "blocks Claude fallthrough for %s with positive capabilities",
    async (id) => {
      const { requests } = fixtureFetch(() =>
        jsonResponse({ providers: statuses }),
      );
      renderRoute(
        <ProviderProvider>
          <NativeRoute />
        </ProviderProvider>,
        `/harnesses/${id}/config`,
        "/harnesses/:providerId/:surface",
      );
      await settle();
      expect(screen.getByText("Native page unavailable")).toBeInTheDocument();
      expect(screen.queryByText(/Mounted/)).not.toBeInTheDocument();
      expect(requests.every((r) => r.path === "providers")).toBe(true);
    },
  );
  it("prepares canonical Codex context before first editor request without changing saved preference", async () => {
    localStorage.setItem("claude-deck:selected-provider", "pi-cli");
    const { requests } = fixtureFetch((path) =>
      path === "providers"
        ? jsonResponse({ providers: statuses })
        : jsonResponse({}),
    );
    renderRoute(
      <ProviderProvider>
        <NativeRoute />
      </ProviderProvider>,
      "/harnesses/codex-cli/config",
      "/harnesses/:providerId/:surface",
    );
    await settle();
    expect(screen.getByText("Mounted codex-cli editor")).toBeInTheDocument();
    expect(requests.some((r) => r.path === "codex-config")).toBe(true);
    expect(requests.some((r) => r.path === "config")).toBe(false);
    expect(localStorage.getItem("claude-deck:selected-provider")).toBe(
      "pi-cli",
    );
  });
  it("guards compatibility entries and prevents writable editor mounting for read-only access", async () => {
    localStorage.setItem("claude-deck:selected-provider", "opencode-cli");
    const { requests } = fixtureFetch(() =>
      jsonResponse({ providers: statuses }),
    );
    renderRoute(
      <ProviderProvider>
        <NativeRoute surface="plugins" />
      </ProviderProvider>,
      "/plugins",
      "/plugins",
    );
    await settle();
    expect(requests).toHaveLength(1);
    cleanup();
    localStorage.setItem("claude-deck:selected-provider", "codex-cli");
    fixtureFetch(() =>
      jsonResponse({
        providers: statuses.map((p) =>
          p.id === "codex-cli"
            ? { ...p, capability_matrix: { config: { state: "read_only" } } }
            : p,
        ),
      }),
    );
    renderRoute(
      <ProviderProvider>
        <NativeRoute surface="config" />
      </ProviderProvider>,
      "/config",
      "/config",
    );
    await settle();
    expect(
      screen.getByText("Native settings are read-only"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Mounted/)).not.toBeInTheDocument();
  });
  it("denies read-only writes and mismatched native API paths before fetch", async () => {
    expect(nativeAccess("codex-cli", "plans")).toBe("read_only");
    expect(() =>
      assertNativeAction("codex-cli", "plans", "plans", "POST"),
    ).toThrow(/does not permit/);
    expect(() => assertNativeAction("codex-cli", "config", "config")).toThrow(
      /does not permit/,
    );
    window.history.replaceState({}, "", "/harnesses/codex-cli/plans");
    expect(() => assertBrowserNativeRequest("plans", "POST")).toThrow(
      /does not permit/,
    );
    const { requests } = fixtureFetch(() => jsonResponse({}));
    await expect(apiClient("plans", { method: "POST" })).rejects.toThrow(
      /does not permit/,
    );
    expect(requests).toHaveLength(0);
  });
});
const session = {
  tmux_target: "fixture:0.0",
  team_preset_id: 1,
  team_slot_id: 2,
  mail_member_id: 3,
  mail_mcp_session_id: 4,
  provider: "codex-cli",
  team_slot_name: "Owner",
} as CCSession;
const query = "context=readonly&team_id=1&slot_id=2&member_id=3&session_id=4";
describe("context navigation", () => {
  it("requires one exact team/slot/member/MCP-session association", () => {
    const q = new URLSearchParams(query);
    expect(verifiedBridgeSession([session], q)).toBe(session);
    expect(
      verifiedBridgeSession([{ ...session, mail_mcp_session_id: 7 }], q),
    ).toBeNull();
    expect(
      verifiedBridgeSession(
        [session, { ...session, tmux_target: "other:0.0" }],
        q,
      ),
    ).toBeNull();
    expect(
      verifiedBridgeSession(
        [session],
        new URLSearchParams("team_id=1&slot_id=2"),
      ),
    ).toBeNull();
  });
  it("opens only verified read-only terminals using GET", async () => {
    const { requests } = fixtureFetch(() =>
      jsonResponse({ sessions: [session] }),
    );
    renderRoute(<BridgeEntry />, `/agent-bridge?${query}`, "/agent-bridge");
    await settle();
    expect(screen.getByText(/locked readonly/)).toBeInTheDocument();
    expect(requests).toHaveLength(1);
    expect(requests[0].method).toBe("GET");
  });
  it("keeps ambiguous/offline context filtered without selecting a terminal", async () => {
    fixtureFetch(() =>
      jsonResponse({
        sessions: [
          session,
          { ...session, tmux_target: "ambiguous:0.0" },
          { ...session, tmux_target: "wrong:0.0", team_preset_id: 9 },
        ],
      }),
    );
    renderRoute(<BridgeEntry />, `/agent-bridge?${query}`, "/agent-bridge");
    await settle();
    expect(screen.queryByText(/Terminal/)).not.toBeInTheDocument();
    expect(screen.getByText(/No unique current/)).toBeInTheDocument();
    expect(screen.getAllByText(/Owner · codex-cli/)).toHaveLength(2);
  });
  it("reads Mail context without sync, inbox claims, acknowledgments or decisions", async () => {
    const { requests } = fixtureFetch((path) =>
      path === "agent-mail/team"
        ? jsonResponse({
            members: [
              {
                id: 3,
                team_preset_id: 1,
                team_slot_id: 2,
                display_name: "Owner",
                status: "offline",
                pending_count: 1,
              },
            ],
          })
        : jsonResponse([
            {
              id: 8,
              sender_member_id: 3,
              subject: "Waiting decision",
              kind: "context_request",
              request_status: "pending",
            },
          ]),
    );
    renderRoute(
      <MailEntry />,
      "/agent-mail?team_id=1&slot_id=2&member_id=3",
      "/agent-mail",
    );
    await settle();
    expect(
      screen.getByRole("button", { name: /Waiting decision/ }),
    ).toBeInTheDocument();
    expect(
      requests.every(
        (r) => r.method === "GET" && !/inbox|ack|approval/.test(r.path),
      ),
    ).toBe(true);
    expect(
      requests.find((r) => r.path === "agent-mail/team")?.query.get("sync"),
    ).toBe("false");
  });
});
