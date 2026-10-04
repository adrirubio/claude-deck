import type { CCSession } from "@/features/cc-bridge/types";
export function positive(value: string | null) {
  return value &&
    /^[1-9]\d*$/.test(value) &&
    Number.isSafeInteger(Number(value))
    ? Number(value)
    : null;
}
export function verifiedBridgeSession(
  sessions: CCSession[],
  query: URLSearchParams,
) {
  const team = positive(query.get("team_id")),
    slot = positive(query.get("slot_id")),
    member = positive(query.get("member_id")),
    session = positive(query.get("session_id"));
  if (!team || !slot || !member || !session) return null;
  const matches = sessions.filter(
    (s) =>
      s.team_preset_id === team &&
      s.team_slot_id === slot &&
      s.mail_member_id === member &&
      Number(s.mail_mcp_session_id) === session,
  );
  return matches.length === 1 ? matches[0] : null;
}
