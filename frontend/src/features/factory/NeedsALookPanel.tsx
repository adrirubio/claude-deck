import { Link, useInRouterContext } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { formatServerTime } from "@/lib/serverTime";
import { REFUSAL_REPEAT_THRESHOLD, type RefusalGroup } from "./auditRefusals";

export type RefusalReadState = "locked" | "loading" | "ready" | "failed";

interface NeedsALookPanelProps {
  state: RefusalReadState;
  groups: RefusalGroup[];
  /** Member names by Agent Mail member id. A missing name falls back to the id. */
  names: Record<number, string>;
  /** The read stopped at its page cap, so older refusals are not counted. */
  truncated: boolean;
  onShowEvents: (group: RefusalGroup) => void;
  onUnlock: () => void;
}

const LAST_TIME: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" };

function memberLabel(group: RefusalGroup, names: Record<number, string>): string {
  if (group.memberId == null) return "an agent";
  return names[group.memberId] ?? `member ${group.memberId}`;
}

function ItemLink({ group }: { group: RefusalGroup }) {
  const inRouter = useInRouterContext();
  const label = `Open ${group.itemLabel}`;
  if (!group.linkAvailable) return null;
  const href = `/work/${group.itemId}`;
  const className = buttonVariants({ variant: "outline", size: "sm" });
  return inRouter
    ? <Link to={href} className={className}>{label}</Link>
    : <a href={href} className={className}>{label}</a>;
}

/**
 * #520: refused agent requests, grouped by member and item, with a plain
 * reason for each. It is a read-only display of audit events.
 */
export function NeedsALookPanel({ state, groups, names, truncated, onShowEvents, onUnlock }: NeedsALookPanelProps) {
  return (
    <section aria-labelledby="needs-a-look" className="space-y-3 rounded border p-3">
      <h3 id="needs-a-look" className="font-semibold">Needs a look (this window)</h3>
      {state === "locked" && (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm">The Director key is needed to read refused requests.</p>
          <Button variant="outline" size="sm" onClick={onUnlock}>Unlock</Button>
        </div>
      )}
      {state === "loading" && <p className="text-sm text-muted-foreground">Reading refused requests.</p>}
      {state === "failed" && <p role="alert" className="text-sm text-destructive">Refused requests could not be read.</p>}
      {state === "ready" && groups.length === 0 && (
        <p className="text-sm">Nothing needs a look in this window.</p>
      )}
      {state === "ready" && groups.map((group) => (
        <div key={group.key} className="space-y-1 rounded border bg-muted/30 p-3">
          <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
            <AlertTriangle aria-hidden="true" className="h-4 w-4 text-amber-600 dark:text-amber-400" />
            <span>
              {group.total} {group.total === 1 ? "request" : "requests"} from {memberLabel(group, names)}{" "}
              {group.total === 1 ? "was" : "were"} refused on {group.itemLabel}
            </span>
          </p>
          <ul className="space-y-1 text-sm">
            {group.reasons.map((reason) => (
              <li key={reason.sentence}>
                {reason.count}× {reason.sentence}
                <span className="text-muted-foreground"> · last {formatServerTime(reason.lastAt, LAST_TIME)}</span>
                {reason.count >= REFUSAL_REPEAT_THRESHOLD && (
                  <span className="block text-xs text-muted-foreground">
                    This refusal came back {reason.count} times. A repeated refusal often means a factory defect, not an agent mistake.
                  </span>
                )}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2 pt-1">
            <ItemLink group={group} />
            <Button variant="outline" size="sm" onClick={() => onShowEvents(group)}>Show events</Button>
          </div>
        </div>
      ))}
      {state === "ready" && truncated && (
        <p className="text-xs text-muted-foreground">
          Deck read only the newest request events. Older refusals in this window are not counted.
        </p>
      )}
    </section>
  );
}
