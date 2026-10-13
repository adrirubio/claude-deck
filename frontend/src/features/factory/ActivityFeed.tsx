import { useState } from "react";
import { Link, useInRouterContext } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatServerTime, parseServerTime } from "@/lib/serverTime";
import type { AuditEventRead } from "./auditApi";
import {
  FEED_FILTERS,
  relativeTime,
  rowMatches,
  teamBadgeClass,
  type Feed,
  type FeedFilter,
  type FeedRow,
  type FeedTeam,
} from "./auditFeed";

interface ActivityFeedProps {
  feed: Feed;
  /** The clock for relative times. Tests fix it. */
  now: number;
  /** Stored snapshot labels of an event, shown only in the technical detail. */
  snapshotLabels: (event: AuditEventRead) => Array<{ name: string; text: string }>;
}

// The clock uses the same format as the rest of the app (formatServerTime with
// no options), so one moment reads the same on Work and Audit (#521). The zone
// name follows it.
const ZONE: Intl.DateTimeFormatOptions = { timeZoneName: "short" };
const FULL_TIME: Intl.DateTimeFormatOptions = {
  month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", timeZoneName: "short",
};

/** The short name of the browser time zone at that moment, for example "GMT+2". */
function zoneName(iso: string): string {
  const part = new Intl.DateTimeFormat(undefined, ZONE).formatToParts(parseServerTime(iso)).find((entry) => entry.type === "timeZoneName");
  return part?.value ?? "";
}

const OUTCOMES: Record<string, string> = {
  applied: "Done",
  rejected: "Refused",
  uncertain: "Not confirmed",
};

function outcomeText(event: AuditEventRead): string {
  return OUTCOMES[event.action_outcome ?? ""] ?? "Recorded";
}

function FeedLink({ href, children, className }: { href: string | null; children: React.ReactNode; className?: string }) {
  const inRouter = useInRouterContext();
  if (!href) return <span className={className}>{children}</span>;
  const classes = cn("underline underline-offset-2 hover:text-primary", className);
  return inRouter ? <Link to={href} className={classes}>{children}</Link> : <a href={href} className={classes}>{children}</a>;
}

function TeamBadge({ team }: { team: FeedTeam }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-semibold", teamBadgeClass(team.key))}>
      <FeedLink href={team.href}>{team.name}</FeedLink>
      {team.deleted && <span>(deleted)</span>}
      {team.formerly && <span className="font-normal">(formerly {team.formerly})</span>}
    </span>
  );
}

function TechnicalDetail({ row, snapshotLabels }: { row: FeedRow; snapshotLabels: ActivityFeedProps["snapshotLabels"] }) {
  return (
    <details className="rounded border bg-background p-2 text-xs">
      <summary className="cursor-pointer font-medium">Technical detail</summary>
      {row.events.map((event) => (
        <dl key={event.id} className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2">
          <div className="break-words"><span className="block font-medium">Event</span>{event.id}: {event.event_kind}</div>
          <div className="break-words"><span className="block font-medium">Source</span>{event.source}</div>
          <div className="break-words"><span className="block font-medium">Record kind</span>{event.record_kind}</div>
          <div className="break-words"><span className="block font-medium">Occurred</span>{event.occurred_at}</div>
          <div className="break-words"><span className="block font-medium">Fact source</span>{event.fact_source ?? "unavailable"}</div>
          <div className="break-words"><span className="block font-medium">Fact time</span>{event.fact_time ?? "unavailable"}</div>
          <div className="break-words"><span className="block font-medium">Actor reference</span>{event.actor_reference ?? "none"}</div>
          <div className="break-words"><span className="block font-medium">Reason</span>{event.sanitized_reason ?? "none"}</div>
          <div className="break-words sm:col-span-2">
            <span className="block font-medium">Context keys</span>
            team {event.team_context_key ?? "none"}; scope {event.scope_context_key ?? "none"}; item {event.item_context_key ?? "none"}
          </div>
          <div className="sm:col-span-2">
            <span className="block font-medium">Stored snapshot labels</span>
            {snapshotLabels(event).length
              ? snapshotLabels(event).map(({ name, text }) => <div key={name} className="break-words">{name}: {text}</div>)
              : "none named in this event"}
          </div>
          <div className="break-words sm:col-span-2">
            <span className="block font-medium">Before / after (allowlisted)</span>
            {JSON.stringify(event.before_values ?? {})} → {JSON.stringify(event.after_values ?? {})}
          </div>
        </dl>
      ))}
    </details>
  );
}

