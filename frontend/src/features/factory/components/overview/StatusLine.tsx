import { Link } from "react-router-dom";
import { buttonVariants } from "@/components/ui/button";
import type { OverviewResponse } from "@/types/factory";
import { statusSentence } from "./statusSentence";

const DOT = { on: "bg-primary", off: "bg-muted-foreground", warn: "bg-amber-500" } as const;

export function StatusLine({ data, teams }: { data: OverviewResponse; teams: number | null }) {
  const { tone, text } = statusSentence(data, teams);
  const [lead, ...rest] = text.split(/(?<=\.)\s/);
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3 text-sm">
      <p>
        <span aria-hidden="true" className={`mr-2 inline-block h-2 w-2 rounded-full ${DOT[tone as keyof typeof DOT]}`} />
        <strong>{lead}</strong> {rest.join(" ")}
      </p>
      {tone === "off" && (
        <Link className={buttonVariants({ variant: "outline", size: "sm" })} to="/teams">
          Open Teams
        </Link>
      )}
    </div>
  );
}
