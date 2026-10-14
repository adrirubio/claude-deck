import { Link } from "react-router-dom";
import type { AgentTeamPreset, AgentTeamSummary, CampaignUnderWayItem } from "@/types/agentTeams";
import { RelativeTime } from "../RelativeTime";
import { anchor } from "../styles";
import { campaignHasContent } from "./campaign";
import { CampaignBar } from "./CampaignBar";

function parentLabel(url: string | null) {
  const match = url ? /\/issues\/(\d+)\/?$/.exec(url) : null;
  return match ? `#${match[1]}` : "parent issue";
}

function underWayText(item: CampaignUnderWayItem) {
  if (item.state_phrase === "waiting for you") return "Waiting for you";
  if (item.owner_short_name) return `${item.owner_short_name} is ${item.state_phrase}`;
  return item.state_phrase.charAt(0).toUpperCase() + item.state_phrase.slice(1);
}

function Count({ label, value, dot }: { label: string; value: number; dot: string }) {
  return (
    <h5 className="flex items-center gap-2 text-sm font-semibold">
      <span aria-hidden="true" className={`inline-block h-2.5 w-2.5 rounded-sm ${dot}`} />
      <span className="text-muted-foreground">{label}</span>
      <span className="text-base">{value}</span>
    </h5>
  );
}

function More({ count, to }: { count: number; to: string }) {
  if (count <= 0) return null;
  return (
    <Link className="text-sm text-muted-foreground underline underline-offset-4" to={to}>
      and {count} more ›
    </Link>
  );
}

function CampaignCard({ preset, summary }: { preset: AgentTeamPreset; summary: AgentTeamSummary }) {
  const c = summary.campaign!;
  const notStarted = c.not_started_count ?? 0;
  const total = c.done_count + c.under_way_count + c.queued_count + notStarted;
  const knownTotal = c.done_count + c.under_way_count + c.queued_count;
  const parent = summary.parent_issue_url;
  const work = `/work?team_id=${preset.id}`;
  const decisions = c.decisions_ahead.filter((d) => d.state !== "done");
  const paused = !preset.autonomy_enabled;
  return (
    <article aria-label={`Progress: ${summary.description || preset.name}`} className="space-y-3 border-b p-4 last:border-b-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-base font-semibold">
          {summary.description || preset.name}{" "}
          <span className="text-sm font-normal text-muted-foreground">
            {preset.name}
            {parent && <> · parent issue {parentLabel(parent)}</>}
          </span>
        </h4>
        <p className="text-sm text-muted-foreground">
          <strong className="text-base text-foreground">{c.done_count}</strong>
          {c.backlog_state === "available"
            ? ` of ${total} done`
            : knownTotal > 0 ? ` of ${knownTotal} known ${knownTotal === 1 ? "item" : "items"} done` : " done"}
          {c.backlog_state !== "available" && (
            <span className="ml-2 rounded border px-2 text-xs font-medium">backlog unknown</span>
          )}
        </p>
      </div>
      <CampaignBar campaign={c} />
      {c.backlog_state !== "available" && (
        <p role="note" className="text-sm text-muted-foreground">
          The backlog cannot be read, so Deck shows only the work it has seen.
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-3">
        <div className="space-y-2">
          <Count label="Done" value={c.done_count} dot="bg-primary" />
          {c.latest_done.length === 0 && <p className="text-sm text-muted-foreground">Nothing is done yet.</p>}
          {c.latest_done.map((item) => (
            <p key={item.title} className="text-sm">
              {item.title}
              {item.merged_at && (
                <span className="block text-xs text-muted-foreground">
                  finished <RelativeTime value={item.merged_at} />
                </span>
              )}
            </p>
          ))}
          <More count={c.done_count - c.latest_done.length} to={`/work?team_id=${preset.id}&category=finished`} />
        </div>
        <div className="space-y-2">
          <Count label="Under way" value={c.under_way_count} dot="bg-violet-500" />
          {c.under_way.length === 0 && (
            <p className="text-sm text-muted-foreground">
              {paused ? "Paused. Nothing is under way." : "Nothing is under way."}
            </p>
          )}
          {c.under_way.map((item) => (
            <p key={item.title} className="text-sm">
              {item.title}
              <span className="block text-xs text-muted-foreground">{underWayText(item)}</span>
            </p>
          ))}
          <More count={c.under_way_count - c.under_way.length} to={work} />
        </div>
        <div className="space-y-2">
          <Count label="Still to do" value={c.queued_count + notStarted} dot="bg-muted-foreground/60" />
          {c.queued.map((item) => (
            <p key={item.title} className="text-sm">
              {item.title}
              <span className="block text-xs text-muted-foreground">queued</span>
            </p>
          ))}
          <More count={c.queued_count - c.queued.length} to={work} />
          {c.not_started_count !== null && (
            <p className="text-sm text-muted-foreground">
              {notStarted} not started{paused ? " · the team is paused" : ""}
            </p>
          )}
          {c.not_started_groups.length > 0 && (
            <ul className="flex flex-wrap gap-1">
              {c.not_started_groups.map((group) => (
                <li key={group.area} className="rounded-full border px-2 text-xs text-muted-foreground">
                  {group.area} {group.count}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-dashed pt-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-muted-foreground">Your decisions ahead:</span>
          {decisions.length === 0 && <span className="text-muted-foreground">none</span>}
          {decisions.map((decision) => (
            <span
              key={decision.text}
              className={decision.state === "now"
                ? "rounded-full border border-amber-500/70 px-2 font-medium text-amber-800 dark:text-amber-300"
                : "rounded-full border px-2 text-muted-foreground"}
            >
              {decision.text.replace(/\.$/, "")} · {decision.state === "now" ? "now" : "later"}
            </span>
          ))}
        </div>
        <span className="flex gap-3">
          <Link className={anchor} to={work}>Work ›</Link>
          {parent && (
            <a className={anchor} href={parent} target="_blank" rel="noreferrer">
              Parent issue {parentLabel(parent)} ›
            </a>
          )}
        </span>
      </div>
    </article>
  );
}

export function CampaignProgress({
  presets,
  summaries,
}: {
  presets: AgentTeamPreset[];
  summaries: (AgentTeamSummary | null)[];
}) {
  const cards = presets.flatMap((preset, index) => {
    const summary = summaries[index];
    return summary && campaignHasContent(summary.campaign) ? [{ preset, summary }] : [];
  });
  if (cards.length === 0) return null;
  return (
    <section aria-labelledby="progress-heading" className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <h3 id="progress-heading" className="text-lg font-semibold">
          Progress <span className="text-sm font-normal text-muted-foreground">{cards.length} {cards.length === 1 ? "campaign" : "campaigns"}</span>
        </h3>
        <Link className={anchor} to="/work">All work ›</Link>
      </div>
      <div className="rounded-lg border bg-card">
        {cards.map(({ preset, summary }) => (
          <CampaignCard key={preset.id} preset={preset} summary={summary} />
        ))}
      </div>
    </section>
  );
}
