import type { AuditEventRead } from "./auditApi";
import { plainReason } from "./auditRefusals";

// #519: turn audit events into the rows of the activity feed. Every row says
// who did what, to which subject, in which team, in plain words. This module
// only reads events. It never shows a code name, `null` or a raw timestamp
// outside the technical detail of a row.

export interface FeedContext {
  /** Current team names by team preset id. */
  teams: Record<number, string>;
  /** Agent Mail member names by member id. */
  members: Record<number, string>;
}

export interface FeedTeam {
  key: string | null;
  name: string;
  deleted: boolean;
  /** The name stored at the time, when it differs from the current name. */
  formerly: string | null;
  factoryWide: boolean;
  href: string | null;
}

export interface FeedSubject {
  text: string;
  href: string | null;
}

export type FeedFilter = "all" | "director" | "refused" | "deliveries" | "requests";

export interface FeedRow {
  key: string;
  occurredAt: string;
  /** How many events this row stands for (same action recorded several times). */
  count: number;
  actor: string;
  /** The plain verb phrase, with its preposition. */
  action: string;
  subject: FeedSubject | null;
  refused: boolean;
  /** A plain reason for a refusal. Null when the reason is not a refusal. */
  reason: string | null;
  /** Changed settings, for example "enabled: on → off". */
  changes: string[];
  notified: string[];
  team: FeedTeam;
  matches: Record<Exclude<FeedFilter, "all">, boolean>;
  events: AuditEventRead[];
}

export interface Feed {
  rows: FeedRow[];
  /** Notification records that had no parent action on this page. */
  hiddenNotifications: number;
}

export const FEED_FILTERS: Array<{ id: FeedFilter; label: string }> = [
  { id: "all", label: "All" },
  { id: "director", label: "Director actions" },
  { id: "refused", label: "Refused" },
  { id: "deliveries", label: "Deliveries" },
  { id: "requests", label: "Agent requests" },
];

const GROUP_WINDOW_MS = 1000;
const NOTIFICATION_WINDOW_MS = 30_000;

interface KindLabel {
  /** The plain verb phrase. */
  action: string;
  /** What a refused request of this kind says. */
  refused?: string;
}

const KIND_LABELS: Record<string, KindLabel> = {
  policy_change: { action: "changed the settings of" },
  scope_policy_change: { action: "changed the settings of" },
  team_delete: { action: "deleted" },
  work_lifecycle: { action: "changed the state of" },
  delivery_evidence: { action: "delivered" },
  revision_outcome: { action: "recorded the outcome of a plan revision for" },
  retry_charge: { action: "used a retry on" },
  review_acceptance_declared: { action: "declared the review accepted for" },
  workspace_release: { action: "released the workspace for" },
  leader_assignment: { action: "assigned the Leader of" },
  handoff_acceptance: { action: "accepted a handoff for" },
  handoff_reassignment: { action: "handed work over on" },
  recovery_cancellation: { action: "cancelled a recovery plan for" },
  recovery_hold: { action: "held a recovery for" },
  recovery_checkpoint_release: { action: "released a recovery checkpoint for" },
  prepared_attempt_resume: { action: "resumed a prepared attempt for" },
  operator_escalation: { action: "stopped the attempt on" },
  request_cancellation: { action: "cancelled a request for" },
  continuation_request: { action: "asked to continue with a new plan on", refused: "asked to continue" },
  continuation_decision: { action: "decided on a plan to continue for" },
  continuation_ack: { action: "acknowledged an approved plan for" },
  approval_decision: { action: "decided on a plan for" },
};

const WORK_STATE_ACTIONS: Record<string, string> = {
  dispatched: "dispatched work on",
  escalated: "stopped work on",
  merged: "marked as merged",
  ready_for_review: "marked ready for review",
  verifying: "started checks on",
  blocked: "marked as blocked",
};

const NOTIFICATION_LABELS: Record<string, string> = {
  continuation_request_notification: "Leader notified",
  approval_decision_notification: "Owner notified",
  continuation_decision_notification: "Owner notified",
  continuation_delivery_notification: "Owner notified",
  recovery_cancellation_notification: "Owner notified",
  handoff_notification: "Recipient notified",
  operator_escalation_notification: "Director notified",
  lifecycle_notification: "Owner notified",
};