function RowDetail({ row, snapshotLabels }: { row: FeedRow; snapshotLabels: ActivityFeedProps["snapshotLabels"] }) {
  const first = row.events[0];
  return (
    <div id={`feed-detail-${row.key}`} className="mt-2 space-y-2 rounded border bg-muted/40 p-3 text-sm">
      <dl className="grid grid-cols-1 gap-1 sm:grid-cols-2">
        <div><span className="block text-xs font-medium">When</span>{formatServerTime(first.occurred_at, FULL_TIME)}</div>
        <div><span className="block text-xs font-medium">Who</span>{row.actor}</div>
        <div><span className="block text-xs font-medium">Outcome</span>{outcomeText(first)}</div>
        <div><span className="block text-xs font-medium">Team</span><TeamBadge team={row.team} /></div>
        {row.subject && (
          <div className="break-words sm:col-span-2">
            <span className="block text-xs font-medium">Subject</span>
            <FeedLink href={row.subject.href}>{row.subject.text}</FeedLink>
          </div>
        )}
        {row.reason && <div className="sm:col-span-2"><span className="block text-xs font-medium">Reason</span>{row.reason}</div>}
        {row.count > 1 && <div><span className="block text-xs font-medium">Recorded</span>{row.count} times within one second</div>}
        {row.notified.length > 0 && <div><span className="block text-xs font-medium">Notified</span>{row.notified.join(", ")}</div>}
      </dl>
      <TechnicalDetail row={row} snapshotLabels={snapshotLabels} />
    </div>
  );
}

function FeedRowView({ row, now, open, onToggle, snapshotLabels }: {
  row: FeedRow; now: number; open: boolean; onToggle: () => void; snapshotLabels: ActivityFeedProps["snapshotLabels"];
}) {
  const relative = relativeTime(row.occurredAt, now);
  return (
    <article
      data-testid="audit-feed-row"
      className={cn(
        "rounded border p-3",
        row.refused && "border-amber-300 bg-amber-50/60 dark:border-amber-800 dark:bg-amber-950/20",
      )}
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="whitespace-nowrap text-muted-foreground">
          <time dateTime={row.occurredAt} title={formatServerTime(row.occurredAt, FULL_TIME)}>
            {formatServerTime(row.occurredAt)} {zoneName(row.occurredAt)}
          </time>
          {relative && <> · {relative}</>}
        </span>
        <TeamBadge team={row.team} />
        <p className="min-w-0 break-words">
          {row.refused && (
            <span className="mr-1 inline-flex items-center gap-1 font-medium text-amber-800 dark:text-amber-300">
              <AlertTriangle aria-hidden="true" className="h-4 w-4" />
              Request refused:
            </span>
          )}
          <span className="font-medium">{row.actor}</span> {row.action}
          {row.subject && <> <FeedLink href={row.subject.href} className="font-medium">{row.subject.text}</FeedLink></>}
          {row.count > 1 && <span className="text-muted-foreground"> ({row.count} times)</span>}
        </p>
      </div>
      {row.reason && <p className="mt-1 text-sm">{row.reason}</p>}
      {row.changes.length > 0 && (
        <ul className="mt-1 text-sm text-muted-foreground">
          {row.changes.map((change) => <li key={change}>{change}</li>)}
        </ul>
      )}
      {row.notified.length > 0 && <p className="mt-1 text-xs text-muted-foreground">{row.notified.join(" · ")}</p>}
      <div className="mt-2">
        <Button
          variant="outline"
          size="sm"
          aria-expanded={open}
          aria-controls={`feed-detail-${row.key}`}
          onClick={onToggle}
        >
          {open ? "Hide detail" : "Show detail"}
        </Button>
      </div>
      {open && <RowDetail row={row} snapshotLabels={snapshotLabels} />}
    </article>
  );
}

/**
 * #519: one line per action, in plain words, with the team and the subject.
 * The filter chips narrow the rows of the loaded page. The detail opens under
 * its own row.
 */
export function ActivityFeed({ feed, now, snapshotLabels }: ActivityFeedProps) {
  const [filter, setFilter] = useState<FeedFilter>("all");
  const [openKey, setOpenKey] = useState<string | null>(null);
  const rows = feed.rows.filter((row) => rowMatches(row, filter));
  return (
    <div className="space-y-3">
      <div role="group" aria-label="Filter the activity" className="flex flex-wrap gap-2">
        {FEED_FILTERS.map(({ id, label }) => {
          const count = feed.rows.filter((row) => rowMatches(row, id)).length;
          return (
            <Button
              key={id}
              size="sm"
              variant={filter === id ? "default" : "outline"}
              aria-pressed={filter === id}
              onClick={() => setFilter(id)}
            >
              {label} ({count})
            </Button>
          );
        })}
      </div>
      <div role="feed" aria-label="Activity" aria-busy="false" className="space-y-2">
        {rows.map((row) => (
          <FeedRowView
            key={row.key}
            row={row}
            now={now}
            open={openKey === row.key}
            onToggle={() => setOpenKey(openKey === row.key ? null : row.key)}
            snapshotLabels={snapshotLabels}
          />
        ))}
      </div>
      {rows.length === 0 && <p className="text-sm">No activity on this page matches this filter.</p>}
      {feed.hiddenNotifications > 0 && (
        <p className="text-xs text-muted-foreground">
          {feed.hiddenNotifications} notification {feed.hiddenNotifications === 1 ? "record is" : "records are"} folded into
          actions on other pages.
        </p>
      )}
    </div>
  );
}
