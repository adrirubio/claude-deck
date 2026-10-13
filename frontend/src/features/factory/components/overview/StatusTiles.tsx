import { Link } from "react-router-dom";
import type { FactoryCounts } from "@/types/factory";
import { categories, workLink } from "../../filterHelpers";
import { panel } from "../styles";

const ORDER = ["attention", "active", "review", "queued", "finished", "unknown"] as const;

// Zero values are muted. Unknown shows only when it is above zero.
export function StatusTiles({ counts, params }: { counts: FactoryCounts; params: URLSearchParams }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      {ORDER.filter((id) => id !== "unknown" || counts.unknown > 0).map((id) => (
        <Link
          key={id}
          className={`${panel} flex items-baseline justify-between space-y-0 p-3 hover:bg-accent focus-visible:outline-solid focus-visible:outline-2 ${
            id === "attention" && counts.attention > 0 ? "border-amber-500/60" : ""
          }`}
          to={workLink(params, id)}
        >
          <span className="text-sm">{categories[id]}</span>
          <strong
            className={`text-xl ${counts[id] === 0 ? "font-normal text-muted-foreground" : ""}`}
          >
            {counts[id]}
          </strong>
        </Link>
      ))}
    </div>
  );
}
