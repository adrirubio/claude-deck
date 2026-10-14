import { Link } from "react-router-dom";
import { RepositoryResults } from "../components/RepositoryResults";
import { destination } from "../components/styles";
import { factoryQuery } from "../filterHelpers";
import { FactoryFilters } from "../filters";
import { useFactoryFilters } from "../filterOptions";

export function RepositoriesPage() {
  const { params, ready } = useFactoryFilters();
  const query = factoryQuery(params);
  return (
    <section className="space-y-5">
      <h2 className="text-2xl font-semibold">Repositories</h2>
      <p className="text-muted-foreground">
        Where work comes from, and how it is handled. Open a repository to see or change its settings.
      </p>
      <div><Link className={destination} to="/repositories/new">Add a repository</Link></div>
      <FactoryFilters repository />
      {ready && <RepositoryResults key={query} query={query} />}
    </section>
  );
}
