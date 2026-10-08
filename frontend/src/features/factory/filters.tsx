import { useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";

import { categories, harnesses } from "./filterHelpers";
export function FactoryFilters({
  work = false,
  repository = false,
}: {
  work?: boolean;
  repository?: boolean;
}) {
  const [params, setParams] = useSearchParams();
  const update = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    next.delete("cursor");
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next);
  };
  return (
    <form
      className="flex flex-wrap items-end gap-3 rounded-lg border bg-card p-3"
      onSubmit={(event) => event.preventDefault()}
      aria-label="Delivery filters"
    >
      {["team_id", "scope_id"].map((name) => (
        <label key={name} className="grid gap-1 text-sm">
          {name === "team_id" ? "Team ID" : "Repository scope ID"}
          <input
            className="h-9 w-36 rounded-md border bg-background px-2"
            inputMode="numeric"
            value={params.get(name) ?? ""}
            onChange={(event) => update(name, event.target.value)}
          />
        </label>
      ))}
      <label className="grid gap-1 text-sm">
        {repository ? "Team roster harness" : "Assigned harness"}
        <select
          className="h-9 rounded-md border bg-background px-2"
          value={params.get("provider") ?? ""}
          onChange={(event) => update("provider", event.target.value)}
        >
          <option value="">All harnesses</option>
          {Object.entries(harnesses).map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {work && (
        <label className="grid gap-1 text-sm">
          Category
          <select
            className="h-9 rounded-md border bg-background px-2"
            value={params.get("category") ?? "all"}
            onChange={(event) => update("category", event.target.value)}
          >
            {Object.entries(categories).map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </label>
      )}
      <Button type="button" variant="outline" onClick={() => setParams({})}>
        Reset filters
      </Button>
    </form>
  );
}
