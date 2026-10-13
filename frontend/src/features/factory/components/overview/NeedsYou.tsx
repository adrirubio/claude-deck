import { Link } from "react-router-dom";
import { buttonVariants } from "@/components/ui/button";
import type { NeedsYouRow } from "./needsYou";

export function NeedsYou({ rows, loading }: { rows: NeedsYouRow[]; loading: boolean }) {
  if (rows.length === 0) {
    return (
      <p className="rounded-lg border bg-card px-4 py-2.5 text-sm">
        {loading ? "Checking what needs you…" : "Nothing needs you right now."}
      </p>
    );
  }
  return (
    <section
      aria-labelledby="needs-you-heading"
      className="rounded-lg border-2 border-amber-500/60 bg-card"
    >
      <h3
        id="needs-you-heading"
        className="flex items-center gap-2 border-b border-amber-500/40 px-4 py-3 text-lg font-semibold"
      >
        Needs you
        <span className="rounded-full bg-amber-500 px-2 text-sm font-semibold text-black">
          {rows.length}
        </span>
      </h3>
      <ul>
        {rows.map((row) => (
          <li
            key={row.key}
            className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 last:border-b-0"
          >
            <div className="min-w-0">
              <p className="font-semibold">{row.title}</p>
              <p className="text-sm text-muted-foreground">
                {row.detail} · {row.team}
              </p>
            </div>
            <Link
              className={buttonVariants({ variant: "outline", size: "sm" })}
              to={row.href}
              aria-label={`${row.cta}: ${row.title} ${row.detail}`}
            >
              {row.cta}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
