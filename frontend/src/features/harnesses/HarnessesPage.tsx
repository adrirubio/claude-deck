import { Link, useParams } from "react-router-dom";
import { useProviderContext } from "@/contexts/ProviderContext";
import { useProviderOperations } from "@/hooks/useProviders";
import { harnesses } from "@/features/factory/filterHelpers";
import { surfaceRegistry, nativeAccess } from "@/features/native-settings/surfaceRegistry";
import { providerOperationKeys, type AgentProviderId, type AgentProviderStatus } from "@/types/providers";

function HarnessCard({ id, metadata }: { id: AgentProviderId; metadata?: AgentProviderStatus }) {
  const { state, catalog, refresh, refreshing } = useProviderOperations(id);
  const readiness = catalog?.readiness;
  return (
    <article className="min-w-0 space-y-3 rounded-lg border bg-card p-4 break-words">
      <h3 className="text-lg font-semibold">
        <Link className="text-primary underline" to={`/harnesses/${id}`}>{harnesses[id]}</Link>
      </h3>
      <p>Binary: {metadata ? metadata.installed ? `installed ${metadata.version ?? ""}` : "missing" : "unknown"}</p>
      {(state === "idle" || state === "loading") && <p role="status">Loading operating catalog…</p>}
      {state === "error" && <p role="alert">Operating catalog unavailable. Readiness is unknown and native pages are unavailable.</p>}
      <dl className="space-y-2 text-sm" aria-label={`${harnesses[id]} readiness`}>
        <div>
          <dt className="font-medium">Configuration</dt>
          <dd>{readiness?.configuration.state === "ready" ? "Configured for launch" : readiness?.configuration.state === "blocked" ? "Configuration blocked" : "Configuration unknown"}</dd>
          {readiness?.configuration.checks.map(check => <dd key={check.code}>{check.reason}</dd>)}
        </div>
        <div><dt className="font-medium">Credentials</dt><dd>{readiness?.credentials.state ?? "unknown"} · {readiness?.credentials.reason ?? "Credentials not checked; configuration does not prove model access."}</dd></div>
        <div><dt className="font-medium">Session</dt><dd>{readiness?.session.state ?? "unknown"} · {readiness?.session.reason ?? "No team slot selected; a generic provider card cannot establish a worker binding."}</dd></div>
      </dl>
      {readiness && <p className="text-xs text-muted-foreground">Observation: {readiness.probe_state} · {new Date(readiness.observed_at).toLocaleString()}. {readiness.probe_state === "pending" ? "Local checks are still pending." : readiness.probe_state === "failed" ? "Local checks could not complete; uncertain results remain unknown." : "Local configuration checks do not contact a model."}</p>}
      <button type="button" className="text-primary underline" onClick={() => { void refresh() }} disabled={refreshing}>Refresh observations</button>
      {catalog && <details>
        <summary className="cursor-pointer">Operations and conditions</summary>
        <ul className="space-y-3 pt-2 text-sm">
          {providerOperationKeys.map(key => {
            const op = catalog.operations[key];
            return <li key={key}><p className="font-medium">{key.replaceAll("_", " ")}: {op.state}</p><p>{op.reason}</p>{op.conditions.length > 0 && <p>Requires: {op.conditions.join("; ")}.</p>}</li>;
          })}
        </ul>
      </details>}
      <p>Native pages: {Object.keys(surfaceRegistry[id]).length ? "matching implemented adapters listed below" : "no dedicated settings adapters; CLI and Mail integration support are separate"}</p>
      <nav className="flex flex-wrap gap-3 text-sm" aria-label={`${harnesses[id]} native surfaces`}>
        {Object.keys(surfaceRegistry[id]).map(surface => {
          const access = catalog && nativeAccess(id, surface, metadata, catalog);
          return access ? <Link className="text-primary underline" key={surface} to={`/harnesses/${id}/${surface}`}>{surface === "summary" ? "Configuration summary" : surface.replaceAll("-", " ")} ({access.replaceAll("_", " ")})</Link> : <span key={surface}>{surface}: unavailable</span>;
        })}
      </nav>
      {catalog && <details><summary className="cursor-pointer">Reported native capabilities</summary><ul className="text-sm">{Object.entries(catalog.native_capabilities).map(([name, value]) => <li key={name}>{name}: {value.state} · {value.reason}</li>)}</ul></details>}
      <div className="flex flex-wrap gap-3 text-sm">
        <Link className="text-primary underline" to="/teams">Teams and launch planning</Link>
        <Link className="text-primary underline" to={`/agent-bridge?provider=${id}`}>Live sessions</Link>
      </div>
    </article>
  );
}

export function HarnessesPage() {
  const { providerId } = useParams();
  const { providers, loading, error } = useProviderContext();
  const ids = Object.keys(harnesses).filter(id => !providerId || providerId === id) as AgentProviderId[];
  return <section className="space-y-5">
    <h2 className="text-2xl font-semibold">Harnesses{providerId ? ` · ${harnesses[providerId as AgentProviderId] ?? providerId}` : ""}</h2>
    <p>Operations, local launch configuration and native pages for every harness. Credential access and a verified worker binding are separate observations.</p>
    {loading && <p role="status">Loading harness registry…</p>}
    {error && <p role="alert">{error}</p>}
    {!ids.length && <p>Unknown harness. <Link to="/harnesses">Show all harnesses</Link></p>}
    <div className="grid gap-4 lg:grid-cols-2">{ids.map(id => <HarnessCard key={id} id={id} metadata={error ? undefined : providers.find(p => p.id === id)} />)}</div>
  </section>;
}
