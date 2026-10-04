import { Link, useParams } from "react-router-dom";
import { useProviderContext } from "@/contexts/ProviderContext";
import { harnesses } from "@/features/factory/filterHelpers";
import {
  surfaceRegistry,
  nativeAccess,
  type NativeSurface,
} from "@/features/native-settings/surfaceRegistry";
import type { AgentProviderId } from "@/types/providers";
export function HarnessesPage() {
  const { providerId } = useParams();
  const { providers, loading, error } = useProviderContext();
  const ids = Object.keys(harnesses).filter(
    (id) => !providerId || providerId === id,
  ) as AgentProviderId[];
  return (
    <section className="space-y-5">
      <h2 className="text-2xl font-semibold">
        Harnesses
        {providerId
          ? ` · ${harnesses[providerId as AgentProviderId] ?? providerId}`
          : ""}
      </h2>
      <p>
        Native configuration and existing team/session operations. Installed
        binaries do not prove session or credential readiness.
      </p>
      {loading && <p role="status">Loading harness registry…</p>}
      {error && <p role="alert">{error}</p>}
      {!ids.length && (
        <p>
          Unknown harness. <Link to="/harnesses">Show all harnesses</Link>
        </p>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        {ids.map((id) => {
          const p = providers.find((p) => p.id === id);
          return (
            <article
              key={id}
              className="space-y-3 rounded-lg border bg-card p-4"
            >
              <h3 className="text-lg font-semibold">
                <Link
                  className="text-primary underline"
                  to={`/harnesses/${id}`}
                >
                  {harnesses[id]}
                </Link>
              </h3>
              <p>
                Binary:{" "}
                {p
                  ? p.installed
                    ? `installed ${p.version ?? ""}`
                    : "missing"
                  : "unknown"}
              </p>
              <p>
                Native pages:{" "}
                {Object.keys(surfaceRegistry[id]).length
                  ? "implemented adapters listed below"
                  : "no dedicated settings adapters; integration capabilities are separate"}
              </p>
              <nav
                className="flex flex-wrap gap-3"
                aria-label={`${harnesses[id]} native surfaces`}
              >
                {Object.entries(surfaceRegistry[id]).map(([surface]) =>
                  nativeAccess(id, surface, p) ? (
                    <Link
                      className="text-primary underline"
                      key={surface}
                      to={`/harnesses/${id}/${surface}`}
                    >
                      {surface === "summary"
                        ? "Configuration summary"
                        : surface.replaceAll("-", " ")}{" "}
                      ({nativeAccess(id, surface, p)?.replaceAll("_", " ")})
                    </Link>
                  ) : (
                    <span key={surface}>
                      {surface as NativeSurface}: unavailable
                    </span>
                  ),
                )}
              </nav>
              {p && (
                <details>
                  <summary className="cursor-pointer">
                    Reported integration capabilities
                  </summary>
                  <ul className="text-sm">
                    {Object.entries(p.capability_matrix ?? {}).map(
                      ([name, value]) => (
                        <li key={name}>
                          {name}: {value?.state} · {value?.reason}
                        </li>
                      ),
                    )}
                  </ul>
                </details>
              )}
              <div className="flex flex-wrap gap-3">
                <Link className="text-primary underline" to="/teams">
                  Teams and launch planning
                </Link>
                <Link
                  className="text-primary underline"
                  to={`/agent-bridge?provider=${id}`}
                >
                  Live sessions
                </Link>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
