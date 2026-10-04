import { MemoryRouter, Routes, Route, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AgentTeamsPage } from "../src/features/agent-teams/AgentTeamsPage";
import {
  fetchAgentTeamPresets,
  fetchTeamGithubScopes,
  launchAgentTeam,
  planAgentTeamLaunch,
} from "../src/features/agent-teams/api";
import {
  clearOperatorToken,
  setOperatorToken,
} from "../src/features/agent-teams/operatorAuth";
import { ApiHttpError } from "../src/lib/api";
import type {
  AgentTeamLaunchPlan,
  AgentTeamLaunchResult,
  AgentTeamPreset,
} from "../src/types/agentTeams";

vi.mock("../src/features/agent-teams/api", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../src/features/agent-teams/api")>();
  return {
    ...actual,
    fetchAgentTeamPresets: vi.fn(),
    fetchTeamGithubScopes: vi.fn().mockResolvedValue({ scopes: [] }),
    planAgentTeamLaunch: vi.fn(),
    launchAgentTeam: vi.fn(),
  };
});

vi.mock("../src/hooks/useProviders", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../src/hooks/useProviders")>();
  return {
    ...actual,
    fetchProviderLaunchOptions: vi.fn(async (provider: string) => ({
      provider,
      supported_launch_modes: ["plain"],
    })),
  };
});

const timestamp = "2026-10-01T12:00:00Z";

const preset: AgentTeamPreset = {
  id: 1,
  name: "Test team",
  created_at: timestamp,
  updated_at: timestamp,
  autonomy_enabled: false,
  slots: [
    {
      id: 2,
      preset_id: 1,
      position: 1,
      display_name: "Leader",
      provider: "codex-cli",
      repo_id: "repo",
      repo_path: "/tmp/repo",
      repo_name: "repo",
      launch_mode: "plain",
      launch_options: {},
      enabled: true,
      created_at: timestamp,
      updated_at: timestamp,
    },
  ],
};

const plan: AgentTeamLaunchPlan = {
  preset_id: 1,
  preset_name: "Test team",
  plan_hash: "plan-hash",
  generated_at: timestamp,
  can_launch: true,
  items: [
    {
      slot_id: 2,
      slot_name: "Leader",
      provider: "codex-cli",
      repo_id: "repo",
      repo_path: "/tmp/repo",
      repo_name: "repo",
      action: "spawn",
      status: "ready",
      reasons: [],
    },
  ],
  reuse_count: 0,
  adopt_count: 0,
  spawn_count: 1,
  skipped_count: 0,
  blocked_count: 0,
};

const result: AgentTeamLaunchResult = {
  launch_id: 3,
  preset_id: 1,
  preset_name: "Test team",
  plan_hash: "plan-hash",
  status: "completed",
  launched_at: timestamp,
  completed_at: timestamp,
  items: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  clearOperatorToken();
  vi.mocked(fetchAgentTeamPresets)
    .mockReset()
    .mockResolvedValue({ presets: [preset] });
  vi.mocked(fetchTeamGithubScopes)
    .mockReset()
    .mockResolvedValue({ scopes: [] });
  vi.mocked(planAgentTeamLaunch).mockResolvedValue(plan);
  vi.mocked(launchAgentTeam).mockResolvedValue(result);
});

