import { WorkResults } from "../components/WorkResults";
import { factoryQuery } from "../filterHelpers";
import { FactoryFilters } from "../filters";
import { useFactoryFilters } from "../filterOptions";

export function WorkPage() {
  const { params, ready } = useFactoryFilters();
  // Active work is the default: every item that is not finished.
  const withDefault = new URLSearchParams(params);
  if (!withDefault.get("category")) withDefault.set("category", "open");
  const query = factoryQuery(withDefault, true);
  return (
    <section className="space-y-5">
      <h2 className="text-2xl font-semibold">Work</h2>
      <p className="text-muted-foreground">
        Work across your teams. Open an item to see its history and actions.
      </p>
      <FactoryFilters work />
      {ready && <WorkResults key={query} query={query} />}
    </section>
  );
}
