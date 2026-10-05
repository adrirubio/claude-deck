import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
}));

vi.mock("@/lib/api", () => ({ apiClient: mocks.apiClient, ApiHttpError: class ApiHttpError extends Error {} }));
vi.mock("@/features/agent-teams/operatorAuth", () => ({ getOperatorToken: () => "synthetic-operator" }));
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
    mocks.fetchAgentTeamPresets.mockResolvedValue({ presets: [] });
    mocks.fetchTeamGithubScopes.mockResolvedValue({ scopes: [] });
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
});