describe("AgentTeamsPage launch authorization", () => {
  it("shows only the token dialog before the first plan request", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AgentTeamsPage />
      </MemoryRouter>,
    );

    await user.click(
      await screen.findByRole("button", { name: "Plan launch" }),
    );
    const tokenDialog = await screen.findByRole("dialog", {
      name: "Operator token",
    });
    expect(
      screen.queryByRole("dialog", { name: "Launch Plan" }),
    ).not.toBeInTheDocument();
    expect(planAgentTeamLaunch).not.toHaveBeenCalled();

    const input = within(tokenDialog).getByLabelText(/Operator token/);
    await user.click(input);
    expect(input).toHaveFocus();
    await user.type(input, "test-token{Enter}");

    await waitFor(() =>
      expect(planAgentTeamLaunch).toHaveBeenCalledWith(
        1,
        { slot_ids: null, adopt_unbound_sessions: false, reuse_existing: true },
        "test-token",
      ),
    );
    expect(
      await screen.findByRole("dialog", { name: "Launch Plan" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("dialog", { name: "Operator token" }),
    ).not.toBeInTheDocument();
  });

  it("hides the plan while re-prompting after a rejected launch token", async () => {
    setOperatorToken("old-token");
    vi.mocked(launchAgentTeam)
      .mockRejectedValueOnce(
        new ApiHttpError("The operator token was rejected.", 401),
      )
      .mockResolvedValueOnce(result);
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AgentTeamsPage />
      </MemoryRouter>,
    );

    await user.click(
      await screen.findByRole("button", { name: "Plan launch" }),
    );
    expect(
      await screen.findByRole("dialog", { name: "Launch Plan" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Launch" }));

    const tokenDialog = await screen.findByRole("dialog", {
      name: "Operator token",
    });
    expect(
      screen.queryByRole("dialog", { name: "Launch Plan" }),
    ).not.toBeInTheDocument();
    const input = within(tokenDialog).getByLabelText(/Operator token/);
    await user.click(input);
    await user.type(input, "new-token{Enter}");

    await waitFor(() =>
      expect(launchAgentTeam).toHaveBeenLastCalledWith(
        1,
        expect.objectContaining({ confirm_plan_hash: "plan-hash" }),
        "new-token",
      ),
    );
    expect(
      await screen.findByRole("dialog", { name: "Launch Plan" }),
    ).toBeInTheDocument();
  });
});

describe("Teams current route and stale reads", () => {
  function Navigation() {
    const navigate = useNavigate();
    return (
      <button onClick={() => navigate("/teams/2?slot_id=2&review_launch=1")}>
        Open Team2 context
      </button>
    );
  }
  const team2 = {
    ...preset,
    id: 2,
    name: "Team2",
    slots: preset.slots.map((slot) => ({ ...slot, preset_id: 2 })),
  };
  const teams = { presets: [{ ...preset, name: "Team1" }, team2] };
  function renderTeams(path = "/teams/1?slot_id=2&review_launch=1") {
    return render(
      <MemoryRouter initialEntries={[path]}>
        <Navigation />
        <Routes>
          <Route path="/teams/:teamId" element={<AgentTeamsPage />} />
        </Routes>
      </MemoryRouter>,
    );
  }
  it("ignores an older preset response and binds the current URL controls to Team2", async () => {
    let release!: (value: { presets: AgentTeamPreset[] }) => void;
    vi.mocked(fetchAgentTeamPresets)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            release = resolve;
          }),
      )
      .mockResolvedValue(teams);
    renderTeams();
    await waitFor(() => expect(fetchAgentTeamPresets).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Open Team2 context" }));
    await waitFor(() =>
      expect(screen.getByLabelText("Name")).toHaveValue("Team2"),
    );
    await act(async () => release({ presets: [{ ...preset, name: "Team1" }] }));
    expect(screen.getByLabelText("Name")).toHaveValue("Team2");
    setOperatorToken("synthetic-route-operator");
    fireEvent.click(
      screen.getByRole("button", {
        name: "Review current authenticated launch plan",
      }),
    );
    await waitFor(() =>
      expect(planAgentTeamLaunch).toHaveBeenCalledWith(
        2,
        { slot_ids: [2], adopt_unbound_sessions: false, reuse_existing: true },
        "synthetic-route-operator",
      ),
    );
    expect(launchAgentTeam).not.toHaveBeenCalled();
  });
  it("keeps current URL controls bound to Team2 while its refresh is still pending", async () => {
    let release!: (value: { presets: AgentTeamPreset[] }) => void;
    vi.mocked(fetchAgentTeamPresets)
      .mockResolvedValueOnce(teams)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            release = resolve;
          }),
      );
    renderTeams();
    await waitFor(() =>
      expect(screen.getByLabelText("Name")).toHaveValue("Team1"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Open Team2 context" }));
    await waitFor(() => expect(fetchAgentTeamPresets).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("Name")).toHaveValue("Team2");
    await act(async () => release(teams));
    expect(screen.getByLabelText("Name")).toHaveValue("Team2");
  });
  it("does not expose an old pending launch plan after navigating to another team", async () => {
    let release!: (value: AgentTeamLaunchPlan) => void;
    vi.mocked(fetchAgentTeamPresets).mockResolvedValue(teams);
    vi.mocked(planAgentTeamLaunch).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    setOperatorToken("synthetic-route-operator");
    renderTeams();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Review current authenticated launch plan",
      }),
    );
    await waitFor(() => expect(planAgentTeamLaunch).toHaveBeenCalledTimes(1));
    fireEvent.click(
      screen.getByRole("button", { name: "Open Team2 context", hidden: true }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Name")).toHaveValue("Team2"),
    );
    await act(async () => release(plan));
    expect(
      screen.queryByRole("dialog", { name: "Launch Plan" }),
    ).not.toBeInTheDocument();
    expect(launchAgentTeam).not.toHaveBeenCalled();
  });
  it("cancels a rejected launch token re-prompt on navigation and never retries the prior team", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchAgentTeamPresets).mockResolvedValue(teams);
    vi.mocked(planAgentTeamLaunch).mockImplementation(async (id) => ({
      ...plan,
      preset_id: id,
      preset_name: id === 1 ? "Team1" : "Team2",
    }));
    vi.mocked(launchAgentTeam).mockRejectedValueOnce(
      new ApiHttpError("Rejected operator token", 401),
    );
    setOperatorToken("synthetic-rejected-token");
    renderTeams();
    await user.click(
      await screen.findByRole("button", {
        name: "Review current authenticated launch plan",
      }),
    );
    const launch = await screen.findByRole("dialog", { name: "Launch Plan" });
    await user.click(within(launch).getByRole("button", { name: "Launch" }));
    await screen.findByRole("dialog", { name: "Operator token" });
    expect(launchAgentTeam).toHaveBeenCalledTimes(1);
    fireEvent.click(
      screen.getByRole("button", { name: "Open Team2 context", hidden: true }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Name")).toHaveValue("Team2"),
    );
    expect(
      screen.queryByRole("dialog", { name: "Operator token" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("dialog", { name: "Launch Plan" }),
    ).not.toBeInTheDocument();
    // A replacement credential belongs to a NEW explicit Team2 plan request.
    await user.click(
      screen.getByRole("button", {
        name: "Review current authenticated launch plan",
      }),
    );
    const current = await screen.findByRole("dialog", {
      name: "Operator token",
    });
    await user.type(
      within(current).getByLabelText(/Operator token/),
      "synthetic-current-token{Enter}",
    );
    await waitFor(() =>
      expect(
        vi.mocked(planAgentTeamLaunch).mock.calls.map((call) => call[0]),
      ).toEqual([1, 2]),
    );
    expect(
      await screen.findByRole("dialog", { name: "Launch Plan" }),
    ).toBeInTheDocument();
    expect(
      vi.mocked(launchAgentTeam).mock.calls.map((call) => call[0]),
    ).toEqual([1]);
    expect(vi.mocked(launchAgentTeam).mock.calls[0][2]).toBe(
      "synthetic-rejected-token",
    );
  });
  it("ignores an old launch result without refreshing presets after navigation", async () => {
    let release!: (value: AgentTeamLaunchResult) => void;
    vi.mocked(fetchAgentTeamPresets).mockResolvedValue(teams);
    vi.mocked(launchAgentTeam).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    setOperatorToken("synthetic-current-token");
    renderTeams();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Review current authenticated launch plan",
      }),
    );
    const launch = await screen.findByRole("dialog", { name: "Launch Plan" });
    fireEvent.click(within(launch).getByRole("button", { name: "Launch" }));
    await waitFor(() => expect(launchAgentTeam).toHaveBeenCalledTimes(1));
    fireEvent.click(
      screen.getByRole("button", { name: "Open Team2 context", hidden: true }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Name")).toHaveValue("Team2"),
    );
    const reads = vi.mocked(fetchAgentTeamPresets).mock.calls.length;
    await act(async () => release(result));
    expect(fetchAgentTeamPresets).toHaveBeenCalledTimes(reads);
    expect(
      screen.queryByRole("dialog", { name: "Launch Plan" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("Team2");
  });
  it("retires an old initial scope response before it can switch the current roster tab", async () => {
    let release!: (
      value: Awaited<ReturnType<typeof fetchTeamGithubScopes>>,
    ) => void;
    vi.mocked(fetchAgentTeamPresets).mockResolvedValue(teams);
    vi.mocked(fetchTeamGithubScopes)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            release = resolve;
          }),
      )
      .mockResolvedValue({ scopes: [] });
    renderTeams("/teams/1");
    await waitFor(() => expect(fetchTeamGithubScopes).toHaveBeenCalledWith(1));
    fireEvent.click(screen.getByRole("button", { name: "Open Team2 context" }));
    await waitFor(() =>
      expect(screen.getByLabelText("Name")).toHaveValue("Team2"),
    );
    await act(async () =>
      release({
        scopes: [{}] as Awaited<
          ReturnType<typeof fetchTeamGithubScopes>
        >["scopes"],
      }),
    );
    expect(screen.getByLabelText("Name")).toHaveValue("Team2");
    expect(screen.getByLabelText("Name")).toBeVisible();
    expect(screen.getByRole("button", { name: "Plan launch" })).toBeVisible();
    expect(fetchTeamGithubScopes).toHaveBeenCalledTimes(1);
  });
});
