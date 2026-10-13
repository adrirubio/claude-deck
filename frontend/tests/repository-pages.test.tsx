import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RepositoriesPage } from "../src/features/factory/pages/RepositoriesPage";
import { RepositoryPage } from "../src/features/factory/pages/RepositoryPage";
import { resetFactoryReads } from "../src/features/factory/reads";
import { clearOperatorToken } from "../src/features/agent-teams/operatorAuth";
import { fixtureFetch, jsonResponse, renderRoute, settle } from "./helpers/factory";
import repositories from "./fixtures/factory/v1-p04/repositories.json";
import repository from "./fixtures/factory/v1-p04/repository.json";

beforeEach(() => {
  resetFactoryReads();
  clearOperatorToken();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const scope = {
  id: 1, preset_id: 1, repo_owner: "fixture", repo_name: "shared", repo_path: "/tmp/shared",
  dispatch_label: "claude-deck-ready", design_label: "claude-deck-design", merge_policy: "human",
  github_auth_mode: "app", github_auth_configured: true, github_poll_token_configured: true,
  max_approval_rounds: 3, max_concurrent_dispatched: 3, max_verification_retries: 2, max_auto_merges_per_day: 5,
  base_ref: "origin/release/v3.1", builds_out_of_tree: false, build_dir_template: "build", build_command_hint: null,
  max_build_parallelism: 4, continuation_enabled: false, max_continuation_revisions: 3, max_continuation_failed_heads: 8,
  max_failed_heads_per_revision: 1, max_scope_paths: 4, max_scope_commands: 8, enabled: true,
  created_at: "2026-09-29T12:00:00Z", updated_at: "2026-09-29T12:00:00Z",
};
const counts = { active: 2, attention: 0, finished: 3, queued: 0, review: 0, total: 5, unknown: 0 };

function serve(overrides: Record<string, () => Response> = {}) {
  return fixtureFetch((path) => {
    if (overrides[path]) return overrides[path]();
    if (path === "factory/repositories") return jsonResponse(repositories.normal.response);
    if (path === "factory/repositories/1") return jsonResponse(repository.fresh_overlap.response);
    if (path === "factory/work-items") return jsonResponse({ counts, items: [], total: 5, has_more: false, next_cursor: null, generated_at: "x", filters: {}, schema_version: 1 });
    if (path === "agent-teams/presets/1/github-scopes") return jsonResponse({ scopes: [scope] });
    return jsonResponse({ detail: "unexpected" }, 404);
  });
}

describe("Repositories list", () => {
  it("is a compact table with the state in words, the reason and one way in", async () => {
    serve();
    renderRoute(<RepositoriesPage />, "/repositories", "/repositories");
    await settle();
    const table = await screen.findByRole("table", { name: "Repositories that Deck watches" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.length).toBe(repositories.normal.response.repositories.length);
    const paused = rows.find((row) => within(row).queryByText("fixture/paused"))!;
    expect(within(paused).getByText("Off")).toBeInTheDocument();
    expect(within(paused).getByText("Repository intake is paused.")).toBeInTheDocument();
    expect(within(paused).getByRole("link", { name: "Open fixture/paused" })).toHaveAttribute("href", "/repositories/3");
    expect(screen.queryByText(/scope \d+/i)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add a repository" })).toHaveAttribute("href", "/repositories/new");
  });

  it("names the branch from the team's scope read", async () => {
    serve();
    renderRoute(<RepositoriesPage />, "/repositories", "/repositories");
    await settle();
    expect(await screen.findAllByText("release/v3.1")).not.toHaveLength(0);
  });
});

function renderRepository(path = "/repositories/1") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/repositories" element={<p>Repositories list</p>} />
        <Route path="/repositories/:scopeId" element={<RepositoryPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Repository page", () => {
  it("is titled by the repository, with no scope number, and links to Work", async () => {
    serve();
    renderRepository();
    expect(await screen.findByRole("heading", { name: "fixture/shared" })).toBeInTheDocument();
    expect(screen.queryByText(/scope \d+/i)).not.toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(nav).getByRole("link", { name: "Repositories" })).toHaveAttribute("href", "/repositories");
    expect(screen.getByRole("link", { name: "Fixture team 1" })).toHaveAttribute("href", "/teams/1");
    await screen.findByText(/5 items · 2 active/);
    expect(screen.getByRole("link", { name: "View in Work ›" })).toHaveAttribute("href", "/work?scope_id=1");
    expect(screen.getByText(/Branch: release\/v3\.1/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows the settings with an Edit button for each part", async () => {
    serve();
    renderRepository();
    await screen.findByRole("heading", { name: "Labels and routing" });
    for (const name of [
      "Edit labels and routing for fixture/shared",
      "Edit merging and limits for fixture/shared",
      "Edit recovery policy for fixture/shared",
    ]) expect(screen.getByRole("button", { name })).toBeInTheDocument();
  });

  it("opens the edit dialog without asking for the Director key until Save", async () => {
    serve();
    const user = userEvent.setup();
    renderRepository();
    await user.click(await screen.findByRole("button", { name: "Edit labels and routing for fixture/shared" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Director key" })).not.toBeInTheDocument();
  });

  it("says plainly when the settings cannot be read, and keeps the rest", async () => {
    serve({ "agent-teams/presets/1/github-scopes": () => jsonResponse({ detail: "down" }, 500) });
    renderRepository();
    expect(await screen.findByRole("heading", { name: "fixture/shared" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/Settings could not be loaded/)).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "View in Work ›" })).toBeInTheDocument();
  });

  it("shows one plain message for a repository that does not exist", async () => {
    serve({ "factory/repositories/9": () => jsonResponse({ detail: "missing" }, 404) });
    renderRepository("/repositories/9");
    expect(await screen.findByRole("alert")).toHaveTextContent("This repository does not exist.");
    expect(screen.getByRole("heading", { name: "Repository" })).toBeInTheDocument();
  });
});
