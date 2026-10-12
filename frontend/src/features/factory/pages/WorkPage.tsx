import { WorkResults } from "../components/WorkResults";
import { factoryQuery } from "../filterHelpers";
import { FactoryFilters } from "../filters";
import { useFactoryFilters } from "../filterOptions";

export function WorkPage() {
  const { params, ready } = useFactoryFilters();
  const query = factoryQuery(params, true);
  return (
    <section className="space-y-5">
      <h2 className="text-2xl font-semibold">Work</h2>
      <p>
        Assigned harness filters describe the current owner slot. Finished means
        tracking ended; delivery and human review require evidence.
      </p>
      <FactoryFilters work />
      {ready && <WorkResults key={query} query={query} />}
    </section>
  );
}
