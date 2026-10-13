import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { AuditMetricsPage } from "../src/features/factory/AuditMetricsPanel";
import { NeedsALookPanel } from "../src/features/factory/NeedsALookPanel";
import { groupRefusals } from "../src/features/factory/auditRefusals";
import type { AuditEventRead } from "../src/features/factory/auditApi";
import { clearOperatorToken, setOperatorToken } from "../src/features/agent-teams/operatorAuth";

const realFetch = globalThis.fetch;

function refusal(id: number, code: string, hoursAgo: number, overrides: Partial<AuditEventRead> = {}): AuditEventRead {
  const at = new Date(Date.now() - hoursAgo * 3600 * 1000).toISOString();
  return {
    id, occurred_at: at, recorded_at: at, event_kind: "continuation_request", source: "test", record_kind: "observation",
    actor_kind: "member", actor_reference: "member:2", item_id: 7, item_context_key: "item-7",
    context_snapshot: { repo_name: "claude-deck-website", issue_number: 2 },
    sanitized_reason: code, action_outcome: "rejected", live_links_available: true, ...overrides,
  };
}

const EVENTS = [
  refusal(1, "allowed_paths_invalid", 3),
  refusal(2, "allowed_paths_invalid", 4),
  refusal(3, "allowed_paths_invalid", 5),
  refusal(4, "continuation_failed_head_limit_exceeded", 6),
  refusal(5, "continuation_not_escalated", 2, { actor_reference: "member:3", item_id: 9, item_context_key: "item-9",
    context_snapshot: { repo_name: "claude-deck", issue_number: 492 } }),
  refusal(6, "never_seen_code", 1, { actor_reference: "member:3", item_id: 9, item_context_key: "item-9",
    context_snapshot: { repo_name: "claude-deck", issue_number: 492 } }),
];

const NAMES = { 2: "R3 website implementer", 3: "R2 release implementer" };

function renderPanel(props: Partial<React.ComponentProps<typeof NeedsALookPanel>> = {}) {
  const onShowEvents = vi.fn();
  render(
    <MemoryRouter>
      <NeedsALookPanel state="ready" groups={groupRefusals(EVENTS, Date.now() - 7 * 24 * 3600 * 1000)} names={NAMES}
        truncated={false} onShowEvents={onShowEvents} onUnlock={vi.fn()} {...props} />
    </MemoryRouter>,
  );
  return { onShowEvents };
}

describe("NeedsALookPanel", () => {
  it("shows each group with the member, the item, counts and plain reasons", () => {
    renderPanel();
    const panel = screen.getByRole("region", { name: /Needs a look/ });
    expect(within(panel).getByText(/4 requests from R3 website implementer were refused on claude-deck-website #2/)).toBeInTheDocument();
    expect(within(panel).getByText(/2 requests from R2 release implementer were refused on claude-deck #492/)).toBeInTheDocument();
    expect(within(panel).getByText(/3× The plan's file paths are not valid\./)).toBeInTheDocument();
    expect(within(panel).getByText(/1× Too many failed attempts for this plan\./)).toBeInTheDocument();
    expect(within(panel).getByText(/1× The reason is not known to this page\./)).toBeInTheDocument();
    expect(panel.textContent).not.toMatch(/allowed_paths_invalid|never_seen_code|continuation_[a-z_]+/);
  });

  it("says that a refusal repeated three times often means a factory defect", () => {
    renderPanel();
    const warnings = screen.getAllByText(/often means a factory defect, not an agent mistake/);
    expect(warnings).toHaveLength(1);
  });

  it("links to the item and asks for the filtered events", () => {
    const { onShowEvents } = renderPanel();
    expect(screen.getByRole("link", { name: "Open claude-deck-website #2" })).toHaveAttribute("href", "/work/7");
    fireEvent.click(screen.getAllByRole("button", { name: "Show events" })[0]);
    expect(onShowEvents).toHaveBeenCalledWith(expect.objectContaining({ itemContextKey: expect.stringMatching(/^item-/) }));
  });

  it("names a member by id when the name is missing", () => {
    renderPanel({ names: {} });
    expect(screen.getByText(/4 requests from member 2 were refused/)).toBeInTheDocument();
  });

  it("shows the empty sentence, the locked state with Unlock, and the page cap", () => {
    const { unmount } = render(<NeedsALookPanel state="ready" groups={[]} names={{}} truncated={false} onShowEvents={vi.fn()} onUnlock={vi.fn()} />);
    expect(screen.getByText("Nothing needs a look in this window.")).toBeInTheDocument();
    unmount();
    const onUnlock = vi.fn();
    const locked = render(<NeedsALookPanel state="locked" groups={[]} names={{}} truncated={false} onShowEvents={vi.fn()} onUnlock={onUnlock} />);
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    expect(onUnlock).toHaveBeenCalled();
    locked.unmount();
    render(<NeedsALookPanel state="ready" groups={[]} names={{}} truncated onShowEvents={vi.fn()} onUnlock={vi.fn()} />);
    expect(screen.getByText(/Older refusals in this window are not counted/)).toBeInTheDocument();
  });
});

describe("Audit page with the Needs a look panel", () => {
  beforeEach(() => setOperatorToken("synthetic-director-key"));
  afterEach(() => {
    globalThis.fetch = realFetch;
    clearOperatorToken();
    vi.restoreAllMocks();
  });

  function stubServer() {
    const urls: URL[] = [];
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://fixture.test");
      urls.push(url);
      if (url.pathname.endsWith("/factory/metrics")) {
        return json({ window_start: "s", window_end: "e", filter_scope: "all", counting_unit_note: "n", missing_intervals: [], metrics: [] });
      }
      if (url.pathname.endsWith("/factory/audit-events")) {
        const refusals = url.searchParams.get("event_kind") === "continuation_request" && !url.searchParams.has("item_context_key");
        const items = refusals ? EVENTS : [];
        return json({ items, total: items.length, page: 1, page_size: Number(url.searchParams.get("page_size")), snapshot_labels: [] });
      }
      if (url.pathname.endsWith("/agent-mail/team")) {
        return json({ members: [{ id: 2, display_name: "R3 website implementer" }, { id: 3, display_name: "R2 release implementer" }] });
      }
      return new Response("{}", { status: 404 });
    }) as unknown as typeof fetch;
    return urls;
  }

  it("reads the refusals with the stored key and shows the groups with member names", async () => {
    const urls = stubServer();
    render(<MemoryRouter><AuditMetricsPage /></MemoryRouter>);
    expect(await screen.findByText(/4 requests from R3 website implementer were refused on claude-deck-website #2/)).toBeInTheDocument();
    expect(screen.getByText(/2 requests from R2 release implementer were refused on claude-deck #492/)).toBeInTheDocument();
    const refusalReads = urls.filter((url) => url.searchParams.get("event_kind") === "continuation_request");
    expect(refusalReads).toHaveLength(1);
    expect(refusalReads[0].searchParams.get("page_size")).toBe("100");
  });

  it("filters the events table by the item when Show events is chosen, and can clear it", async () => {
    const urls = stubServer();
    render(<MemoryRouter><AuditMetricsPage /></MemoryRouter>);
    await screen.findByText(/4 requests from R3 website implementer/);
    fireEvent.click(screen.getAllByRole("button", { name: "Show events" })[0]);
    expect(await screen.findByText(/Showing refused requests for .* only\./)).toBeInTheDocument();
    await waitFor(() => expect(urls.some((url) => url.searchParams.has("item_context_key"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Show all events" }));
    await waitFor(() => expect(screen.queryByText(/Showing refused requests for/)).not.toBeInTheDocument());
  });
});
