import { StrictMode } from "react";
import { MemoryRouter, Routes, Route, useNavigate } from "react-router-dom";
import {
  act,
  render,
  cleanup,
  fireEvent,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkPage } from "../src/features/factory/pages/WorkPage";
import { RepositoryPage } from "../src/features/factory/pages/RepositoryPage";
import { OverviewPage } from "../src/features/factory/pages/OverviewPage";
import { WorkDetailPage } from "../src/features/factory/pages/WorkDetailPage";
import { ReadStatus } from "../src/features/factory/components/ReadStatus";
import {
  resetFactoryReads,
  useObservation,
  markWorkListsDirty,
} from "../src/features/factory/reads";
import {
  clearOperatorToken,
  getOperatorToken,
  setOperatorToken,
} from "../src/features/agent-teams/operatorAuth";
import {
  fixtureFetch,
  jsonResponse,
  renderRoute,
  settle,
  visibility,
} from "./helpers/factory";
import work from "./fixtures/factory/v1-p04/work-items.json";
import detail from "./fixtures/factory/v1-p04/work-item.json";
import overview from "./fixtures/factory/v1-p04/overview.json";
import repositories from "./fixtures/factory/v1-p04/repositories.json";

beforeEach(async () => {
  resetFactoryReads();
  clearOperatorToken();
  localStorage.clear();
  await visibility("visible");
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
const first = work.first_page.response;
const last = work.next_page.response;
function standard(path: string) {
  if (path === "factory/overview")
    return jsonResponse(overview.normal.response);
  if (path === "factory/repositories")
    return jsonResponse(repositories.last_page.response);
  if (path.startsWith("factory/work-items/"))
    return jsonResponse(detail.completed.response);
  return jsonResponse(first);
}

describe("delivery read authority and filters", () => {
  it("shares observations under StrictMode and pauses hidden polling", async () => {
    vi.useFakeTimers();
    function Observer() {
      const state = useObservation<{ generated_at: string }>(
        "factory/overview",
      );
      return <span>{state.data?.generated_at}</span>;
    }
    const { requests } = fixtureFetch(() =>
      jsonResponse(overview.normal.response),
    );
    renderRoute(
      <StrictMode>
        <Observer />
        <Observer />
      </StrictMode>,
    );
    await settle();
    expect(requests).toHaveLength(1);
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(requests).toHaveLength(2);
    await visibility("hidden");
    await act(async () => vi.advanceTimersByTimeAsync(10000));
    expect(requests).toHaveLength(2);
  });

  it("does not inherit native preferences and links complete-set counts with URL filters", async () => {
    localStorage.setItem("claude-deck:selected-provider", "pi-cli");
    localStorage.setItem("claude-deck:active-project", "/native/project");
    const { requests } = fixtureFetch((path) => standard(path));
    renderRoute(<OverviewPage />, "/?team_id=1", "/");
    await settle();
    expect(
      screen.getByText("132 matching work items across the complete set."),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: /Needs attention/ })[0],
    ).toHaveAttribute("href", "/work?team_id=1&category=attention");
    expect(
      requests.every(
        (r) =>
          r.method === "GET" &&
          !r.query.has("project_path") &&
          !r.query.has("provider"),
      ),
    ).toBe(true);
    expect(
      requests.some((r) =>
        /operations|native_surfaces|inbox|claim/.test(r.path),
      ),
    ).toBe(false);
  });
  it("ignores an old filter response after a filter change", async () => {
    let release!: (response: Response) => void;
    fixtureFetch((path, q) =>
      path === "factory/repositories"
        ? jsonResponse(repositories.normal.response)
        : q.get("team_id") === "1"
          ? new Promise((resolve) => {
              release = resolve;
            })
          : jsonResponse(last),
    );
    renderRoute(<WorkPage />, "/work?team_id=1");
    await settle();
    fireEvent.change(screen.getByLabelText("Team"), {
      target: { value: "2" },
    });
    await settle();
    expect(screen.getAllByText(/Fixture issue/).length).toBe(last.items.length);
    await act(async () => release(jsonResponse(first)));
    await settle();
    expect(
      screen.queryByText(first.items[0].item.issue_title, { exact: false }),
    ).not.toBeInTheDocument();
  });
  it("preserves last good observations after failure instead of showing an empty factory", async () => {
    vi.useFakeTimers();
    let fail = false;
    fixtureFetch(() =>
      fail
        ? jsonResponse(
            {
              detail: {
                code: "projection_failed",
                message: "Projection unavailable",
              },
            },
            500,
          )
        : jsonResponse(first),
    );
    renderRoute(<WorkPage />);
    await settle();
    fail = true;
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(screen.getByRole("alert")).toHaveTextContent("Stale data");
    expect(screen.getAllByText(/Fixture issue/)).toHaveLength(
      first.items.length,
    );
  });
  it("shows recovery-only/stopped observations without treating configuration as intake", async () => {
    fixtureFetch((path) =>
      path === "factory/overview"
        ? jsonResponse(overview.recovery_only.response)
        : standard(path),
    );
    renderRoute(<OverviewPage />, "/", "/");
    await settle();
    expect(
      screen.getByText(/Recovery-only mode blocks normal intake/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Intake: 0 eligible · 2 blocked/),
    ).toBeInTheDocument();
  });
  it("keeps configuration-only empty factories useful", async () => {
    const empty = structuredClone(overview.normal.response);
    Object.keys(empty.counts).forEach((k) => {
      empty.counts[k as keyof typeof empty.counts] = 0;
    });
    Object.keys(empty.automation)
      .filter((k) => k !== "runtime")
      .forEach((k) => {
        (empty.automation as unknown as Record<string, unknown>)[k] = 0;
      });
    fixtureFetch((path) =>
      path === "factory/overview"
        ? jsonResponse(empty)
        : path === "factory/repositories"
          ? jsonResponse({
              ...repositories.last_page.response,
              repositories: [],
              total: 0,
            })
          : jsonResponse({
              ...first,
              items: [],
              total: 0,
              has_more: false,
              next_cursor: null,
            }),
    );
    renderRoute(<OverviewPage />, "/", "/");
    await settle();
    expect(
      screen.getByRole("link", { name: "Open Harnesses and configuration" }),
    ).toHaveAttribute("href", "/harnesses");
    expect(
      screen.getByRole("link", { name: "Open live sessions" }),
    ).toBeInTheDocument();
  });
});

