import { Link, useLocation, useSearchParams } from "react-router-dom";
import { buttonVariants } from "@/components/ui/button";
import { categories, harnesses } from "./filterHelpers";
import { useFactoryFilters, type FilterOption } from "./filterOptions";

const select = "h-9 rounded-md border bg-background px-2";

function NameSelect({
  label,
  all,
  options,
  value,
  onChange,
}: {
  label: string;
  all: string;
  options: FilterOption[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid gap-1 text-sm">
      {label}
      <select
        className={`${select} max-w-64`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{all}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

// Active is every item that is not finished. A link can also name one category.
const CHIPS: [string, string][] = [
  ["open", "Active"],
  ["finished", "Finished"],
  ["all", "All"],
];

function CategoryChips({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const chips = CHIPS.some(([id]) => id === value)
    ? CHIPS
    : [...CHIPS, [value, categories[value as keyof typeof categories] ?? value]];
  return (
    <div role="group" aria-label="Category" className="flex items-end gap-2">
      {chips.map(([id, label]) => (
        <button
          key={id}
          type="button"
          aria-pressed={id === value}
          onClick={() => onChange(id)}
          className={`h-9 rounded-full border px-3 text-sm ${
            id === value
              ? "border-primary bg-accent font-medium"
              : "text-muted-foreground hover:bg-accent"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

export function FactoryFilters({
  work = false,
  repository = false,
}: {
  work?: boolean;
  repository?: boolean;
}) {
  const [raw, setParams] = useSearchParams();
  const location = useLocation();
  const { params, unknown, teams, repositories } = useFactoryFilters();
  const update = (name: string, value: string) => {
    // Values that name nothing are dropped on any change.
    const next = new URLSearchParams(params);
    next.delete("cursor");
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next);
  };
  const active = ["team_id", "scope_id", "provider"].some((key) =>
    raw.has(key),
  ) || (raw.has("category") && raw.get("category") !== "open");
  const names = unknown.map((key) => (key === "team_id" ? "team" : "repository"));
  return (
    <form
      className="flex flex-wrap items-end gap-3 rounded-lg border bg-card p-3"
      onSubmit={(event) => event.preventDefault()}
      aria-label="Delivery filters"
    >
      {teams.length > 1 && (
        <NameSelect
          label="Team"
          all="All teams"
          options={teams}
          value={params.get("team_id") ?? ""}
          onChange={(value) => update("team_id", value)}
        />
      )}
      {repositories.length > 1 && (
        <NameSelect
          label="Repository"
          all="All repositories"
          options={repositories}
          value={params.get("scope_id") ?? ""}
          onChange={(value) => update("scope_id", value)}
        />
      )}
      <label className="grid gap-1 text-sm">
        {repository ? "Team roster harness" : "Assigned harness"}
        <select
          className={select}
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
        <CategoryChips
          value={params.get("category") ?? "open"}
          onChange={(value) => update("category", value === "open" ? "" : value)}
        />
      )}
      {active && (
        <Link
          className={buttonVariants({ variant: "outline" })}
          to={{ pathname: location.pathname }}
        >
          Reset filters
        </Link>
      )}
      {names.length > 0 && (
        <p role="status" className="basis-full text-sm">
          The {names.join(" and ")} in this link {names.length > 1 ? "were" : "was"} not
          found, so {names.length > 1 ? "those filters are" : "that filter is"} ignored.
        </p>
      )}
    </form>
  );
}
