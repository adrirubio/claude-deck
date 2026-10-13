import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { ConversationsTab } from "../src/features/agent-mail/ConversationsTab";
import { buildConversations } from "../src/features/agent-mail/conversations";
import { ThreadDialog } from "../src/features/agent-mail/ThreadDialog";
import { LEGACY_SENDER_LABEL, senderKind, senderName } from "../src/features/agent-mail/utils";
import type { MailMemberResponse, MailMessageResponse } from "../src/types/agentMail";

vi.mock("../src/features/agent-mail/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/features/agent-mail/api")>();
  return { ...actual, fetchAgentMailThread: vi.fn() };
});
import { fetchAgentMailThread } from "../src/features/agent-mail/api";

const MEMBERS = [
  { id: 2, display_name: "B1 Backend" },
  { id: 3, display_name: "L1 Leader" },
] as MailMemberResponse[];

function message(id: number, overrides: Partial<MailMessageResponse>): MailMessageResponse {
  return {
    id, kind: "message", sender_name: "", recipient_member_id: 2, subject: `Subject ${id}`,
    body_markdown: `Body ${id}`, is_stale: false, created_at: "2026-10-13T08:00:00Z", ...overrides,
  } as MailMessageResponse;
}

const BY_TYPE = {
  deck: message(1, { sender_type: "system", sender_name: "Deck" }),
  director: message(2, { sender_type: "director", sender_name: "Director" }),
  agent: message(3, { sender_type: "member", sender_member_id: 3, sender_name: "L1 Leader" }),
  legacy: message(4, { sender_type: "legacy", sender_name: LEGACY_SENDER_LABEL }),
  external: message(5, { sender_type: "external_actor", sender_actor_kind: "external_tool", sender_name: "Supervisor (v3.1)" }),
  unknown: message(6, { sender_type: undefined, sender_name: "Director" }),
};

describe("senderName and senderKind", () => {
  it("reads the label only from sender_type and sender_name", () => {
    expect(senderName(BY_TYPE.deck, MEMBERS)).toBe("Deck");
    expect(senderName(BY_TYPE.director, MEMBERS)).toBe("Director");
    expect(senderName(BY_TYPE.agent, MEMBERS)).toBe("L1 Leader");
    expect(senderName(BY_TYPE.legacy, MEMBERS)).toBe(LEGACY_SENDER_LABEL);
    expect(senderName(BY_TYPE.external, MEMBERS)).toBe("Supervisor (v3.1)");
    expect([BY_TYPE.deck, BY_TYPE.director, BY_TYPE.agent, BY_TYPE.legacy, BY_TYPE.external, BY_TYPE.unknown].map(senderKind))
      .toEqual(["deck", "director", "agent", "legacy", "external", "unknown"]);
  });

  it("shows Deck for a service message even when the name says Director", () => {
    expect(senderName(message(7, { sender_type: "system", sender_name: "Director" }), MEMBERS)).toBe("Deck");
  });

  it("never shows Director for an unknown sender", () => {
    expect(senderName(BY_TYPE.unknown, MEMBERS)).toBe("Unknown sender");
    expect(senderName(message(8, { sender_type: "future_type", sender_name: "Director" }), MEMBERS)).toBe("Unknown sender");
  });

  it("falls back for a legacy or external sender with no name, and an agent with no member", () => {
    expect(senderName(message(9, { sender_type: "legacy" }), MEMBERS)).toBe(LEGACY_SENDER_LABEL);
    expect(senderName(message(10, { sender_type: "external_actor" }), MEMBERS)).toBe("External actor");
    expect(senderName(message(11, { sender_type: "member" }), MEMBERS)).toBe("Unknown sender");
    expect(senderName(message(12, { sender_type: "member", sender_member_id: 99 }), MEMBERS)).toBe("Member 99");
  });
});

const NOOP = vi.fn();

function renderRequests(messages: MailMessageResponse[], search = "") {
  return render(
    <ConversationsTab
      conversations={buildConversations(messages, MEMBERS)} members={MEMBERS} loading={false} search={search}
      chip="all" team="" recipientMemberId={null} messageCount={messages.length}
      onSearchChange={NOOP} onChipChange={NOOP} onClearRecipient={NOOP} onOpenThread={NOOP}
    />,
  );
}

function card(subject: string): HTMLElement {
  return screen.getByText(subject).closest("[class*='rounded-lg']") as HTMLElement;
}

describe("Conversations list", () => {
  it("shows one label and the right icon for each sender type", () => {
    renderRequests(Object.values(BY_TYPE));
    const expected: Array<[string, string, RegExp | null]> = [
      ["Subject 1", "Deck", /Sent by Deck, not by an agent/],
      ["Subject 2", "Director", /Sent by the Director/],
      ["Subject 3", "L1 Leader", null],
      ["Subject 4", LEGACY_SENDER_LABEL, /Recorded before sender types existed/],
      ["Subject 5", "Supervisor (v3.1)", /Sent by an external tool/],
      ["Subject 6", "Unknown sender", /The sender is not known/],
    ];
    for (const [subject, name, icon] of expected) {
      const row = within(card(subject));
      expect(row.getByText(name)).toBeInTheDocument();
      if (icon) expect(row.getByRole("img", { name: icon })).toBeInTheDocument();
      else expect(row.queryAllByRole("img", { name: /^(Sent by|Recorded before|The sender)/ })).toHaveLength(0);
    }
  });

  it("does not show a scheduler message as sent by the Director", () => {
    renderRequests([BY_TYPE.deck]);
    const row = card("Subject 1");
    expect(row.textContent).toContain("Deck→B1 Backend");
    expect(row.textContent).not.toContain("Director");
  });

  it("finds a message by its sender label in the search", () => {
    renderRequests(Object.values(BY_TYPE), "deck");
    expect(screen.getByText("Subject 1")).toBeInTheDocument();
    expect(screen.queryByText("Subject 2")).not.toBeInTheDocument();
  });
});

describe("Thread dialog", () => {
  it.each([
    ["deck", "Deck", /Sent by Deck, not by an agent/],
    ["director", "Director", /Sent by the Director/],
    ["legacy", LEGACY_SENDER_LABEL, /Recorded before sender types existed/],
    ["unknown", "Unknown sender", /The sender is not known/],
  ] as const)("shows the %s label and icon in the thread", async (key, name, icon) => {
    const root = BY_TYPE[key];
    vi.mocked(fetchAgentMailThread).mockResolvedValue({ root, replies: [] } as never);
    render(<ThreadDialog message={root} members={MEMBERS} open onOpenChange={NOOP} onChanged={async () => undefined} />);
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText(`Body ${root.id}`);
    expect(within(dialog).getByText(name)).toBeInTheDocument();
    expect(within(dialog).getByRole("img", { name: icon })).toBeInTheDocument();
    expect(dialog.textContent).toContain(`From ${name} to B1 Backend`);
  });

  it("shows an agent name with no icon", async () => {
    const root = BY_TYPE.agent;
    vi.mocked(fetchAgentMailThread).mockResolvedValue({ root, replies: [] } as never);
    render(<ThreadDialog message={root} members={MEMBERS} open onOpenChange={NOOP} onChanged={async () => undefined} />);
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Body 3");
    expect(dialog.textContent).toContain("From L1 Leader to B1 Backend");
    expect(within(dialog).queryAllByRole("img", { name: /^Sent by/ })).toHaveLength(0);
  });
});
