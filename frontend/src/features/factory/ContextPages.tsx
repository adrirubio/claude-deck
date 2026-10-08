import { Link, useSearchParams } from "react-router-dom";
import { CCBridgePage } from "@/features/cc-bridge/CCBridgePage";
import { TerminalView } from "@/features/cc-bridge/TerminalView";
import type { CCSession } from "@/features/cc-bridge/types";
import { AgentMailPage } from "@/features/agent-mail/AgentMailPage";
import type {
  TeamListResponse,
  MailMessageResponse,
  MailThreadResponse,
} from "@/types/agentMail";
import { useObservation } from "./reads";

import { positive, verifiedBridgeSession } from "./contextLinks";
function BridgeContext() {
  const [query] = useSearchParams();
  const state = useObservation<{ sessions: CCSession[] }>(
    "agent-bridge/sessions",
  );
  const sessions = state.data?.sessions ?? [];
  const verified = !state.error ? verifiedBridgeSession(sessions, query) : null;
  const team = positive(query.get("team_id")),
    slot = positive(query.get("slot_id"));
  const candidates = sessions.filter(
    (s) =>
      team !== null &&
      s.team_preset_id === team &&
      (slot === null || s.team_slot_id === slot),
  );
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Read-only session context</h2>
      <p>
        Verified team {team ?? "unknown"} / slot {slot ?? "unknown"}. Navigation
        never sends terminal input, launches, restarts or claims work.
      </p>
      {state.error && (
        <p role="alert">
          {state.error.message}; last session observation is stale. Automatic
          terminal selection is disabled.
        </p>
      )}
      {state.refreshing && !state.data && (
        <p role="status">Loading session associations…</p>
      )}
      {verified ? (
        <div className="h-[60vh] min-h-80">
          <TerminalView
            key={verified.tmux_target}
            target={verified.tmux_target}
            session={verified}
            forceReadOnly
          />
        </div>
      ) : (
        <div className="rounded border p-4">
          <p>
            No unique current team/slot/member/MCP-session match. Inspect
            candidates; no terminal is selected.
          </p>
          <ul>
            {candidates.map((s) => (
              <li key={s.tmux_target}>
                {s.team_slot_name ?? "Slot"} · {s.provider} · member{" "}
                {s.mail_member_id ?? "unknown"} · MCP session{" "}
                {s.mail_mcp_session_id ?? "unknown"}
              </li>
            ))}
          </ul>
          {!candidates.length && <p>No matching current sessions.</p>}
        </div>
      )}
      <Link className="text-primary underline" to={`/teams/${team ?? ""}`}>
        Inspect team
      </Link>
      <p>
        <Link className="text-primary underline" to="/agent-bridge">
          Open manual live sessions
        </Link>
      </p>
    </section>
  );
}
export function BridgeEntry() {
  const [query] = useSearchParams();
  return query.get("context") === "readonly" ? (
    <BridgeContext />
  ) : (
    <CCBridgePage />
  );
}
function MailThread({ id }: { id: number }) {
  const state = useObservation<MailThreadResponse>(
    `agent-mail/messages/${id}/thread`,
  );
  return (
    <div className="space-y-3">
      {state.error && <p role="alert">{state.error.message}</p>}
      {state.data &&
        [state.data.root, ...state.data.replies].map((m) => (
          <article key={m.id} className="rounded border p-3">
            <h3 className="font-semibold">{m.subject ?? "Reply"}</h3>
            <p>
              {m.sender_name} · {m.kind} · {m.request_status ?? "message"}
            </p>
            <p className="whitespace-pre-wrap break-words text-sm">
              {m.body_markdown}
            </p>
          </article>
        ))}
    </div>
  );
}
function MailContext() {
  const [query, setQuery] = useSearchParams();
  const team = positive(query.get("team_id")),
    slot = positive(query.get("slot_id")),
    memberId = positive(query.get("member_id"));
  const members = useObservation<TeamListResponse>(
    "agent-mail/team?sync=false",
  );
  const messages = useObservation<MailMessageResponse[]>("agent-mail/messages");
  const member = members.data?.members.find(
    (m) =>
      m.id === memberId && m.team_preset_id === team && m.team_slot_id === slot,
  );
  const context = member
    ? (messages.data?.filter(
        (m) =>
          m.sender_member_id === member.id ||
          m.recipient_member_id === member.id ||
          (m.audience_type === "team_preset" && Number(m.audience_id) === team),
      ) ?? [])
    : [];
  const thread = positive(query.get("thread_id"));
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Mail context</h2>
      <p>
        Read-only context for team {team ?? "unknown"} / slot{" "}
        {slot ?? "unknown"} / member {memberId ?? "unknown"}. Reading does not
        check an agent inbox, acknowledge a request, send a message or approve
        work.
      </p>
      {members.error && <p role="alert">{members.error.message}</p>}
      {messages.error && <p role="alert">{messages.error.message}</p>}
      {member ? (
        <p>
          {member.display_name} · {member.status} · {member.pending_count}{" "}
          pending requests
        </p>
      ) : (
        <p>
          Member association is unavailable or does not match. No guessed
          recipient.
        </p>
      )}
      <ul className="space-y-2">
        {context.map((m) => (
          <li key={m.id}>
            <button
              className="text-primary underline"
              onClick={() => {
                const next = new URLSearchParams(query);
                next.set("thread_id", String(m.id));
                setQuery(next);
              }}
            >
              {m.subject ?? `Message ${m.id}`} · {m.kind} ·{" "}
              {m.request_status ?? "message"}
            </button>
          </li>
        ))}
      </ul>
      {member && thread && context.some((m) => m.id === thread) && (
        <MailThread key={thread} id={thread} />
      )}
      <Link className="text-primary underline" to="/agent-mail">
        Open Coordination
      </Link>
    </section>
  );
}
export function MailEntry() {
  const [query] = useSearchParams();
  return query.has("member_id") ||
    query.has("team_id") ||
    query.has("slot_id") ? (
    <MailContext />
  ) : (
    <AgentMailPage />
  );
}