describe("cursor browsing V26/V27", () => {
  it("clears older-page browsing on a filter change, including return to a previous URL", async () => {
    fixtureFetch((path, query) =>
      path === "factory/repositories"
        ? jsonResponse(repositories.normal.response)
        : jsonResponse(query.has("cursor") ? work.next_page.response : first),
    );
    renderRoute(<WorkPage />, "/work?team_id=1");
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await settle();
    expect(screen.getByText(/Live updates paused/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Team"), {
      target: { value: "2" },
    });
    await settle();
    fireEvent.change(screen.getByLabelText("Team"), {
      target: { value: "1" },
    });
    await settle();
    expect(screen.queryByText(/Live updates paused/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/Fixture issue/)).toHaveLength(2);
  });
  it("retains >100 paused rows, dirty state, return focus/scroll through real list/detail/action/Back routes", async () => {
    vi.useFakeTimers();
    const eligible = detail.operator_stop_retry_eligible.response;
    const rows = Array.from({ length: 132 }, (_, i) => ({
      ...structuredClone(first.items[i % first.items.length]),
      item: {
        ...first.items[0].item,
        id: 1000 + i,
        issue_title: `Navigation issue ${i}`,
      },
    }));
    rows[131].item.id = eligible.work_item.item.id;
    const { requests } = fixtureFetch((path, query) => {
      if (path.endsWith("/retry")) return jsonResponse(eligible.work_item.item);
      if (path.startsWith("factory/work-items/")) return jsonResponse(eligible);
      const cursor = query.get("cursor"),
        start = cursor === "second" ? 50 : cursor === "third" ? 100 : 0;
      return jsonResponse({
        ...first,
        items: rows.slice(start, start + 50),
        has_more: start !== 100,
        next_cursor: start === 0 ? "second" : start === 50 ? "third" : null,
      });
    });
    function Back() {
      const navigate = useNavigate();
      return <button onClick={() => navigate(-1)}>Browser Back</button>;
    }
    render(
      <MemoryRouter initialEntries={["/work?team_id=1"]}>
        <Back />
        <main>
          <Routes>
            <Route path="/work" element={<WorkPage />} />
            <Route path="/work/:workItemId" element={<WorkDetailPage />} />
          </Routes>
        </main>
      </MemoryRouter>,
    );
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await settle();
    expect(screen.getAllByText(/Navigation issue/)).toHaveLength(132);
    const main = document.querySelector("main")!,
      table = main.querySelector<HTMLElement>("[data-work-table]")!;
    main.scrollTop = 730;
    table.scrollLeft = 210;
    const link = screen.getByRole("link", { name: /Navigation issue 131/ });
    link.focus();
    fireEvent.click(link);
    await settle();
    expect(
      screen.queryByRole("button", { name: "No more results" }),
    ).not.toBeInTheDocument();
    main.scrollTop = 0;
    const listReads = requests.filter(
      (r) => r.path === "factory/work-items",
    ).length;
    setOperatorToken("synthetic-test-operator");
    fireEvent.click(screen.getByRole("button", { name: "Retry issue" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm retry" }));
    await settle();
    await act(async () => vi.advanceTimersByTimeAsync(15000));
    await visibility("hidden");
    await visibility("visible");
    fireEvent.click(screen.getByRole("button", { name: "Browser Back" }));
    await settle();
    expect(screen.getAllByText(/Navigation issue/)).toHaveLength(132);
    expect(
      screen.getByText(/detail changed; refresh needed/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "No more results" }),
    ).toHaveAttribute("aria-disabled", "true");
    expect(main.scrollTop).toBe(730);
    expect(
      main.querySelector<HTMLElement>("[data-work-table]")!.scrollLeft,
    ).toBe(210);
    expect(
      screen.getByRole("link", { name: /Navigation issue 131/ }),
    ).toHaveFocus();
    await act(async () => vi.advanceTimersByTimeAsync(15000));
    expect(
      requests.filter((r) => r.path === "factory/work-items"),
    ).toHaveLength(listReads);
    expect(requests.filter((r) => r.method === "POST")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Refresh from start" }));
    await settle();
    expect(screen.getAllByText(/Navigation issue/)).toHaveLength(50);
    expect(screen.queryByText(/Live updates paused/)).not.toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(
      requests.filter((r) => r.path === "factory/work-items").length,
    ).toBeGreaterThan(listReads);
  });

  it("preserves >100 derived rows, focus and scroll after old responses, polling, final page, visibility and detail actions", async () => {
    vi.useFakeTimers();
    // Explicit P02 derivation: duplicate accepted row structure with distinct safe IDs/titles.
    const rows = Array.from({ length: 132 }, (_, i) => ({
      ...structuredClone(first.items[i % first.items.length]),
      item: {
        ...first.items[0].item,
        id: 1000 + i,
        issue_title: `Derived issue ${i}`,
      },
    }));
    let old!: (response: Response) => void;
    let firstReads = 0;
    const { requests } = fixtureFetch((path, query) => {
      if (path === "factory/repositories")
        return jsonResponse(repositories.normal.response);
      const cursor = query.get("cursor");
      if (!cursor && ++firstReads === 2)
        return new Promise((resolve) => {
          old = resolve;
        });
      const start = cursor === "second" ? 50 : cursor === "third" ? 100 : 0;
      return jsonResponse({
        ...first,
        items: rows.slice(start, start + 50),
        next_cursor: start === 0 ? "second" : start === 50 ? "third" : null,
        has_more: start !== 100,
      });
    });
    const { container } = renderRoute(<WorkPage />);
    await settle();
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    const load = screen.getByRole("button", { name: "Load more" });
    load.focus();
    container.scrollTop = 91;
    fireEvent.click(load);
    await settle();
    expect(screen.getAllByText(/Derived issue/)).toHaveLength(100);
    await act(async () => old(jsonResponse({ ...first, items: [], total: 0 })));
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await settle();
    expect(screen.getAllByText(/Derived issue/)).toHaveLength(132);
    const reads = requests.length;
    await act(async () => vi.advanceTimersByTimeAsync(20000));
    await visibility("hidden");
    await visibility("visible");
    await act(async () => markWorkListsDirty());
    await settle();
    expect(requests).toHaveLength(reads);
    expect(
      screen.getByText(/detail changed; refresh needed/),
    ).toBeInTheDocument();
    expect(container.scrollTop).toBe(91);
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "No more results" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Refresh from start" }));
    await settle();
    expect(screen.getAllByText(/Derived issue/)).toHaveLength(50);
    expect(screen.queryByText(/Live updates paused/)).not.toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(requests.length).toBeGreaterThan(reads);
  });
});

describe("work details and protected controls", () => {
  it("does not prompt for safe detail, distinguishes completed and preserves offline actor slot links", async () => {
    const { requests } = fixtureFetch((path) => standard(path));
    renderRoute(<WorkDetailPage />, "/work/9", "/work/:workItemId");
    await settle();
    expect(
      screen.getByText(/delivery and human review are unconfirmed/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Review launch for Leader" }),
    ).toHaveAttribute("href", "/teams/1?slot_id=1&review_launch=1");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(requests).toHaveLength(1);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Inspect protected revision history",
      }),
    );
    await settle();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(requests).toHaveLength(1);
  });
  it("uses the existing operator header, preserves denial and refreshes detail without browser agent approval", async () => {
    const eligible = structuredClone(detail.escalated.response);
    eligible.work_item.actions[0].state = "eligible";
    const { requests } = fixtureFetch((path, _query, options) =>
      path.endsWith("/retry")
        ? options?.headers &&
          new Headers(options.headers).get("X-Deck-Operator-Token") ===
            "test-operator"
          ? jsonResponse(
              {
                detail: {
                  block_code: "state_changed",
                  message: "Current eligibility changed",
                },
              },
              409,
            )
          : jsonResponse({}, 401)
        : jsonResponse(eligible),
    );
    renderRoute(<WorkDetailPage />, "/work/6", "/work/:workItemId");
    await settle();
    expect(
      screen.queryByRole("button", { name: /Approve/ }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry issue" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm retry" }));
    await settle();
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Operator token"), {
      target: { value: "test-operator" },
    });
    fireEvent.submit(
      within(dialog)
        .getByRole("button", { name: "Authorize retry" })
        .closest("form")!,
    );
    await settle();
    expect(screen.getAllByRole("alert")[0]).toHaveTextContent(
      "Current eligibility changed",
    );
    expect(requests.filter((r) => r.method === "POST")).toHaveLength(1);
    expect(requests.filter((r) => r.path.startsWith("factory/"))).toHaveLength(
      2,
    );
  });
  it.each([false, true])("cancel leaves retry untouched with cached credential=%s", async (cached) => {
    const eligible = detail.operator_stop_retry_eligible.response;
    const { requests } = fixtureFetch(() => jsonResponse(eligible));
    if (cached) setOperatorToken("synthetic-operator");
    renderRoute(<WorkDetailPage />, "/work/6", "/work/:workItemId");
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Retry issue" }));
    const warning = screen.getByRole("alertdialog");
    expect(within(warning).getByText(/discard prior PR, handoff, and attempt markers/)).toBeInTheDocument();
    expect(within(warning).getByText(/until the current owner releases it/)).toBeInTheDocument();
    expect(requests.filter((r) => r.method === "POST")).toHaveLength(0);
    expect(screen.queryByLabelText("Operator token")).not.toBeInTheDocument();
    fireEvent.click(within(warning).getByRole("button", { name: "Cancel" }));
    await settle();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Operator token")).not.toBeInTheDocument();
    expect(requests).toHaveLength(1);
  });

  it.each(["deferred", "pending", "retained"])("confirms cached retry once and reports %s without claiming dispatch", async (status) => {
    const eligible = detail.operator_stop_retry_eligible.response;
    // Explicit P02 derivation of the legacy retry response, not a new P01 fixture.
    const response = { ...eligible.work_item.item,
      dispatch_status: status === "pending" ? "pending" : "escalated",
      retry_requested_at: status === "deferred" ? "2026-09-30T12:01:00Z" : null,
      status_note: status === "deferred" ? "Waiting for current owner release." : null,
    };
    const credentials: (string | null)[] = [];
    const { requests } = fixtureFetch((path, _query, options) => {
      if (!path.endsWith("/retry")) return jsonResponse(eligible);
      credentials.push(new Headers(options?.headers).get("X-Deck-Operator-Token"));
      return jsonResponse(response);
    });
    setOperatorToken("synthetic-operator");
    renderRoute(<WorkDetailPage />, "/work/6", "/work/:workItemId");
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Retry issue" }));
    expect(requests.filter((r) => r.method === "POST")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Confirm retry" }));
    await settle();
    expect(requests.filter((r) => r.method === "POST")).toHaveLength(1);
    expect(credentials).toEqual(["synthetic-operator"]);
    expect(requests.filter((r) => r.path.startsWith("factory/"))).toHaveLength(2);
    const message = screen.getByRole("status");
    expect(message).toHaveTextContent(status === "deferred" ? "re-dispatch is deferred" : "A new dispatch has not been observed");
    if (status === "pending") expect(message).toHaveTextContent("reset this work item to pending");
    if (status === "retained") expect(message).toHaveTextContent("Retry response status: escalated");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Operator token")).not.toBeInTheDocument();
  });

  it("requires a fresh confirmation after 401 before using a replacement credential", async () => {
    const eligible = detail.operator_stop_retry_eligible.response;
    let posts = 0;
    const credentials: (string | null)[] = [];
    const { requests } = fixtureFetch((path, _query, options) => {
      if (!path.endsWith("/retry")) return jsonResponse(eligible);
      credentials.push(new Headers(options?.headers).get("X-Deck-Operator-Token"));
      return ++posts === 1 ? jsonResponse({ detail: "Expired authorization" }, 401)
        : jsonResponse({ ...eligible.work_item.item, dispatch_status: "pending" });
    });
    setOperatorToken("synthetic-expired");
    renderRoute(<WorkDetailPage />, "/work/6", "/work/:workItemId");
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Retry issue" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm retry" }));
    await settle();
    const auth = screen.getByRole("dialog");
    fireEvent.change(within(auth).getByLabelText("Operator token"), { target: { value: "synthetic-replacement" } });
    fireEvent.click(within(auth).getByRole("button", { name: "Authorize retry" }));
    await settle();
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(posts).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await settle();
    expect(posts).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Retry issue" }));
    expect(posts).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Confirm retry" }));
    await settle();
    expect(requests.filter((r) => r.method === "POST")).toHaveLength(2);
    expect(credentials).toEqual(["synthetic-expired", "synthetic-replacement"]);
  });

  it("drops pending retry authorization when navigating to another work item", async () => {
    const eligible = detail.operator_stop_retry_eligible.response;
    const { requests } = fixtureFetch((path) => jsonResponse(path.endsWith("/9") ? detail.completed.response : eligible));
    let navigateAway!: () => void;
    function Navigate() {
      const navigate = useNavigate();
      navigateAway = () => navigate("/work/9");
      return null;
    }
    render(<MemoryRouter initialEntries={["/work/6"]}><Navigate /><Routes>
      <Route path="/work/:workItemId" element={<WorkDetailPage />} />
    </Routes></MemoryRouter>);
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Retry issue" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm retry" }));
    await settle();
    expect(screen.getByLabelText("Operator token")).toBeInTheDocument();
    // Browser history navigation remains possible while modal focus is trapped.
    await act(async () => navigateAway());
    await settle();
    expect(screen.queryByLabelText("Operator token")).not.toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(requests.filter((r) => r.method === "POST")).toHaveLength(0);
  });

  it("ignores an old retry 401 after navigating and preserves the new context credential", async () => {
    const eligible = detail.operator_stop_retry_eligible.response;
    let finish!: (value: Response) => void;
    const { requests } = fixtureFetch((path) => path.endsWith("/retry")
      ? new Promise<Response>((resolve) => { finish = resolve; })
      : jsonResponse(path.endsWith("/9") ? detail.completed.response : eligible));
    function Navigate() {
      const navigate = useNavigate();
      return <button onClick={() => navigate("/work/9")}>Other work</button>;
    }
    setOperatorToken("synthetic-old");
    render(<MemoryRouter initialEntries={["/work/6"]}><Navigate /><Routes>
      <Route path="/work/:workItemId" element={<WorkDetailPage />} />
    </Routes></MemoryRouter>);
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Retry issue" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm retry" }));
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Other work" }));
    await settle();
    setOperatorToken("synthetic-new-context");
    await act(async () => finish(jsonResponse({ detail: "Old denial" }, 401)));
    await settle();
    expect(getOperatorToken()).toBe("synthetic-new-context");
    expect(screen.queryByLabelText("Operator token")).not.toBeInTheDocument();
    expect(screen.queryByText("Old denial")).not.toBeInTheDocument();
    expect(requests.filter((r) => r.path === "factory/work-items/6")).toHaveLength(1);
    expect(requests.filter((r) => r.method === "POST")).toHaveLength(1);
  });

});