/** The action kinds that a notification can belong to. */
const NOTIFICATION_PARENTS: Record<string, string[]> = {
  continuation_request_notification: ["continuation_request"],
  approval_decision_notification: ["approval_decision"],
  continuation_decision_notification: ["continuation_decision", "approval_decision"],
  continuation_delivery_notification: ["continuation_decision", "continuation_ack"],
  recovery_cancellation_notification: ["recovery_cancellation"],
  handoff_notification: ["handoff_reassignment", "handoff_acceptance"],
  operator_escalation_notification: ["operator_escalation"],
  lifecycle_notification: ["work_lifecycle"],
};

const DELIVERY_KINDS = new Set(["delivery_evidence", "revision_outcome", "review_acceptance_declared"]);
const REQUEST_KINDS = new Set([
  "continuation_request", "continuation_decision", "continuation_ack", "approval_decision",
  "handoff_acceptance", "handoff_reassignment", "request_cancellation",
]);

/** Tailwind classes for the team badges. Each pair keeps AA contrast in both themes. */
export const TEAM_BADGE_CLASSES = [
  "border-blue-300 bg-blue-50 text-blue-800 dark:border-blue-800 dark:bg-blue-950/40 dark:text-blue-300",
  "border-violet-300 bg-violet-50 text-violet-800 dark:border-violet-800 dark:bg-violet-950/40 dark:text-violet-300",
  "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300",
  "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
  "border-rose-300 bg-rose-50 text-rose-800 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300",
  "border-cyan-300 bg-cyan-50 text-cyan-800 dark:border-cyan-800 dark:bg-cyan-950/40 dark:text-cyan-300",
];

/** A stable badge class for a team key. */
export function teamBadgeClass(key: string | null): string {
  if (!key) return "border-muted-foreground/30 bg-muted text-muted-foreground";
  let hash = 0;
  for (const char of key) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return TEAM_BADGE_CLASSES[hash % TEAM_BADGE_CLASSES.length];
}

function snapshotText(event: AuditEventRead, name: string): string | null {
  const value = (event.context_snapshot ?? {})[name];
  if (typeof value === "string" && value) return value;
  if (typeof value === "number") return String(value);
  return null;
}

function timeOf(event: AuditEventRead): number {
  return Date.parse(event.occurred_at);
}

function isNotification(event: AuditEventRead): boolean {
  return event.event_kind.endsWith("_notification");
}

/** The plain name of the actor. Never a role code. */
export function actorName(event: AuditEventRead, members: Record<number, string>): string {
  if (event.actor_kind === "operator") return "Director";
  if (event.actor_kind === "member") {
    const match = /^member:(\d+)$/.exec(event.actor_reference ?? "");
    // A name that cannot be found reads "An agent", never "member <id>".
    if (match) return members[Number(match[1])] ?? "An agent";
    return "An agent";
  }
  return "Deck";
}

function teamOf(event: AuditEventRead, ctx: FeedContext): FeedTeam {
  const stored = snapshotText(event, "team_display_name");
  const key = event.team_context_key ?? null;
  const id = event.team_preset_id ?? null;
  if (!key && id == null && !stored) {
    return { key: null, name: "Factory-wide", deleted: false, formerly: null, factoryWide: true, href: null };
  }
  const current = id != null ? ctx.teams[id] : undefined;
  const deleted = id == null;
  const name = current ?? stored ?? "Unnamed team";
  return {
    key: key ?? (id != null ? `team:${id}` : stored),
    name,
    deleted,
    formerly: current && stored && current !== stored ? stored : null,
    factoryWide: false,
    href: !deleted && id != null ? `/teams/${id}` : null,
  };
}

