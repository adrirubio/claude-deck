import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OverviewPage } from "../src/features/factory/pages/OverviewPage";
import { RepositoryPage } from "../src/features/factory/pages/RepositoryPage";
import { WorkDetailPage } from "../src/features/factory/pages/WorkDetailPage";
import { WorkPage } from "../src/features/factory/pages/WorkPage";
import { resetFactoryReads } from "../src/features/factory/reads";
import { waitingActorLabel } from "../src/features/factory/waitingActor";
import { fixtureFetch, jsonResponse, renderRoute, settle } from "./helpers/factory";
import work from "./fixtures/factory/v1-p04/work-items.json";
import detail from "./fixtures/factory/v1-p04/work-item.json";
import overview from "./fixtures/factory/v1-p04/overview.json";
import repositories from "./fixtures/factory/v1-p04/repositories.json";

// #513: the Director-facing pages use plain words. Visible text on Overview,
// Work, a work item and Repositories has no "observation", "scope ID" or
// "backend instance", and calls the human role Director.

vi.mock("../src/features/agent-teams/WorkPublicationPanel", () => ({ WorkPublicationPanel: () => null }));

beforeEach(() => resetFactoryReads());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const FORBIDDEN = [/observation/i, /scope ID/i, /backend instance/i, /\boperator\b/i];

function expectPlain(container: HTMLElement, page: string) {
  // Open every disclosure so hidden text counts too.
  container.querySelectorAll("details").forEach((element) => { element.open = true; });
  const text = container.textContent ?? "";
  for (const pattern of FORBIDDEN) expect(text, `${page} must not match ${pattern}`).not.toMatch(pattern);
}

function serve() {
  return fixtureFetch((path) => {
    if (path === "factory/overview") return jsonResponse(overview.recovery_only.response);
    if (path === "factory/repositories") return jsonResponse(repositories.last_page.response);
    if (path.startsWith("factory/work-items/")) return jsonResponse(detail.completed.response);
    if (path.startsWith("factory/work-items")) return jsonResponse(work.first_page.response);
    if (path === "agent-teams/presets") return jsonResponse({ presets: [] });
    return jsonResponse({ rows: [], items: [], repositories: [], total: 0, has_more: false });
  });
}

describe("Director copy", () => {
  it("names the Director for the waiting actor and keeps other actors", () => {
    expect(waitingActorLabel("operator")).toBe("Director");
    expect(waitingActorLabel("leader")).toBe("Leader");
    expect(waitingActorLabel("owner")).toBe("owner");
  });

  it("Overview, with the automation details open, uses plain words", async () => {
    serve();
    const { container } = renderRoute(<OverviewPage />, "/", "/");
    await settle();
    await settle();
    expect(container.textContent).toContain("Overview");
    expectPlain(container, "Overview");
  });

  it("Work uses plain words", async () => {
    serve();
    const { container } = renderRoute(<WorkPage />);
    await settle();
    await settle();
    expect(container.textContent).toContain("Fixture issue");
    expectPlain(container, "Work");
  });

  it("a work item uses plain words", async () => {
    serve();
    const { container } = renderRoute(<WorkDetailPage />, "/work/9", "/work/:workItemId");
    await settle();
    await settle();
    expectPlain(container, "Work item");
  });

  it("a repository uses plain words", async () => {
    serve();
    const { container } = renderRoute(<RepositoryPage />, "/repositories/1", "/repositories/:id");
    await settle();
    await settle();
    expectPlain(container, "Repository");
  });
});