describe("polling after errors", () => {
  const unprocessable = () =>
    jsonResponse({ detail: { code: "invalid_id", message: "Bad ID." } }, 422);
  const steps = async (ms: number) =>
    act(async () => vi.advanceTimersByTimeAsync(ms));

  it("stops an observation after a 422 and keeps a link back", async () => {
    vi.useFakeTimers();
    const { requests } = fixtureFetch(unprocessable);
    renderRoute(<RepositoryPage />, "/repositories/abc", "/repositories/:scopeId");
    await settle();
    expect(screen.getByRole("alert")).toHaveTextContent("Bad ID. (invalid_id)");
    expect(screen.getByRole("link", { name: "Back to Repositories" })).toHaveAttribute(
      "href",
      "/repositories",
    );
    expect(screen.queryByText("Retrying…")).not.toBeInTheDocument();
    await steps(120000);
    await visibility("hidden");
    await visibility("visible");
    await steps(120000);
    expect(requests).toHaveLength(1);
  });

  it("stops after a 404 or a 401 and sends no further request", async () => {
    vi.useFakeTimers();
    const { requests } = fixtureFetch(() =>
      jsonResponse({ detail: "Work item not found" }, 404),
    );
    renderRoute(<WorkDetailPage />, "/work/9", "/work/:workItemId");
    await settle();
    expect(screen.getByRole("link", { name: "Back to Work" })).toBeInTheDocument();
    await steps(120000);
    expect(requests).toHaveLength(1);
    cleanup();
    resetFactoryReads();
    const denied = fixtureFetch(() => jsonResponse({ detail: "Denied" }, 401));
    renderRoute(<OverviewPage />, "/", "/");
    await settle();
    await steps(120000);
    expect(denied.requests).toHaveLength(1);
  });

  it("stops a list after a 422", async () => {
    vi.useFakeTimers();
    const { requests } = fixtureFetch(unprocessable);
    renderRoute(<WorkPage />, "/work?team_id=bad");
    await settle();
    await steps(120000);
    expect(requests).toHaveLength(1);
  });

  it("resumes after a manual refresh that succeeds", async () => {
    vi.useFakeTimers();
    let broken = true;
    const { requests } = fixtureFetch((path) =>
      broken ? unprocessable() : standard(path),
    );
    renderRoute(<OverviewPage />, "/", "/");
    await settle();
    await steps(60000);
    expect(requests).toHaveLength(1);
    broken = false;
    fireEvent.click(screen.getByRole("button", { name: "Refresh observation" }));
    await settle();
    const reads = requests.length;
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await steps(5000);
    expect(requests.length).toBeGreaterThan(reads);
  });

  it("backs off 5, 10, 30 and 60 seconds after a transient error, then resets", async () => {
    vi.useFakeTimers();
    let broken = true;
    const { requests } = fixtureFetch((path) =>
      broken ? jsonResponse({ detail: "Unavailable" }, 503) : standard(path),
    );
    function Observer() {
      const state = useObservation<unknown>("factory/overview");
      return <ReadStatus state={state} />;
    }
    renderRoute(<Observer />);
    await settle();
    expect(screen.getByText("Retrying…")).toBeInTheDocument();
    for (const [wait, total] of [
      [5000, 2],
      [10000, 3],
      [30000, 4],
      [60000, 5],
      [60000, 6],
    ]) {
      await steps(wait - 1);
      expect(requests).toHaveLength(total - 1);
      await steps(1);
      expect(requests).toHaveLength(total);
    }
    broken = false;
    await steps(60000);
    expect(requests).toHaveLength(7);
    expect(screen.queryByText("Retrying…")).not.toBeInTheDocument();
    await steps(5000);
    expect(requests).toHaveLength(8);
  });
});