function subjectOf(event: AuditEventRead, team: FeedTeam): FeedSubject | null {
  const owner = snapshotText(event, "repo_owner");
  const repo = snapshotText(event, "repo_name");
  const issue = snapshotText(event, "issue_number");
  const pr = snapshotText(event, "pr_number");
  const repoText = repo ? (owner ? `${owner}/${repo}` : repo) : null;
  if (event.event_kind === "team_delete" || event.event_kind === "leader_assignment") {
    return { text: `team ${team.name}`, href: team.href };
  }
  if (issue || pr) {
    const where = [repoText, issue ? `#${issue}` : null].filter(Boolean).join(" ");
    const text = pr ? `${where ? `${where}, ` : ""}PR #${pr}` : where;
    return { text, href: event.item_id != null ? `/work/${event.item_id}` : null };
  }
  if (event.item_id != null) return { text: "a work item", href: `/work/${event.item_id}` };
  if (repoText) {
    return { text: `repository ${repoText}`, href: event.scope_id != null ? `/repositories/${event.scope_id}` : null };
  }
  if (event.scope_id != null) return { text: "a repository", href: `/repositories/${event.scope_id}` };
  if (!team.factoryWide) return { text: `team ${team.name}`, href: team.href };
  return null;
}

function format(value: unknown): string {
  if (value === true) return "on";
  if (value === false) return "off";
  if (value === null || value === undefined) return "not set";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return "changed";
}

/** The changed settings only: "enabled: on → off". */
export function changedFields(before: Record<string, unknown> | null | undefined, after: Record<string, unknown> | null | undefined): string[] {
  const left = before ?? {};
  const right = after ?? {};
  const keys = [...new Set([...Object.keys(left), ...Object.keys(right)])].sort();
  return keys
    .filter((key) => JSON.stringify(left[key] ?? null) !== JSON.stringify(right[key] ?? null))
    .map((key) => `${key.replaceAll("_", " ")}: ${format(left[key])} → ${format(right[key])}`);
}

function actionOf(event: AuditEventRead, refused: boolean): string {
  const label = KIND_LABELS[event.event_kind];
  if (event.event_kind === "work_lifecycle") {
    const status = event.after_values?.["dispatch_status"];
    return (typeof status === "string" && WORK_STATE_ACTIONS[status]) || label.action;
  }
  if (event.event_kind === "approval_decision" || event.event_kind === "continuation_decision") {
    const decision = JSON.stringify(event.after_values ?? {}).toLowerCase();
    if (/approved/.test(decision)) return "approved a plan for";
    if (/declined|rejected/.test(decision)) return "declined a plan for";
  }
  if (!label) return "did something that Deck does not describe on";
  return refused && label.refused ? label.refused : label.action;
}

function sameAction(left: AuditEventRead, right: AuditEventRead): boolean {
  return left.event_kind === right.event_kind
    && left.actor_reference === right.actor_reference
    && left.item_id === right.item_id
    && left.scope_id === right.scope_id
    && left.team_preset_id === right.team_preset_id
    && left.action_outcome === right.action_outcome
    && left.sanitized_reason === right.sanitized_reason
    && JSON.stringify(left.before_values ?? null) === JSON.stringify(right.before_values ?? null)
    && JSON.stringify(left.after_values ?? null) === JSON.stringify(right.after_values ?? null);
}

function makeRow(group: AuditEventRead[], ctx: FeedContext): FeedRow {
  const first = group[0];
  const refused = first.action_outcome === "rejected";
  const team = teamOf(first, ctx);
  const policy = first.event_kind === "policy_change" || first.event_kind === "scope_policy_change";
  const subject = subjectOf(first, team);
  // Without a subject the preposition at the end of the phrase has no object.
  const action = actionOf(first, refused);
  return {
    key: `event-${first.id}`,
    occurredAt: first.occurred_at,
    count: group.length,
    actor: actorName(first, ctx.members),
    action: subject ? action : action.replace(/ (of|for|on)$/, ""),
    subject,
    refused,
    reason: refused ? plainReason(first.sanitized_reason) : null,
    changes: policy ? changedFields(first.before_values, first.after_values) : [],
    notified: [],
    team,
    matches: {
      director: first.actor_kind === "operator",
      refused,
      deliveries: DELIVERY_KINDS.has(first.event_kind),
      requests: REQUEST_KINDS.has(first.event_kind),
    },
    events: group,
  };
}

