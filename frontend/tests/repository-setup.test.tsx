import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiClient: vi.fn(),
  fetchAgentTeamPresets: vi.fn(),
  fetchTeamGithubScopes: vi.fn(),
  fetchConfigurationObservation: vi.fn(),
  createAgentTeamPreset: vi.fn(),
  createTeamGithubScope: vi.fn(),
  launchAgentTeam: vi.fn(),
  planAgentTeamLaunch: vi.fn(),
  updateAgentTeamLeader: vi.fn(),
  updateAgentTeamPreset: vi.fn(),
  updateTeamGithubScope: vi.fn(),
  getOperatorToken: vi.fn(() => "synthetic-operator"),
  setOperatorToken: vi.fn(),
  clearOperatorToken: vi.fn(),
  ApiHttpError: class ApiHttpError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
}));

vi.mock("@/lib/api", () => ({ apiClient: mocks.apiClient, ApiHttpError: mocks.ApiHttpError }));
vi.mock("@/features/agent-teams/operatorAuth", () => ({
  getOperatorToken: mocks.getOperatorToken,
  setOperatorToken: mocks.setOperatorToken,
  clearOperatorToken: mocks.clearOperatorToken,
}));
vi.mock("@/features/agent-teams/api", () => ({
  createAgentTeamPreset: mocks.createAgentTeamPreset,
  createTeamGithubScope: mocks.createTeamGithubScope,
  fetchAgentTeamPresets: mocks.fetchAgentTeamPresets,
  fetchTeamGithubScopes: mocks.fetchTeamGithubScopes,
  fetchConfigurationObservation: mocks.fetchConfigurationObservation,
  launchAgentTeam: mocks.launchAgentTeam,
  planAgentTeamLaunch: mocks.planAgentTeamLaunch,
  updateAgentTeamLeader: mocks.updateAgentTeamLeader,
  updateAgentTeamPreset: mocks.updateAgentTeamPreset,
  updateTeamGithubScope: mocks.updateTeamGithubScope,
}));

import { RepositorySetupPage } from "../src/features/factory/RepositorySetupPage";

