import type { TeamCampaignSummary } from "@/types/agentTeams";
import { campaignBarLabel } from "./campaign";

// The bar is always drawn when there is known work. With a readable backlog it
// shows the whole campaign. Without one it shows only the work that Deck has
// seen, and a dashed end marks the part that nobody knows, so the bar never
// suggests that the campaign is nearly done.
export function CampaignBar({ campaign: c }: { campaign: TeamCampaignSummary }) {
  const known = c.backlog_state === "available";
  const todo = c.queued_count + (c.not_started_count ?? 0);
  const total = c.done_count + c.under_way_count + todo;
  if (total === 0) return null;
  // With an unknown remainder the known work fills 80% of the bar.
  const scale = known ? 100 : 80;
  const width = (n: number) => `${(n / total) * scale}%`;
  return (
    <div
      role="img"
      aria-label={campaignBarLabel(c)}
      className="flex h-2 overflow-hidden rounded bg-muted"
    >
      <span className="bg-primary" style={{ width: width(c.done_count) }} />
      <span className="bg-violet-500" style={{ width: width(c.under_way_count) }} />
      <span className="bg-muted-foreground/50" style={{ width: width(todo) }} />
      {!known && (
        <span
          data-testid="unknown-remainder"
          className="flex-1 border-l-2 border-dashed border-muted-foreground text-muted-foreground"
          style={{
            backgroundImage:
              "repeating-linear-gradient(135deg, transparent 0 3px, color-mix(in srgb, currentColor 55%, transparent) 3px 5px)",
          }}
        />
      )}
    </div>
  );
}