function importRow(events: AuditEventRead[]): FeedRow {
  const newest = events.reduce((a, b) => (timeOf(b) > timeOf(a) ? b : a));
  return {
    key: `import-${newest.id}`,
    occurredAt: newest.occurred_at,
    count: events.length,
    actor: "Deck",
    action: `recorded the start of the history; existing state imported (${events.length} ${events.length === 1 ? "record" : "records"})`,
    subject: null,
    refused: false,
    reason: null,
    changes: [],
    notified: [],
    team: { key: null, name: "Factory-wide", deleted: false, formerly: null, factoryWide: true, href: null },
    matches: { director: false, refused: false, deliveries: false, requests: false },
    events,
  };
}

/** The best parent action for a notification, or null. */
function parentOf(notification: AuditEventRead, actions: AuditEventRead[]): AuditEventRead | null {
  const kinds = NOTIFICATION_PARENTS[notification.event_kind]
    ?? [notification.event_kind.replace(/_notification$/, "")];
  let best: AuditEventRead | null = null;
  let bestGap = Infinity;
  for (const action of actions) {
    if (!kinds.includes(action.event_kind)) continue;
    const sameSubject = notification.item_id != null
      ? action.item_id === notification.item_id
      : notification.scope_id != null
        ? action.scope_id === notification.scope_id
        : action.team_preset_id === notification.team_preset_id;
    if (!sameSubject) continue;
    const gap = Math.abs(timeOf(action) - timeOf(notification));
    if (gap <= NOTIFICATION_WINDOW_MS && gap < bestGap) {
      best = action;
      bestGap = gap;
    }
  }
  return best;
}

/**
 * Build the feed for one page of events (newest first, as the API sends them).
 * Notifications fold into their action. Repeats of one action within a second
 * make one row. The setup import is one row.
 */
export function buildFeed(events: AuditEventRead[], ctx: FeedContext): Feed {
  const notifications = events.filter(isNotification);
  const imports = events.filter((event) => event.event_kind === "work_state_import");
  const actions = events.filter((event) => !isNotification(event) && event.event_kind !== "work_state_import");

  // Rows keep the order of their newest event.
  const entries: Array<{ at: number; row: FeedRow }> = [];
  let current: AuditEventRead[] = [];
  const flush = () => {
    if (current.length === 0) return;
    entries.push({ at: timeOf(current[0]), row: makeRow(current, ctx) });
    current = [];
  };
  for (const event of actions) {
    const last = current[current.length - 1];
    if (last && sameAction(last, event) && Math.abs(timeOf(last) - timeOf(event)) <= GROUP_WINDOW_MS) {
      current.push(event);
    } else {
      flush();
      current = [event];
    }
  }
  flush();
  if (imports.length > 0) {
    const row = importRow(imports);
    entries.push({ at: Date.parse(row.occurredAt), row });
  }
  entries.sort((a, b) => b.at - a.at);

  let hidden = 0;
  for (const notification of notifications) {
    const parent = parentOf(notification, actions);
    const row = parent ? entries.find((entry) => entry.row.events.includes(parent))?.row : undefined;
    if (!row) {
      hidden += 1;
      continue;
    }
    const label = NOTIFICATION_LABELS[notification.event_kind] ?? "Notified";
    if (!row.notified.includes(label)) row.notified.push(label);
  }
  return { rows: entries.map((entry) => entry.row), hiddenNotifications: hidden };
}

export function rowMatches(row: FeedRow, filter: FeedFilter): boolean {
  return filter === "all" || row.matches[filter];
}

/** "just now", "12 min ago" or "3 h ago" inside one day. Null for older events. */
export function relativeTime(iso: string, nowMs: number): string | null {
  const gap = nowMs - Date.parse(iso);
  if (!Number.isFinite(gap) || gap < 0 || gap >= 24 * 3600 * 1000) return null;
  const minutes = Math.floor(gap / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  return `${Math.floor(minutes / 60)} h ago`;
}
