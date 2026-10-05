import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiClient: vi.fn(),
  fetchAgentTeamPresets: vi.fn(),
  fetchTeamGithubScopes: vi.fn(),
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
}));

vi.mock("@/lib/api", () => ({ apiClient: mocks.apiClient, ApiHttpError: class ApiHttpError extends Error {} }));
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

    resolveCheck?.({
      status: "ready", checked_at: "2026-10-05T00:00:00Z",
      checks: { checkout_identity: { status: "ready", code: "checkout_identity_matches" } },
    });

    await waitFor(() => expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled());
    expect(screen.queryByText(/Current result:/)).not.toBeInTheDocument();
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
    fireEvent.click(await screen.findByRole("button", { name: "Continue" }));
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
    fireEvent.click(await screen.findByRole("button", { name: "Continue" }));
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
});