describe("guided repository setup", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getOperatorToken.mockReturnValue("synthetic-operator");
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [] });
    // Compatibility shim: the page reads one bounded observation. Tests keep
    // configuring the underlying preset and scope data sources.
    mocks.fetchConfigurationObservation.mockImplementation(async () => {
      const { presets } = await mocks.fetchAgentTeamPresets();
      const scopeLists = await Promise.all(
        presets.map((preset: { id: number }) => mocks.fetchTeamGithubScopes(preset.id)),
      );
      return {
        observed_at: "2026-10-05T00:00:00Z",
        complete: true,
        presets,
        scopes: scopeLists.flatMap((list: { scopes: never[] }) => list.scopes),
      };
    });
  });

  it("asks for an operator token before preflight when no token is stored", async () => {
    mocks.getOperatorToken.mockReturnValue(null);
    mocks.apiClient.mockResolvedValue({
      status: "ready", observed_at: "2026-10-05T00:00:00Z", checks: {},
    });
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);

    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));

    const dialog = await screen.findByRole("dialog");
    const tokenInput = within(dialog).getByPlaceholderText("Enter secret value");
    expect(mocks.apiClient).not.toHaveBeenCalled();
    fireEvent.change(tokenInput, { target: { value: "fixture-token" } });
    fireEvent.click(screen.getByRole("button", { name: "Use token" }));

    await waitFor(() => expect(mocks.apiClient).toHaveBeenCalledTimes(1));
    expect(mocks.setOperatorToken).toHaveBeenCalledWith("fixture-token");
  });

  it("discards a preflight response when the checked draft changes", async () => {
    let resolveCheck: ((value: unknown) => void) | undefined;
    mocks.apiClient.mockImplementation(() => new Promise((resolve) => { resolveCheck = resolve; }));
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);

    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.change(screen.getByLabelText("Dispatch label"), { target: { value: "dispatch-ready" } });
    fireEvent.change(screen.getByLabelText("Design label"), { target: { value: "design" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/changed-checkout" } });

    await waitFor(() => expect(mocks.apiClient).toHaveBeenCalledTimes(1));
    resolveCheck?.({
      status: "ready", checked_at: "2026-10-05T00:00:00Z",
      checks: { checkout_identity: { status: "ready", code: "checkout_identity_matches" } },
    });

    // A configuration-only save stays available while checks have gaps.
    await waitFor(() => expect(screen.getByRole("button", { name: "Continue to configuration" })).toBeEnabled());
    // The response for the changed draft is discarded: no result panel appears.
    expect(screen.queryByText(/Current result:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Stale result/)).not.toBeInTheDocument();
  });

  it("keeps Save blocked after an uncertain create until fresh records can be selected", async () => {
    mocks.apiClient.mockResolvedValue({
      status: "ready", checked_at: "2026-10-05T00:00:00Z",
      checks: { checkout_identity: { status: "ready", code: "checkout_identity_matches" } },
    });
    mocks.createAgentTeamPreset.mockRejectedValue(new Error("create response lost"));
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);

    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Synthetic team" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));

    await screen.findByText(/Fresh reads found 0 matching record/);
    expect(screen.getByText(/Keep this setup blocked/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save configuration" })).toBeDisabled();
    expect(mocks.createAgentTeamPreset).toHaveBeenCalledTimes(1);
  });

  it("saves separate worker routes and leaves the Leader without worker labels", async () => {
    mocks.apiClient.mockResolvedValue({
      status: "ready", observed_at: "2026-10-05T00:00:00Z", checked_at: "2026-10-05T00:00:00Z",
      checks: { checkout_identity: { status: "ready", code: "checkout_identity_matches", remedy: "ready" } },
    });
    const team = {
      id: 12, name: "Synthetic team", autonomy_enabled: false, leader_slot_id: 101, updated_at: "2026-10-05T00:00:00Z",
      slots: [
        { id: 101, display_name: "Leader", enabled: true, provider: "codex-cli" },
        { id: 102, display_name: "Worker A", enabled: true, provider: "codex-cli" },
        { id: 103, display_name: "Worker B", enabled: true, provider: "codex-cli" },
      ],
    };
    mocks.createAgentTeamPreset.mockResolvedValue(team);
    mocks.createTeamGithubScope.mockResolvedValue({
      id: 55, preset_id: 12, repo_owner: "example", repo_name: "synthetic-product", repo_path: "/synthetic/checkout",
      dispatch_label: "claude-deck-ready", design_label: "claude-deck-design", base_ref: "origin/HEAD",
      github_auth_mode: "ambient", enabled: false,
    });
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);

    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Synthetic team" } });
    fireEvent.change(screen.getByLabelText("Worker slots, one name per line"), { target: { value: "Worker A\nWorker B" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    const workerA = screen.getByRole("group", { name: "Worker A" });
    const workerB = screen.getByRole("group", { name: "Worker B" });
    fireEvent.change(within(workerA).getByLabelText("Area labels, comma separated"), { target: { value: "backend" } });
    fireEvent.change(within(workerA).getByLabelText("Expertise"), { target: { value: "API" } });
    fireEvent.change(within(workerB).getByLabelText("Area labels, comma separated"), { target: { value: "frontend" } });
    fireEvent.change(within(workerB).getByLabelText("Expertise"), { target: { value: "UI" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));

    await screen.findByText(/Team Synthetic team/);
    const slots = mocks.createAgentTeamPreset.mock.calls[0][0].slots;
    expect(slots[0]).toMatchObject({ role: "Leader", area_labels: [], expertise: null });
    expect(slots[1]).toMatchObject({ role: "Worker", area_labels: ["backend"], expertise: "API" });
    expect(slots[2]).toMatchObject({ role: "Worker", area_labels: ["frontend"], expertise: "UI" });
  });

  it("allows safe correction after a definite rejected create without latching", async () => {
    mocks.apiClient.mockResolvedValue({
      status: "ready", observed_at: "2026-10-05T00:00:00Z", checked_at: "2026-10-05T00:00:00Z",
      checks: { checkout_identity: { status: "ready", code: "checkout_identity_matches", remedy: "ready" } },
    });
    mocks.createAgentTeamPreset.mockRejectedValue(new mocks.ApiHttpError("invalid team request", 422));
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);

    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Synthetic team" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));

    await screen.findByText(/invalid team request/);
    // A definite non-write needs no latch and allows safe correction or retry.
    expect(screen.queryByText(/Fresh reads found/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save configuration" })).toBeEnabled();
    expect(mocks.createAgentTeamPreset).toHaveBeenCalledTimes(1);
  });

  it("keeps activation blocked while shared readiness has gaps", async () => {
    const preflight = {
      status: "ready", observed_at: "2026-10-05T00:00:00Z", checked_at: "2026-10-05T00:00:00Z",
      checks: { checkout_identity: { status: "ready", code: "checkout_identity_matches", remedy: "ready" } },
    };
    mocks.apiClient.mockImplementation((endpoint: string) => {
      if (endpoint.startsWith("factory/setup-preflight")) return Promise.resolve(preflight);
      if (endpoint.includes("activation-readiness")) {
        return Promise.resolve({
          status: "blocked", observed_at: "2026-10-05T00:00:00Z",
          blockers: [
            { code: "leader_binding_unauthenticated", message: "The current authenticated Leader binding is not confirmed." },
            { code: "owner_binding_missing", message: "A distinct eligible owner binding is required." },
          ],
        });
      }
      return Promise.resolve({ members: [] });
    });
    const team = {
      id: 12, name: "Synthetic team", autonomy_enabled: false, leader_slot_id: 101, updated_at: "2026-10-05T00:00:00Z",
      slots: [
        { id: 101, display_name: "Leader", enabled: true, provider: "codex-cli", role: "Leader", repo_path: "/synthetic/checkout", area_labels: [], expertise: null },
        { id: 102, display_name: "Worker A", enabled: true, provider: "codex-cli", role: "Worker", repo_path: "/synthetic/checkout", area_labels: [], expertise: null },
      ],
    };
    const scope = {
      id: 55, preset_id: 12, repo_owner: "example", repo_name: "synthetic-product", repo_path: "/synthetic/checkout",
      dispatch_label: "claude-deck-ready", design_label: "claude-deck-design", base_ref: "origin/HEAD",
      github_auth_mode: "ambient", github_auth_configured: true, github_poll_token_configured: true, enabled: false,
    };
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [team] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [scope] });
    mocks.createAgentTeamPreset.mockResolvedValue(team);
    mocks.planAgentTeamLaunch.mockResolvedValue({
      can_launch: false, spawn_count: 0, reuse_count: 0, blocked_count: 1, plan_hash: "synthetic-plan",
      items: [{ slot_id: 102, slot_name: "Worker A", action: "blocked", block_code: "provider_unavailable", reasons: [], matching_session: null }],
    });
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);

    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));

    await screen.findByText(/Saved configuration/);
    fireEvent.click(screen.getByRole("button", { name: "Review current activation and overlap" }));

    await screen.findByText(/The current authenticated Leader binding is not confirmed/);
    expect(screen.getByText(/A distinct eligible owner binding is required/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/Enable team automation/));
    expect(screen.getByRole("button", { name: "Enable team automation" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Enable this scope" })).toBeDisabled();
  });

  const connectedRoster = {
    members: [
      { id: 1, status: "connected", team_preset_id: 12, team_slot_id: 101, sessions: [{ team_preset_id: 12, team_slot_id: 101, mailbox_status: "connected" }] },
      { id: 2, status: "connected", team_preset_id: 12, team_slot_id: 102, sessions: [{ team_preset_id: 12, team_slot_id: 102, mailbox_status: "connected" }] },
    ],
  };
  const readyPlan = {
    can_launch: true, spawn_count: 0, reuse_count: 2, blocked_count: 0, plan_hash: "synthetic-plan",
    items: [
      { slot_id: 101, slot_name: "Leader", action: "reuse", block_code: null, reasons: [], matching_session: { id: 1 } },
      { slot_id: 102, slot_name: "Worker A", action: "reuse", block_code: null, reasons: [], matching_session: { id: 2 } },
    ],
  };

  function teamFixture(autonomy: boolean) {
    return {
      id: 12, name: "Synthetic team", autonomy_enabled: autonomy, leader_slot_id: 101, updated_at: "2026-10-05T00:00:00Z",
      slots: [
        { id: 101, display_name: "Leader", enabled: true, provider: "codex-cli", role: "Leader", repo_path: "/synthetic/checkout", area_labels: [], expertise: null },
        { id: 102, display_name: "Worker A", enabled: true, provider: "codex-cli", role: "Worker", repo_path: "/synthetic/checkout", area_labels: [], expertise: null },
      ],
    };
  }

  function scopeFixture(id: number, presetId: number, enabled: boolean, repo: string, label: string) {
    return {
      id, preset_id: presetId, repo_owner: "example", repo_name: repo, repo_path: "/synthetic/checkout",
      dispatch_label: label, design_label: "claude-deck-design", base_ref: "origin/HEAD",
      github_auth_mode: "ambient", github_auth_configured: true, github_poll_token_configured: true, enabled,
    };
  }

  async function runDraftToSavedSetup() {
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await screen.findByText(/Saved configuration/);
  }

  it("shows an external collision for a scope resumed by team activation and requires acknowledgement", async () => {
    const team = teamFixture(false);
    const externalTeam = { id: 20, name: "External team", autonomy_enabled: true, leader_slot_id: 201, updated_at: "2026-10-05T00:00:00Z", slots: [] };
    const ownScope = scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready");
    const sibling = scopeFixture(56, 12, true, "other-repo", "shared-label");
    const external = scopeFixture(77, 20, true, "other-repo", "shared-label");
    const allScopes = [ownScope, sibling, external];
    mocks.apiClient.mockImplementation((endpoint: string) => {
      if (endpoint.startsWith("factory/setup-preflight")) return Promise.resolve({
        status: "ready", observed_at: "2026-10-05T00:00:00Z", checked_at: "2026-10-05T00:00:00Z",
        checks: { checkout_identity: { status: "ready", code: "checkout_identity_matches", remedy: "ready" } },
      });
      if (endpoint.includes("activation-readiness")) {
        return Promise.resolve({ status: "ready", observed_at: "2026-10-05T00:00:00Z", blockers: [] });
      }
      return Promise.resolve(connectedRoster);
    });
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [team, externalTeam] });
    mocks.fetchTeamGithubScopes.mockImplementation((teamId: number) => Promise.resolve({ scopes: allScopes.filter((item) => item.preset_id === teamId) }));
    mocks.createAgentTeamPreset.mockResolvedValue(team);
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    await runDraftToSavedSetup();

    fireEvent.click(screen.getByRole("button", { name: "Review current activation and overlap" }));
    await screen.findByText(/Team activation overlaps/);
    expect(screen.getByText(/Prospective overlap/)).toBeInTheDocument();
    expect(screen.getByText(/This can dispatch the same issue more than once/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/Enable team automation/));
    expect(screen.getByRole("button", { name: "Enable team automation" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Prospective overlap/ }));
    expect(screen.getByRole("button", { name: "Enable team automation" })).toBeEnabled();
    expect(mocks.updateAgentTeamPreset).not.toHaveBeenCalled();
  });

  it("invalidates acknowledgements when a collision appears after the activation review", async () => {
    const team = teamFixture(true);
    const ownScope = scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready");
    const externalTeam = { id: 20, name: "External team", autonomy_enabled: true, leader_slot_id: 201, updated_at: "2026-10-05T00:00:00Z", slots: [] };
    let scopes = [ownScope];
    mocks.apiClient.mockImplementation((endpoint: string) => {
      if (endpoint.startsWith("factory/setup-preflight")) return Promise.resolve({
        status: "ready", observed_at: "2026-10-05T00:00:00Z", checked_at: "2026-10-05T00:00:00Z",
        checks: { checkout_identity: { status: "ready", code: "checkout_identity_matches", remedy: "ready" } },
      });
      if (endpoint.includes("activation-readiness")) {
        return Promise.resolve({ status: "ready", observed_at: "2026-10-05T00:00:00Z", blockers: [] });
      }
      return Promise.resolve(connectedRoster);
    });
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [team, externalTeam] });
    mocks.fetchTeamGithubScopes.mockImplementation((teamId: number) => Promise.resolve({ scopes: scopes.filter((item) => item.preset_id === teamId) }));
    mocks.createAgentTeamPreset.mockResolvedValue(team);
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    await runDraftToSavedSetup();

    fireEvent.click(screen.getByRole("button", { name: "Review current activation and overlap" }));
    await screen.findByRole("button", { name: "Enable this scope" });
    expect(screen.getByRole("button", { name: "Enable this scope" })).toBeEnabled();

    // A conflicting external scope appears between review and activation.
    scopes = [ownScope, scopeFixture(77, 20, true, "synthetic-product", "claude-deck-ready")];
    fireEvent.click(screen.getByRole("button", { name: "Enable this scope" }));

    await screen.findByText(/changed after the checks/);
    expect(screen.getByText(/Prospective overlap/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enable this scope" })).toBeDisabled();
    expect(mocks.updateTeamGithubScope).not.toHaveBeenCalled();
  });

  async function runDraftToSavedSetupWithExistingTeam(teamId: number) {
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team setup"), { target: { value: "existing" } });
    fireEvent.change(screen.getByLabelText("Team"), { target: { value: String(teamId) } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await screen.findByText(/Saved configuration/);
  }

  function mockReadyPreflightAndRoster() {
    mocks.apiClient.mockImplementation((endpoint: string) => {
      if (endpoint.startsWith("factory/setup-preflight")) return Promise.resolve({
        status: "ready", observed_at: "2026-10-05T00:00:00Z", checked_at: "2026-10-05T00:00:00Z",
        checks: { checkout_identity: { status: "ready", code: "checkout_identity_matches", remedy: "ready" } },
      });
      if (endpoint.includes("activation-readiness")) {
        return Promise.resolve({ status: "ready", observed_at: "2026-10-05T00:00:00Z", blockers: [] });
      }
      return Promise.resolve(connectedRoster);
    });
  }

  it("keeps the active team unchanged and saves the new scope disabled (V28)", async () => {
    const team = teamFixture(true);
    const siblingA = scopeFixture(56, 12, true, "other-repo-a", "label-a");
    const siblingB = scopeFixture(57, 12, true, "other-repo-b", "label-b");
    const newScope = scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready");
    mockReadyPreflightAndRoster();
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [team] });
    mocks.fetchTeamGithubScopes.mockImplementation((teamId: number) =>
      Promise.resolve({ scopes: [siblingA, siblingB].filter((item) => item.preset_id === teamId) }));
    mocks.createTeamGithubScope.mockResolvedValue(newScope);
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    await runDraftToSavedSetupWithExistingTeam(12);

    expect(mocks.createTeamGithubScope).toHaveBeenCalledTimes(1);
    expect(mocks.createTeamGithubScope.mock.calls[0][1]).toMatchObject({
      enabled: false, merge_policy: "human", max_concurrent_dispatched: 1,
      max_verification_retries: 1, max_auto_merges_per_day: 0,
    });
    // V28: policies, autonomy, Leader and existing scopes stay untouched.
    expect(mocks.updateAgentTeamPreset).not.toHaveBeenCalled();
    expect(mocks.updateAgentTeamLeader).not.toHaveBeenCalled();
    expect(mocks.updateTeamGithubScope).not.toHaveBeenCalled();
    expect(screen.getByText(/Scope #55 is disabled/)).toBeInTheDocument();
  });

  it("recovers an interrupted save without duplicating the disabled scope (V28)", async () => {
    const team = teamFixture(true);
    const newScope = scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready");
    mockReadyPreflightAndRoster();
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [team] });
    let saved = false;
    mocks.fetchTeamGithubScopes.mockImplementation((teamId: number) =>
      Promise.resolve({ scopes: (saved ? [newScope] : []).filter((item) => item.preset_id === teamId) }));
    mocks.createTeamGithubScope.mockImplementation(() => {
      saved = true;
      return Promise.reject(new mocks.ApiHttpError("transport reset", 0));
    });
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team setup"), { target: { value: "existing" } });
    fireEvent.change(screen.getByLabelText("Team"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));

    await screen.findByText(/Reconcile uncertain create/);
    expect((await screen.findAllByText(/Do not repeat the create request/)).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: /Use Scope #55/ }));
    await screen.findByText(/Saved configuration/);
    // V28: no duplicate create, and the recovered scope stays disabled.
    expect(mocks.createTeamGithubScope).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Scope #55 is disabled/)).toBeInTheDocument();
    expect(mocks.updateTeamGithubScope).not.toHaveBeenCalled();
  });

  it("recovers a rejected third-scope save on an active team with two scopes (V28)", async () => {
    const team = teamFixture(true);
    const siblingA = scopeFixture(56, 12, true, "other-repo-a", "label-a");
    const siblingB = scopeFixture(57, 12, true, "other-repo-b", "label-b");
    const newScope = scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready");
    mockReadyPreflightAndRoster();
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [team] });
    let persisted = false;
    mocks.fetchTeamGithubScopes.mockImplementation((teamId: number) => Promise.resolve({
      scopes: (persisted ? [siblingA, siblingB, newScope] : [siblingA, siblingB])
        .filter((item) => item.preset_id === teamId),
    }));
    mocks.createTeamGithubScope.mockImplementation(() => {
      // The save persists server-side, then its response is rejected.
      persisted = true;
      return Promise.reject(new mocks.ApiHttpError("transport reset", 0));
    });
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team setup"), { target: { value: "existing" } });
    fireEvent.change(screen.getByLabelText("Team"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));

    // Actual recovery controls with fresh reads select the created scope.
    await screen.findByText(/Reconcile uncertain create/);
    fireEvent.click(screen.getByRole("button", { name: /Use Scope #55/ }));
    await screen.findByText(/Saved configuration/);
    // No second creation and no unrelated writes.
    expect(mocks.createTeamGithubScope).toHaveBeenCalledTimes(1);
    expect(mocks.updateTeamGithubScope).not.toHaveBeenCalled();
    expect(mocks.updateAgentTeamPreset).not.toHaveBeenCalled();
    expect(mocks.updateAgentTeamLeader).not.toHaveBeenCalled();
    expect(screen.getByText(/Scope #55 is disabled/)).toBeInTheDocument();

    // Unrelated state is unchanged: no write touched the siblings and the
    // recovery used fresh reads that still observe both existing scopes.
    const scopeReads = mocks.fetchTeamGithubScopes.mock.calls.length;
    expect(scopeReads).toBeGreaterThanOrEqual(3);
    fireEvent.click(screen.getByRole("button", { name: "Review current activation and overlap" }));
    await screen.findByText(/Scopes affected or overlapping:/);
    // The affected list is scope-only: the new scope, with no resumed siblings
    // on the already-active team.
    expect(screen.getByText(/team 12\/scope 55/)).toBeInTheDocument();
    expect(screen.queryByText(/team 12\/scope 56/)).not.toBeInTheDocument();
    expect(screen.queryByText(/team 12\/scope 57/)).not.toBeInTheDocument();
  });

  it("refuses an existing team without explicit Leader and never pauses it (V28)", async () => {
    const team = { ...teamFixture(true), leader_slot_id: null };
    mockReadyPreflightAndRoster();
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [team] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [] });
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team setup"), { target: { value: "existing" } });
    fireEvent.change(screen.getByLabelText("Team"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));

    await screen.findByText(/has no explicit Leader assignment/);
    // V28: a blocked role edit never pauses the team or writes configuration.
    expect(mocks.updateAgentTeamPreset).not.toHaveBeenCalled();
    expect(mocks.updateAgentTeamLeader).not.toHaveBeenCalled();
    expect(mocks.createTeamGithubScope).not.toHaveBeenCalled();
  });


  async function runToUncertainLaunchSetupWithPlanConflict() {
    const team = teamFixture(false);
    const ownScope = scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready");
    mockReadyPreflightAndRoster();
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [team] });
    mocks.fetchTeamGithubScopes.mockImplementation((teamId: number) =>
      Promise.resolve({ scopes: [ownScope].filter((item) => item.preset_id === teamId) }));
    mocks.createAgentTeamPreset.mockResolvedValue(team);
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    const conflict = new mocks.ApiHttpError("Launch plan changed; review the latest plan before launching", 409);
    (conflict as { code?: string; provenNonWrite?: boolean }).code = "plan_conflict";
    (conflict as { code?: string; provenNonWrite?: boolean }).provenNonWrite = true;
    mocks.launchAgentTeam.mockRejectedValue(conflict);
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    await runDraftToSavedSetup();
    fireEvent.click(screen.getByRole("checkbox", { name: /Worker A/ }));
    fireEvent.click(screen.getByRole("button", { name: "Review current launch plan" }));
    await screen.findByText(/Plan ready/);
    fireEvent.click(screen.getByRole("button", { name: "Launch reviewed slots" }));
  }


  async function runToUncertainLaunchSetupWithUnmarkedConflict() {
    const team = teamFixture(false);
    const ownScope = scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready");
    mockReadyPreflightAndRoster();
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [team] });
    mocks.fetchTeamGithubScopes.mockImplementation((teamId: number) =>
      Promise.resolve({ scopes: [ownScope].filter((item) => item.preset_id === teamId) }));
    mocks.createAgentTeamPreset.mockResolvedValue(team);
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    const conflict = new mocks.ApiHttpError("The selected pane changed; review a new launch plan", 409);
    (conflict as { code?: string }).code = "plan_conflict";
    mocks.launchAgentTeam.mockRejectedValue(conflict);
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    await runDraftToSavedSetup();
    fireEvent.click(screen.getByRole("checkbox", { name: /Worker A/ }));
    fireEvent.click(screen.getByRole("button", { name: "Review current launch plan" }));
    await screen.findByText(/Plan ready/);
    fireEvent.click(screen.getByRole("button", { name: "Launch reviewed slots" }));
  }

  async function runToUncertainLaunch() {
    const team = teamFixture(false);
    const ownScope = scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready");
    mockReadyPreflightAndRoster();
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [team] });
    mocks.fetchTeamGithubScopes.mockImplementation((teamId: number) =>
      Promise.resolve({ scopes: [ownScope].filter((item) => item.preset_id === teamId) }));
    mocks.createAgentTeamPreset.mockResolvedValue(team);
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    mocks.launchAgentTeam.mockRejectedValue(new Error("transport reset"));
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    await runDraftToSavedSetup();
    fireEvent.click(screen.getByRole("checkbox", { name: /Worker A/ }));
    fireEvent.click(screen.getByRole("button", { name: "Review current launch plan" }));
    await screen.findByText(/Plan ready/);
    fireEvent.click(screen.getByRole("button", { name: "Launch reviewed slots" }));
    await screen.findByText(/Launch outcome needs operator reconciliation/);
  }

  it("freezes the original launch request after an uncertain outcome (V21)", async () => {
    await runToUncertainLaunch();
    expect(mocks.launchAgentTeam).toHaveBeenCalledTimes(1);

    // The slot selection is frozen while the outcome is uncertain.
    fireEvent.click(screen.getByRole("checkbox", { name: /Worker A/ }));
    mocks.planAgentTeamLaunch.mockClear();
    mocks.planAgentTeamLaunch.mockResolvedValue({
      can_launch: false, spawn_count: 0, reuse_count: 0, blocked_count: 1, plan_hash: "synthetic-plan",
      items: [{ slot_id: 102, slot_name: "Worker A", action: "blocked", block_code: "provider_unavailable", reasons: [], matching_session: null }],
    });
    fireEvent.click(screen.getByRole("button", { name: "Reconcile current sessions" }));

    await screen.findByText(/Keep launch blocked/);
    const reconcileArgs = mocks.planAgentTeamLaunch.mock.calls.at(-1)?.[1] as { slot_ids: number[] };
    expect(reconcileArgs.slot_ids).toEqual([102]);
    expect(screen.getByText(/synthetic-plan/)).toBeInTheDocument();
    expect(mocks.launchAgentTeam).toHaveBeenCalledTimes(1);
  });

  it("confirms reconciliation only when every frozen slot has a session (V21)", async () => {
    await runToUncertainLaunch();
    mocks.planAgentTeamLaunch.mockResolvedValue({
      can_launch: true, spawn_count: 0, reuse_count: 1, blocked_count: 0, plan_hash: "synthetic-plan",
      items: [{ slot_id: 102, slot_name: "Worker A", action: "reuse", block_code: null, reasons: [], matching_session: { id: 2 } }],
    });
    fireEvent.click(screen.getByRole("button", { name: "Reconcile current sessions" }));
    await screen.findByRole("button", { name: "Confirm reconciled sessions" });
    fireEvent.click(screen.getByRole("button", { name: "Confirm reconciled sessions" }));

    await screen.findByText(/Current sessions were reconciled/);
    expect(mocks.launchAgentTeam).toHaveBeenCalledTimes(1);
    // Confirmation clears the frozen request and requires a fresh launch plan.
    expect(screen.queryByRole("button", { name: "Launch reviewed slots" })).not.toBeInTheDocument();
  });

  it("requires a fresh reviewed plan after a proven plan conflict (P04)", async () => {
    await runToUncertainLaunchSetupWithPlanConflict();
    await screen.findByText(/Review a new launch plan before launching/);
    // Proven pre-write conflict: no uncertain latch and no reconciliation path.
    expect(screen.queryByText(/Launch outcome needs operator reconciliation/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reconcile current sessions" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review current launch plan" })).toBeEnabled();
    expect(mocks.launchAgentTeam).toHaveBeenCalledTimes(1);
  });

  it("discards a late launch-plan response after the selection changes (P04)", async () => {
    const team = teamFixture(false);
    const ownScope = scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready");
    mockReadyPreflightAndRoster();
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [team] });
    mocks.fetchTeamGithubScopes.mockImplementation((teamId: number) =>
      Promise.resolve({ scopes: [ownScope].filter((item) => item.preset_id === teamId) }));
    mocks.createAgentTeamPreset.mockResolvedValue(team);
    let resolvePlan: ((value: unknown) => void) | undefined;
    mocks.planAgentTeamLaunch.mockImplementation(() => new Promise((resolve) => { resolvePlan = resolve; }));
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    await runDraftToSavedSetup();
    fireEvent.click(screen.getByRole("checkbox", { name: /Worker A/ }));
    fireEvent.click(screen.getByRole("button", { name: "Review current launch plan" }));
    await waitFor(() => expect(mocks.planAgentTeamLaunch).toHaveBeenCalledTimes(1));

    // The slot selection changes while the plan response is still in flight.
    fireEvent.click(screen.getByRole("checkbox", { name: /Worker A/ }));
    resolvePlan?.(readyPlan);

    await screen.findByText(/Inputs changed while the launch plan was built/);
    expect(screen.queryByText(/Plan ready/)).not.toBeInTheDocument();
  });

  it("blocks readiness on an incomplete observation without omitting collisions (P04)", async () => {
    const team = teamFixture(true);
    const externalTeam = { id: 20, name: "External team", autonomy_enabled: true, leader_slot_id: 201, updated_at: "2026-10-05T00:00:00Z", slots: [] };
    const ownScope = scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready");
    const external = scopeFixture(77, 20, true, "synthetic-product", "claude-deck-ready");
    mockReadyPreflightAndRoster();
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [team, externalTeam] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [ownScope, external] });
    mocks.fetchConfigurationObservation.mockResolvedValue({
      observed_at: "2026-10-05T00:00:00Z", complete: false, presets: [team, externalTeam], scopes: [ownScope, external],
    });
    mocks.createTeamGithubScope.mockResolvedValue(ownScope);
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    await runDraftToSavedSetupWithExistingTeam(12);

    fireEvent.click(screen.getByRole("button", { name: "Review current activation and overlap" }));
    await screen.findByText(/The configuration observation is incomplete/);
    // Observed collisions are still shown while readiness is blocked.
    expect(screen.getByText(/Prospective overlap/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enable this scope" })).toBeDisabled();
  });

  it("blocks the write when the final observation turns incomplete (P04)", async () => {
    const team = teamFixture(true);
    const ownScope = scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready");
    mockReadyPreflightAndRoster();
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [team] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [ownScope] });
    let incomplete = false;
    mocks.fetchConfigurationObservation.mockImplementation(async () => {
      const { presets } = await mocks.fetchAgentTeamPresets();
      const scopes = (await mocks.fetchTeamGithubScopes(12)).scopes;
      return { observed_at: "2026-10-05T00:00:00Z", complete: !incomplete, presets, scopes };
    });
    mocks.createTeamGithubScope.mockResolvedValue(ownScope);
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    mocks.updateTeamGithubScope.mockResolvedValue({ ...ownScope, enabled: true });
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    await runDraftToSavedSetupWithExistingTeam(12);
    fireEvent.click(screen.getByRole("button", { name: "Review current activation and overlap" }));
    await screen.findByRole("button", { name: "Enable this scope" });

    // A complete-to-incomplete final read must block the write even when the
    // truncated snapshot matches the reviewed set.
    incomplete = true;
    fireEvent.click(screen.getByRole("button", { name: "Enable this scope" }));
    await screen.findByText(/The final configuration observation is incomplete/);
    expect(mocks.updateTeamGithubScope).not.toHaveBeenCalled();
  });

  it("shows saved-stage preflight details with gaps and remedies (P04)", async () => {
    mockReadyPreflightAndRoster();
    mocks.apiClient.mockImplementation((endpoint: string) => {
      if (endpoint.startsWith("factory/setup-preflight")) return Promise.resolve({
        status: "blocked", observed_at: "2026-10-05T00:00:00Z", checked_at: "2026-10-05T00:00:00Z",
        checks: {
          checkout_identity: { status: "ready", code: "checkout_identity_matches", remedy: "No action is required for this check." },
          labels: { status: "blocked", code: "selected_labels_missing", remedy: "Create the selected label on the repository, then run this check again." },
        },
      });
      if (endpoint.includes("activation-readiness")) {
        return Promise.resolve({ status: "ready", observed_at: "2026-10-05T00:00:00Z", blockers: [] });
      }
      return Promise.resolve(connectedRoster);
    });
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [] });
    mocks.createAgentTeamPreset.mockResolvedValue(teamFixture(false));
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Synthetic team" } });
    fireEvent.change(screen.getByLabelText("Worker slots, one name per line"), { target: { value: "Worker A" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await screen.findByText(/Saved configuration/);

    // Saved-stage preflight details remain visible with timestamps, gaps, remedies.
    expect(screen.getByText(/Saved-stage preflight/)).toBeInTheDocument();
    expect(screen.getByText(/checkout_identity: ready \(checkout_identity_matches\)/)).toBeInTheDocument();
    expect(screen.getByText(/labels: blocked \(selected_labels_missing\)/)).toBeInTheDocument();
    expect(screen.getByText(/Gaps remain in the checks above/)).toBeInTheDocument();
  });

  it("keeps the uncertain latch for a plan conflict without proven non-write (P04)", async () => {
    await runToUncertainLaunchSetupWithUnmarkedConflict();
    await screen.findByText(/Launch outcome needs operator reconciliation/);
    expect(screen.getByRole("button", { name: "Reconcile current sessions" })).toBeEnabled();
    expect(screen.queryByText(/Review a new launch plan before launching/)).not.toBeInTheDocument();
  });

  it("blocks new launch actions while reconciliation is pending (V21)", async () => {
    await runToUncertainLaunch();
    expect(screen.getByRole("button", { name: "Review current launch plan" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Launch reviewed slots" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconcile current sessions" })).toBeEnabled();
    expect(mocks.launchAgentTeam).toHaveBeenCalledTimes(1);
  });

  it("treats the proven 400 validation refusal as a definite non-write (P04)", async () => {
    mockReadyPreflightAndRoster();
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [] });
    mocks.createAgentTeamPreset.mockRejectedValue(new mocks.ApiHttpError("team name rejected", 400));
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Synthetic team" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));

    await screen.findByText(/team name rejected/);
    // The proven validation non-write offers safe correction without a latch.
    expect(screen.queryByText(/Reconcile uncertain create/)).not.toBeInTheDocument();
    expect(mocks.createAgentTeamPreset).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Save configuration" })).toBeEnabled();
  });

  it("blocks the write when saved inputs change during the readiness wait (V21)", async () => {
    const team = teamFixture(true);
    const ownScope = scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready");
    mockReadyPreflightAndRoster();
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [team] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [ownScope] });
    const readinessResolvers: Array<(value: unknown) => void> = [];
    mocks.apiClient.mockImplementation((endpoint: string) => {
      if (endpoint.startsWith("factory/setup-preflight")) return Promise.resolve({
        status: "ready", observed_at: "2026-10-05T00:00:00Z", checked_at: "2026-10-05T00:00:00Z",
        checks: { checkout_identity: { status: "ready", code: "checkout_identity_matches", remedy: "ready" } },
      });
      if (endpoint.includes("activation-readiness")) {
        return new Promise((resolve) => { readinessResolvers.push(resolve); });
      }
      return Promise.resolve(connectedRoster);
    });
    mocks.createTeamGithubScope.mockResolvedValue(ownScope);
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    await runDraftToSavedSetupWithExistingTeam(12);
    fireEvent.click(screen.getByRole("button", { name: "Review current activation and overlap" }));
    await waitFor(() => expect(readinessResolvers).toHaveLength(1));
    readinessResolvers[0]({ status: "ready", observed_at: "2026-10-05T00:00:00Z", blockers: [] });
    const enableScope = await screen.findByRole("button", { name: "Enable this scope" });
    await waitFor(() => expect(enableScope).toBeEnabled());

    fireEvent.click(enableScope);
    await waitFor(() => expect(readinessResolvers).toHaveLength(2));
    // Saved inputs change while the activation readiness response is in flight.
    const changed = { ...ownScope, base_ref: "origin/changed" };
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [changed] });
    readinessResolvers[1]({ status: "ready", observed_at: "2026-10-05T00:00:00Z", blockers: [] });

    await screen.findByText(/changed after the readiness wait|changed after the checks/);
    expect(mocks.updateTeamGithubScope).not.toHaveBeenCalled();
  });

  it("stops stale save continuation from writing for changed inputs (V21)", async () => {
    mockReadyPreflightAndRoster();
    const team = teamFixture(false);
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [] });
    let resolveCreate: ((value: unknown) => void) | undefined;
    mocks.createAgentTeamPreset.mockImplementation(() => new Promise((resolve) => { resolveCreate = resolve; }));
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Synthetic team" } });
    fireEvent.change(screen.getByLabelText("Worker slots, one name per line"), { target: { value: "Worker A" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await waitFor(() => expect(resolveCreate).toBeDefined());

    // Keyed inputs change while the create response is still in flight.
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.change(screen.getByLabelText("Dispatch label"), { target: { value: "changed-during-save" } });
    resolveCreate?.(team);

    await screen.findByText(/Inputs changed during the save/);
    expect(mocks.updateAgentTeamLeader).not.toHaveBeenCalled();
    expect(mocks.createTeamGithubScope).not.toHaveBeenCalled();
  });

  it("stops stale save for changed team and provider inputs (V21)", async () => {
    mockReadyPreflightAndRoster();
    const team = teamFixture(false);
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [] });
    let resolveCreate: ((value: unknown) => void) | undefined;
    mocks.createAgentTeamPreset.mockImplementation(() => new Promise((resolve) => { resolveCreate = resolve; }));
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Synthetic team" } });
    fireEvent.change(screen.getByLabelText("Worker slots, one name per line"), { target: { value: "Worker A" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await waitFor(() => expect(resolveCreate).toBeDefined());

    // Team and provider inputs change while the create response is in flight.
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Changed team" } });
    fireEvent.change(screen.getByLabelText("Worker and Leader provider"), { target: { value: "pi-cli" } });
    resolveCreate?.(team);

    await screen.findByText(/Inputs changed during the save/);
    expect(mocks.updateAgentTeamLeader).not.toHaveBeenCalled();
    expect(mocks.createTeamGithubScope).not.toHaveBeenCalled();
  });

  it("stops stale save for changed routing inputs (V21)", async () => {
    mockReadyPreflightAndRoster();
    const team = teamFixture(false);
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [] });
    let resolveCreate: ((value: unknown) => void) | undefined;
    mocks.createAgentTeamPreset.mockImplementation(() => new Promise((resolve) => { resolveCreate = resolve; }));
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Synthetic team" } });
    fireEvent.change(screen.getByLabelText("Worker slots, one name per line"), { target: { value: "Worker A" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.change(within(screen.getByRole("group", { name: "Worker A" })).getByLabelText("Area labels, comma separated"), { target: { value: "backend" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await waitFor(() => expect(resolveCreate).toBeDefined());

    // Routing inputs change while the create response is in flight.
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.change(within(screen.getByRole("group", { name: "Worker A" })).getByLabelText("Area labels, comma separated"), { target: { value: "frontend" } });
    resolveCreate?.(team);

    await screen.findByText(/Inputs changed during the save/);
    expect(mocks.createTeamGithubScope).not.toHaveBeenCalled();
  });

  it("stops stale save for changed existing-team selection during the initial observation (V21)", async () => {
    mockReadyPreflightAndRoster();
    const firstTeam = teamFixture(true);
    const secondTeam = { ...teamFixture(true), id: 13, name: "Second existing team" };
    let reads = 0;
    let saveReadEntered = false;
    let signalSaveRead: (() => void) | undefined;
    const saveReadEnteredSignal = new Promise<void>((resolve) => { signalSaveRead = resolve; });
    let releaseSaveRead: (() => void) | undefined;
    const saveReadGate = new Promise<void>((resolve) => { releaseSaveRead = resolve; });
    mocks.fetchAgentTeamPresets.mockImplementation(async () => {
      reads += 1;
      if (reads >= 2) {
        saveReadEntered = true;
        signalSaveRead?.();
        await saveReadGate;
      }
      return { presets: [firstTeam, secondTeam] };
    });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [] });
    mocks.createAgentTeamPreset.mockResolvedValue(firstTeam);
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team setup"), { target: { value: "existing" } });
    fireEvent.change(screen.getByLabelText("Team"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    // The save's initial observation has actually entered before any change.
    await saveReadEnteredSignal;
    expect(saveReadEntered).toBe(true);

    // The selected existing team changes while the initial observation waits.
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.change(screen.getByLabelText("Team"), { target: { value: "13" } });
    releaseSaveRead?.();

    await screen.findByText(/Inputs changed during the save/);
    expect(mocks.createAgentTeamPreset).not.toHaveBeenCalled();
    expect(mocks.createTeamGithubScope).not.toHaveBeenCalled();
    expect(screen.queryByText(/Saved configuration/)).not.toBeInTheDocument();
  });

  it("stops stale save during the final observation wait (V21)", async () => {
    mockReadyPreflightAndRoster();
    const team = teamFixture(false);
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [] });
    mocks.createAgentTeamPreset.mockResolvedValue(team);
    mocks.createTeamGithubScope.mockResolvedValue(scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready"));
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    let finalReadEntered = false;
    let signalFinalRead: (() => void) | undefined;
    const finalReadEnteredSignal = new Promise<void>((resolve) => { signalFinalRead = resolve; });
    let releaseFinalRead: (() => void) | undefined;
    const finalReadGate = new Promise<void>((resolve) => { releaseFinalRead = resolve; });
    let reads = 0;
    const originalObservation = mocks.fetchConfigurationObservation.getMockImplementation()!;
    mocks.fetchConfigurationObservation.mockImplementation(async () => {
      reads += 1;
      if (reads >= 3) {
        finalReadEntered = true;
        signalFinalRead?.();
        await finalReadGate;
      }
      return originalObservation();
    });
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Synthetic team" } });
    fireEvent.change(screen.getByLabelText("Worker slots, one name per line"), { target: { value: "Worker A" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    // The team and scope writes completed and the final read actually entered.
    await waitFor(() => expect(mocks.createTeamGithubScope).toHaveBeenCalledTimes(1));
    await finalReadEnteredSignal;
    expect(finalReadEntered).toBe(true);

    // Keyed inputs change while the final observation is in flight.
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.change(screen.getByLabelText("Dispatch label"), { target: { value: "changed-during-final-read" } });
    releaseFinalRead?.();

    await screen.findByText(/Inputs changed during the save/);
    expect(screen.queryByText(/Saved configuration/)).not.toBeInTheDocument();
  });

  it("blocks page input while the operator-token prompt is open (V21 unreachability)", async () => {
    let stored: string | null = null;
    mocks.getOperatorToken.mockImplementation(() => stored);
    mocks.setOperatorToken.mockImplementation((value: string) => { stored = value; });
    mockReadyPreflightAndRoster();
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [] });
    mocks.createAgentTeamPreset.mockResolvedValue(teamFixture(false));
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByPlaceholderText("Enter secret value"), { target: { value: "preflight-token" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Use token" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Synthetic team" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    stored = null;
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    const saveDialog = await screen.findByRole("dialog");

    // The credential prompt is modal: page inputs are inaccessible while it is
    // open, so changed inputs during the credential wait are unreachable. The
    // live-intent checks remain as defense in depth.
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
    fireEvent.change(within(saveDialog).getByPlaceholderText("Enter secret value"), { target: { value: "save-token" } });
    fireEvent.click(within(saveDialog).getByRole("button", { name: "Use token" }));

    // With unchanged inputs the save continues normally.
    await screen.findByText(/Saved configuration/);
    expect(mocks.createAgentTeamPreset).toHaveBeenCalledTimes(1);
  });

  it("preserves the Leader record and stops stale writes after the Leader wait (V21)", async () => {
    mockReadyPreflightAndRoster();
    const createdTeam = { ...teamFixture(false), leader_slot_id: null };
    const fixedTeam = teamFixture(false);
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [createdTeam] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [] });
    mocks.createAgentTeamPreset.mockResolvedValue(createdTeam);
    let resolveLeader: ((value: unknown) => void) | undefined;
    mocks.updateAgentTeamLeader.mockImplementation(() => new Promise((resolve) => { resolveLeader = resolve; }));
    mocks.createTeamGithubScope.mockResolvedValue(scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready"));
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Synthetic team" } });
    fireEvent.change(screen.getByLabelText("Worker slots, one name per line"), { target: { value: "Worker A" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await waitFor(() => expect(resolveLeader).toBeDefined());

    // Keyed inputs change while the Leader update is in flight.
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.change(screen.getByLabelText("Dispatch label"), { target: { value: "changed-during-leader-wait" } });
    resolveLeader?.(fixedTeam);

    await screen.findByText(/The Leader record is saved/);
    expect(mocks.updateAgentTeamLeader).toHaveBeenCalledTimes(1);
    expect(mocks.createTeamGithubScope).not.toHaveBeenCalled();
    expect(screen.queryByText(/Saved configuration/)).not.toBeInTheDocument();
  });

  it("re-prompts through the shared credential helper after a 401 create (V20)", async () => {
    let stored: string | null = "synthetic-operator";
    mocks.getOperatorToken.mockImplementation(() => stored);
    mocks.clearOperatorToken.mockImplementation(() => { stored = null; });
    mocks.setOperatorToken.mockImplementation((value: string) => { stored = value; });
    mockReadyPreflightAndRoster();
    const team = teamFixture(false);
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [] });
    mocks.createAgentTeamPreset
      .mockRejectedValueOnce(new mocks.ApiHttpError("The operator token was rejected.", 401))
      .mockResolvedValue(team);
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Synthetic team" } });
    fireEvent.change(screen.getByLabelText("Worker slots, one name per line"), { target: { value: "Worker A" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));

    // The shared protected helper clears the rejected credential, re-prompts,
    // and retries the create with the new token.
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByPlaceholderText("Enter secret value"), { target: { value: "fresh-token" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Use token" }));
    await screen.findByText(/Saved configuration/);
    expect(mocks.createAgentTeamPreset).toHaveBeenCalledTimes(2);
    expect(mocks.setOperatorToken).toHaveBeenCalledWith("fresh-token");
  });

  it("keeps the create latch when reconciliation fails (V20/V21)", async () => {
    mockReadyPreflightAndRoster();
    let reads = 0;
    mocks.fetchAgentTeamPresets.mockImplementation(() => {
      reads += 1;
      return reads <= 2 ? Promise.resolve({ presets: [] }) : Promise.reject(new Error("read failed"));
    });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [] });
    mocks.createAgentTeamPreset.mockRejectedValue(new mocks.ApiHttpError("transport reset", 0));
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Synthetic team" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));

    // Failed reconciliation keeps the no-duplicate-create latch and offers no
    // selection. The shown error is the safe underlying read failure.
    await screen.findByText(/No unique record is ready for selection/);
    expect(screen.getByText(/read failed/)).toBeInTheDocument();
    expect(mocks.createAgentTeamPreset).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /Use / })).not.toBeInTheDocument();
  });

  it("resumes an interrupted Leader assignment without a duplicate team (V21)", async () => {
    mockReadyPreflightAndRoster();
    const createdTeam = { ...teamFixture(false), leader_slot_id: null };
    const fixedTeam = teamFixture(false);
    const newScope = scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready");
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [createdTeam] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [] });
    mocks.createAgentTeamPreset.mockResolvedValue(createdTeam);
    mocks.updateAgentTeamLeader
      .mockRejectedValueOnce(new mocks.ApiHttpError("stale expected state", 409))
      .mockResolvedValue(fixedTeam);
    mocks.createTeamGithubScope.mockResolvedValue(newScope);
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Synthetic team" } });
    fireEvent.change(screen.getByLabelText("Worker slots, one name per line"), { target: { value: "Worker A" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await screen.findByText(/stale expected state/);

    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await screen.findByText(/Saved configuration/);
    // V21: the interrupted role step resumes on the created team without a
    // duplicate create, and completes the explicit Leader assignment.
    expect(mocks.createAgentTeamPreset).toHaveBeenCalledTimes(1);
    expect(mocks.updateAgentTeamLeader).toHaveBeenCalledTimes(2);
    expect(mocks.createTeamGithubScope).toHaveBeenCalledTimes(1);
  });

  it("refuses a recovered team after the draft changes (V21)", async () => {
    mockReadyPreflightAndRoster();
    const createdTeam = teamFixture(false);
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [createdTeam] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [] });
    mocks.createAgentTeamPreset.mockRejectedValue(new mocks.ApiHttpError("transport reset", 0));
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Synthetic team" } });
    fireEvent.change(screen.getByLabelText("Worker slots, one name per line"), { target: { value: "Worker A" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await screen.findByText(/Reconcile uncertain create/);

    // The draft changes before the operator selects the recovered record.
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Changed team name" } });
    fireEvent.click(screen.getByRole("button", { name: /Use Synthetic team/ }));
    await screen.findByText(/no longer matches this draft/);
    expect(mocks.createAgentTeamPreset).toHaveBeenCalledTimes(1);
  });

  it("captures implemented-flow configuration and compares it with saved payloads (V32)", async () => {
    mockReadyPreflightAndRoster();
    const team = teamFixture(false);
    const newScope = scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready");
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [] });
    mocks.createAgentTeamPreset.mockResolvedValue(team);
    mocks.createTeamGithubScope.mockResolvedValue(newScope);
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);

    // Requested configuration from the implemented flow.
    fireEvent.change(screen.getByLabelText("Repository owner"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Repository name"), { target: { value: "synthetic-product" } });
    fireEvent.change(screen.getByLabelText("Primary checkout path"), { target: { value: "/synthetic/checkout" } });
    fireEvent.click(screen.getByRole("button", { name: "Check access and labels" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to configuration" }));
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "Synthetic team" } });
    fireEvent.change(screen.getByLabelText("Worker slots, one name per line"), { target: { value: "Worker A" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.change(within(screen.getByRole("group", { name: "Worker A" })).getByLabelText("Area labels, comma separated"), { target: { value: "backend" } });
    fireEvent.change(within(screen.getByRole("group", { name: "Worker A" })).getByLabelText("Expertise"), { target: { value: "API" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Review setup" }));
    fireEvent.click(screen.getByLabelText(/Save configuration only/));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await screen.findByText(/Saved configuration/);

    // The captured team payload equals the requested roster and routing.
    const teamPayload = mocks.createAgentTeamPreset.mock.calls[0][0];
    expect(teamPayload).toMatchObject({ name: "Synthetic team", autonomy_enabled: false });
    expect(teamPayload.slots).toMatchObject([
      { display_name: "Leader", role: "Leader", provider: "codex-cli", repo_path: "/synthetic/checkout", area_labels: [], expertise: null },
      { display_name: "Worker A", role: "Worker", provider: "codex-cli", repo_path: "/synthetic/checkout", area_labels: ["backend"], expertise: "API" },
    ]);
    // The captured scope payload equals the requested repository configuration.
    // The draft selects the GitHub token dispatch mode; the documented mapping
    // saves it as the ambient auth mode. github_app maps to app.
    const scopePayload = mocks.createTeamGithubScope.mock.calls[0][1];
    expect(scopePayload).toMatchObject({
      repo_owner: "example", repo_name: "synthetic-product", repo_path: "/synthetic/checkout",
      dispatch_label: "claude-deck-ready", design_label: "claude-deck-design", base_ref: "origin/HEAD",
      github_auth_mode: "ambient", merge_policy: "human", enabled: false,
      max_concurrent_dispatched: 1, max_verification_retries: 1, max_auto_merges_per_day: 0,
    });
    expect(scopePayload.github_auth_mode).toBe("ambient");
    // The saved configuration shown to the operator equals the created records.
    expect(screen.getByText(/Team Synthetic team \(#12\)/)).toBeInTheDocument();
    expect(screen.getByText(/Scope #55 is disabled/)).toBeInTheDocument();
    expect(screen.getByText(/A cached fallback is not current evidence/)).toBeInTheDocument();
  });

  it("activates only the new scope on an active team (V28)", async () => {
    const team = teamFixture(true);
    const siblingA = scopeFixture(56, 12, true, "other-repo-a", "label-a");
    const siblingB = scopeFixture(57, 12, true, "other-repo-b", "label-b");
    const newScope = scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready");
    mockReadyPreflightAndRoster();
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [team] });
    mocks.fetchTeamGithubScopes.mockImplementation((teamId: number) =>
      Promise.resolve({ scopes: [siblingA, siblingB, newScope].filter((item) => item.preset_id === teamId) }));
    mocks.createTeamGithubScope.mockResolvedValue(newScope);
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    mocks.updateTeamGithubScope.mockResolvedValue({ ...newScope, enabled: true });
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    await runDraftToSavedSetupWithExistingTeam(12);

    fireEvent.click(screen.getByRole("button", { name: "Review current activation and overlap" }));
    await screen.findByRole("button", { name: "Enable this scope" });
    fireEvent.click(screen.getByRole("button", { name: "Enable this scope" }));

    await waitFor(() => expect(mocks.updateTeamGithubScope).toHaveBeenCalledTimes(1));
    expect(mocks.updateTeamGithubScope.mock.calls[0][0]).toBe(55);
    expect(mocks.updateTeamGithubScope.mock.calls[0][1]).toMatchObject({ enabled: true });
    // V28: scope-only activation never touches the team or the sibling scopes.
    expect(mocks.updateAgentTeamPreset).not.toHaveBeenCalled();
    expect(mocks.updateAgentTeamLeader).not.toHaveBeenCalled();
  });

  it("previews every resumed sibling for a paused team and gates team activation (V28)", async () => {
    const team = teamFixture(false);
    const siblingA = scopeFixture(56, 12, true, "other-repo-a", "label-a");
    const siblingB = scopeFixture(57, 12, true, "other-repo-b", "label-b");
    const newScope = scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready");
    mockReadyPreflightAndRoster();
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [team] });
    mocks.fetchTeamGithubScopes.mockImplementation((teamId: number) =>
      Promise.resolve({ scopes: [siblingA, siblingB, newScope].filter((item) => item.preset_id === teamId) }));
    mocks.createTeamGithubScope.mockResolvedValue(newScope);
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    await runDraftToSavedSetupWithExistingTeam(12);

    fireEvent.click(screen.getByRole("button", { name: "Review current activation and overlap" }));
    await screen.findByText(/Scopes affected or overlapping:/);
    // V28: every already-enabled sibling that team activation resumes is listed.
    expect(screen.getByText(/team 12\/scope 56/)).toBeInTheDocument();
    expect(screen.getByText(/team 12\/scope 57/)).toBeInTheDocument();
    // The team-wide effect needs its own acknowledgement before activation.
    expect(screen.getByRole("button", { name: "Enable team automation" })).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/Enable team automation/));
    expect(screen.getByRole("button", { name: "Enable team automation" })).toBeEnabled();
    expect(mocks.updateAgentTeamPreset).not.toHaveBeenCalled();
  });

  it("requires one acknowledgement per simultaneous overlap (V36)", async () => {
    const team = teamFixture(false);
    const externalTeam = { id: 20, name: "External team", autonomy_enabled: true, leader_slot_id: 201, updated_at: "2026-10-05T00:00:00Z", slots: [] };
    const ownScope = scopeFixture(55, 12, false, "synthetic-product", "claude-deck-ready");
    const siblingOne = scopeFixture(56, 12, true, "other-repo-a", "shared-a");
    const siblingTwo = scopeFixture(57, 12, true, "other-repo-b", "shared-b");
    const externalOne = scopeFixture(77, 20, true, "other-repo-a", "shared-a");
    const externalTwo = scopeFixture(78, 20, true, "other-repo-b", "shared-b");
    const allScopes = [ownScope, siblingOne, siblingTwo, externalOne, externalTwo];
    mockReadyPreflightAndRoster();
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [team, externalTeam] });
    mocks.fetchTeamGithubScopes.mockImplementation((teamId: number) =>
      Promise.resolve({ scopes: allScopes.filter((item) => item.preset_id === teamId) }));
    mocks.createTeamGithubScope.mockResolvedValue(ownScope);
    mocks.planAgentTeamLaunch.mockResolvedValue(readyPlan);
    render(<MemoryRouter><RepositorySetupPage /></MemoryRouter>);
    await runDraftToSavedSetupWithExistingTeam(12);

    fireEvent.click(screen.getByRole("button", { name: "Review current activation and overlap" }));
    const boxes = await screen.findAllByRole("checkbox", { name: /Prospective overlap/ });
    expect(boxes).toHaveLength(2);
    fireEvent.click(screen.getByLabelText(/Enable team automation/));
    expect(screen.getByRole("button", { name: "Enable team automation" })).toBeDisabled();
    // V36: every overlap.key needs its own acknowledgement.
    fireEvent.click(boxes[0]);
    expect(screen.getByRole("button", { name: "Enable team automation" })).toBeDisabled();
    fireEvent.click(boxes[1]);
    expect(screen.getByRole("button", { name: "Enable team automation" })).toBeEnabled();
    expect(mocks.updateAgentTeamPreset).not.toHaveBeenCalled();
  });
});