describe("name filters", () => {
  const withNames = (path: string, query: URLSearchParams) =>
    path === "factory/repositories" && query.get("limit") === "100"
      ? jsonResponse(repositories.normal.response)
      : path === "factory/overview"
        ? jsonResponse(overview.normal.response)
        : jsonResponse(first);
  const sent = (requests: { query: URLSearchParams }[], key: string) =>
    requests.map((r) => r.query.get(key)).filter((v) => v !== null);

  it("filters by team and repository name, with no ID inputs", async () => {
    const { requests } = fixtureFetch(withNames);
    renderRoute(<WorkPage />, "/work");
    await settle();
    expect(screen.queryByLabelText(/ID/)).not.toBeInTheDocument();
    const team = screen.getByLabelText("Team") as HTMLSelectElement;
    expect([...team.options].map((o) => o.text)).toEqual([
      "All teams",
      "Fixture team 1",
      "Fixture team 2",
    ]);
    const repository = screen.getByLabelText("Repository") as HTMLSelectElement;
    // One repository name in two scopes also shows the team.
    expect([...repository.options].map((o) => o.text)).toEqual([
      "All repositories",
      "fixture/paused",
      "fixture/shared · Fixture team 1",
      "fixture/shared · Fixture team 2",
    ]);
    fireEvent.change(team, { target: { value: "2" } });
    await settle();
    fireEvent.change(repository, { target: { value: "3" } });
    await settle();
    expect(sent(requests, "team_id")).toContain("2");
    expect(sent(requests, "scope_id")).toContain("3");
  });

  it("hides a select that has one option, and shows Reset only while a filter is active", async () => {
    fixtureFetch((path, query) =>
      path === "factory/repositories" && query.get("limit") === "100"
        ? jsonResponse(repositories.last_page.response)
        : jsonResponse(first),
    );
    renderRoute(<WorkPage />, "/work");
    await settle();
    expect(screen.queryByLabelText("Team")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Repository")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Reset filters" })).not.toBeInTheDocument();
    cleanup();
    renderRoute(<WorkPage />, "/work?provider=codex-cli");
    await settle();
    expect(screen.getByRole("link", { name: "Reset filters" })).toHaveAttribute("href", "/work");
  });

  for (const value of ["abc", "999", "0", "1e3"]) {
    for (const key of ["team_id", "scope_id"]) {
      it(`keeps the page and sends nothing for an unknown ${key}=${value}`, async () => {
        const { requests } = fixtureFetch(withNames);
        renderRoute(<WorkPage />, `/work?${key}=${value}`);
        await settle();
        expect(screen.getByRole("status")).toHaveTextContent("was not found");
        expect(screen.getAllByRole("link", { name: "Reset filters" })).toHaveLength(1);
        expect(screen.getAllByText(/Fixture issue/).length).toBeGreaterThan(0);
        expect(sent(requests, key)).toEqual([]);
        cleanup();
        resetFactoryReads();
        const overviewReads = fixtureFetch(withNames);
        renderRoute(<OverviewPage />, `/?${key}=${value}`, "/");
        await settle();
        expect(screen.getByRole("status")).toHaveTextContent("was not found");
        expect(screen.getByText(/matching work items/)).toBeInTheDocument();
        expect(sent(overviewReads.requests, key)).toEqual([]);
      });
    }
  }

  it("holds a numeric filter until the names are known", async () => {
    let release!: (response: Response) => void;
    const { requests } = fixtureFetch((path, query) =>
      path === "factory/repositories" && query.get("limit") === "100"
        ? new Promise((resolve) => {
            release = resolve;
          })
        : jsonResponse(first),
    );
    renderRoute(<WorkPage />, "/work?team_id=999");
    await settle();
    expect(requests).toHaveLength(0);
    await act(async () => release(jsonResponse(repositories.normal.response)));
    await settle();
    expect(sent(requests, "team_id")).toEqual([]);
    expect(requests.length).toBeGreaterThan(0);
  });

  it("sends a valid-looking value when the names cannot be read, and still drops text", async () => {
    const { requests } = fixtureFetch((path, query) =>
      path === "factory/repositories" && query.get("limit") === "100"
        ? jsonResponse({ detail: "Unavailable" }, 500)
        : jsonResponse(first),
    );
    renderRoute(<WorkPage />, "/work?team_id=1&scope_id=abc");
    await settle();
    expect(sent(requests, "team_id")).toContain("1");
    expect(sent(requests, "scope_id")).toEqual([]);
  });
});
