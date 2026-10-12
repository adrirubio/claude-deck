import { Link, useSearchParams } from "react-router-dom";
import { RepositoryResults } from "../components/RepositoryResults";
import { destination } from "../components/styles";
import { factoryQuery } from "../filterHelpers";
import { FactoryFilters } from "../filters";

export function RepositoriesPage() {
  const [params] = useSearchParams();
  const query = factoryQuery(params);
  return (
    <section className="space-y-5">
      <h2 className="text-2xl font-semibold">Repositories</h2>
      <div><Link className={destination} to="/repositories/new">Set up a repository</Link></div>
      <p>
        Each watched scope keeps its owning team and independent authority. Team
        roster harness filters may differ from Work's assigned owner filter.
      </p>
      <FactoryFilters repository />
      <RepositoryResults key={query} query={query} />
    </section>
  );
}
