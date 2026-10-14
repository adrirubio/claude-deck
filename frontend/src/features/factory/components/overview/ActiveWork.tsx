import { Link } from "react-router-dom";
import type { WorkProjection } from "@/types/factory";
import { useCursorList } from "../../reads";
import { anchor } from "../styles";
import { WorkTable } from "../WorkTable";

// A short preview of the open work that is not in Needs you: In progress and
// Needs review. It is empty and hidden when there is none.
export function ActiveWork({ query, viewAll }: { query: string; viewAll: string }) {
  const join = (category: string) => `factory/work-items?${query ? `${query}&` : ""}category=${category}&limit=8`;
  const id = (row: WorkProjection) => row.item.id;
  const active = useCursorList<WorkProjection>(join("active"), "items", id);
  const review = useCursorList<WorkProjection>(join("review"), "items", id);
  const rows = [...(active.data?.rows ?? []), ...(review.data?.rows ?? [])]
    .sort((a, b) => b.item.updated_at.localeCompare(a.item.updated_at))
    .slice(0, 8);
  if (rows.length === 0) return null;
  return (
    <section aria-labelledby="active-work-heading" className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <h3 id="active-work-heading" className="text-lg font-semibold">
          Active work <span className="text-sm font-normal text-muted-foreground">{rows.length}</span>
        </h3>
        <Link className={anchor} to={viewAll}>All work ›</Link>
      </div>
      <WorkTable rows={rows} />
    </section>
  );
}
