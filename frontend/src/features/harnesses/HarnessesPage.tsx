import { useEffect, useState, type KeyboardEvent, type MouseEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Lock, Terminal } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { useProviderContext, NativeProviderScope } from "@/contexts/ProviderContext";
import { DashboardProvider, useDashboard } from "@/contexts/DashboardContext";
import { useProviderOperations } from "@/hooks/useProviders";
import { fetchAgentTeamPresets } from "@/features/agent-teams/api";
import { harnesses } from "@/features/factory/filterHelpers";
import { CLICKABLE_CARD } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { surfaceRegistry, nativeAccess } from "@/features/native-settings/surfaceRegistry";
import { SURFACE_GROUPS } from "@/features/harnesses/surfaceCatalog";
import { HarnessBreadcrumb } from "@/features/harnesses/HarnessNav";
import { availablePages, focusRing, useDocumentTitle } from "@/features/harnesses/harnessPages";
import { providerOperationKeys, type AgentProviderId, type AgentProviderStatus, type ProviderOperations } from "@/types/providers";


// A card shows no "unknown" or "unavailable" while the registry or its own operating catalog still loads.
function HarnessCardSkeleton({ id }: { id: AgentProviderId }) {
  return (
    <article aria-busy="true" className="min-w-0 space-y-3 rounded-lg border bg-card p-4">
      <h3 className="text-lg font-semibold">{harnesses[id]}</h3>
      <p role="status">Loading {harnesses[id]}…</p>
      <div className="space-y-2" aria-hidden="true">
        <div className="h-4 w-1/2 animate-pulse rounded bg-muted" />
        <div className="h-4 w-3/4 animate-pulse rounded bg-muted" />
        <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
        <div className="h-11 w-44 animate-pulse rounded bg-muted" />
      </div>
    </article>
  );
}

type HarnessStatus = { kind: "ready" | "setup" | "missing" | "unchecked"; label: string; reason?: string };

function harnessStatus(metadata: AgentProviderStatus | undefined, catalog: ProviderOperations | null): HarnessStatus | null {
  if (metadata && !metadata.installed) return { kind: "missing", label: "Not installed" };
  const configuration = catalog?.readiness.configuration;
  if (configuration?.state === "ready") return { kind: "ready", label: "Ready" };
  if (configuration?.state === "blocked") return { kind: "setup", label: "Needs setup", reason: configuration.checks.find(check => check.state !== "ready")?.reason };
  return catalog ? { kind: "unchecked", label: "Not checked yet" } : null;
}

// Green for ready, amber only for needs setup, neutral grey for not installed. Each colour has a light and a dark value.
const statusClass: Record<HarnessStatus["kind"], string> = {
  ready: "border-emerald-600/40 text-emerald-700 dark:text-emerald-400",
  setup: "border-amber-600/40 text-amber-700 dark:text-amber-400",
  missing: "border-border text-muted-foreground",
  unchecked: "border-border text-muted-foreground",
};

function StatusBadge({ status }: { status: HarnessStatus }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium", statusClass[status.kind])}>
      <span aria-hidden="true">{status.kind === "missing" ? "○" : "●"}</span>{status.label}
    </span>
  );
}

// Code names, access codes, credentials, session binding and the raw observation live here only.
function TechnicalDetails({ id, metadata }: { id: AgentProviderId; metadata?: AgentProviderStatus }) {
  const { catalog, refresh, refreshing } = useProviderOperations(id);
  const readiness = catalog?.readiness;
  return (
    <details className="rounded-lg border bg-card p-3">
      <summary className="cursor-pointer font-medium">Technical details</summary>
      <div className="space-y-3 pt-3">
        <p>Binary: {metadata ? metadata.installed ? `installed ${metadata.version ?? ""}${metadata.binary_path ? ` · ${metadata.binary_path}` : ""}` : "missing" : "not reported"}</p>
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
        <button type="button" className={buttonVariants({ variant: "secondary", className: "h-auto min-h-11 whitespace-normal text-left focus-visible:ring-2" })} onClick={() => { void refresh() }} disabled={refreshing}>Refresh observations</button>
        {catalog && <details>
          <summary className="cursor-pointer">Operations and conditions</summary>
          <ul className="space-y-3 pt-2 text-sm">
            {providerOperationKeys.map(key => {
              const op = catalog.operations[key];
              return <li key={key}><p className="font-medium">{key.replaceAll("_", " ")}: {op.state}</p><p>{op.reason}</p>{op.conditions.length > 0 && <p>Requires: {op.conditions.join("; ")}.</p>}</li>;
            })}
          </ul>
        </details>}
        {catalog && <p>Native pages: {Object.keys(surfaceRegistry[id]).length ? "matching implemented adapters listed below" : "no dedicated settings adapters; CLI and Mail integration support are separate"}</p>}
        {catalog && <ul className="space-y-1 text-sm" aria-label={`${harnesses[id]} native page access`}>
          {Object.keys(surfaceRegistry[id]).map(surface => {
            const access = nativeAccess(id, surface, metadata, catalog);
            return <li key={surface}>{surface}: {access ? access.replaceAll("_", " ") : "unavailable"}</li>;
          })}
        </ul>}
        {catalog && <details><summary className="cursor-pointer">Reported native capabilities</summary><ul className="text-sm">{Object.entries(catalog.native_capabilities).map(([name, value]) => <li key={name}>{name}: {value.state} · {value.reason}</li>)}</ul></details>}
      </div>
    </details>
  );
}

function Tiles({ id, metadata, catalog, withCounts }: { id: AgentProviderId; metadata?: AgentProviderStatus; catalog: ProviderOperations; withCounts: boolean }) {
  const { stats } = useDashboard({ autoFetch: withCounts });
  const providerStats = withCounts && stats?.providerId === id ? stats : null;
  const pages = availablePages(id, metadata, catalog);
  if (!pages.length) {
    return (
      <p>
        {harnesses[id]} has no settings pages in Deck. <Link className="text-primary underline" to="/teams">Open Teams</Link> or <Link className="text-primary underline" to={`/agent-bridge?provider=${id}`}>Live sessions</Link> to work with it.
      </p>
    );
  }
  return (
    <div className="space-y-6">
      {SURFACE_GROUPS.map(group => {
        const inGroup = pages.filter(page => page.info.group === group);
        if (!inGroup.length) return null;
        return (
          <section key={group} aria-labelledby={`group-${group}`} className="space-y-2">
            <h3 id={`group-${group}`} className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{group}</h3>
            <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {inGroup.map(({ surface, info, access }) => {
                const Icon = info.icon;
                const count = providerStats ? info.count?.(providerStats) : null;
                return (
                  <li key={surface} className="flex min-w-0 gap-3 rounded-lg border-2 bg-card p-3">
                    <span aria-hidden="true" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted"><Icon className="h-4 w-4" /></span>
                    <div className="min-w-0 space-y-0.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <Link data-plain="name" className={`font-semibold text-foreground hover:underline ${focusRing}`} to={`/harnesses/${id}/${surface}`}>{info.name}</Link>
                        {access === "read_only" && <span className="inline-flex items-center gap-1 rounded border px-1.5 text-xs text-muted-foreground"><Lock className="h-3 w-3" aria-hidden="true" />View only</span>}
                      </div>
                      <p className="text-sm text-muted-foreground">{info.purpose}</p>
                      {count && <p data-plain="count" className="text-xs text-muted-foreground">{count}</p>}
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function HarnessPage({ id, metadata, registryLoading }: { id: AgentProviderId; metadata?: AgentProviderStatus; registryLoading: boolean }) {
  const { state, catalog } = useProviderOperations(id);
  useDocumentTitle(`${harnesses[id]} · Claude Deck`);
  const summaryAccess = catalog ? nativeAccess(id, "summary", metadata, catalog) : null;
  if (registryLoading || state === "idle" || state === "loading") return <HarnessCardSkeleton id={id} />;
  const status = harnessStatus(metadata, catalog);
  return (
    <NativeProviderScope providerId={id} onSelect={() => undefined}>
      <div className="space-y-6">
        <HarnessBreadcrumb harnessId={id} />
        <header className="space-y-1">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-2xl font-semibold">{harnesses[id]}</h2>
            {status && <StatusBadge status={status} />}
          </div>
          {metadata?.installed && metadata.version && <p className="text-sm text-muted-foreground">Version {metadata.version}</p>}
          {metadata && !metadata.installed && <p className="text-sm text-muted-foreground">Install it on this machine to use it in a team.</p>}
        </header>
        {state === "error" && <p role="alert">Operating catalog unavailable. Readiness is unknown and native pages are unavailable.</p>}
        {catalog && (
          <DashboardProvider>
            <Tiles id={id} metadata={metadata} catalog={catalog} withCounts={summaryAccess !== null} />
          </DashboardProvider>
        )}
        <TechnicalDetails id={id} metadata={metadata} />
      </div>
    </NativeProviderScope>
  );
}

function HarnessCard({ id, metadata, registryLoading, teamCount }: { id: AgentProviderId; metadata?: AgentProviderStatus; registryLoading: boolean; teamCount: number | null }) {
  const { state, catalog } = useProviderOperations(id);
  const navigate = useNavigate();
  if (registryLoading || state === "idle" || state === "loading") return <HarnessCardSkeleton id={id} />;
  const status = harnessStatus(metadata, catalog);
  const missing = status?.kind === "missing";
  const pageCount = catalog ? availablePages(id, metadata, catalog).length : 0;
  const pages = pageCount > 0 ? `${pageCount} settings ${pageCount === 1 ? "page" : "pages"}` : "No settings pages in Deck";
  const usedBy = teamCount ? ` · used by ${teamCount} ${teamCount === 1 ? "team" : "teams"}` : "";
  const open = () => navigate(`/harnesses/${id}`);
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
  };
  const stop = (event: MouseEvent) => event.stopPropagation();
  return (
    <article
      className={cn("flex min-w-0 items-start gap-3 rounded-lg bg-card p-4 break-words", CLICKABLE_CARD)}
      tabIndex={0}
      onClick={open}
      onKeyDown={onKeyDown}
    >
      <span aria-hidden="true" className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-muted"><Terminal className="h-5 w-5" /></span>
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="flex flex-wrap items-center gap-2 text-lg font-semibold">
            {harnesses[id]}
            {status && <StatusBadge status={status} />}
          </h3>
          {!missing && metadata?.version && <span className="font-mono text-xs text-muted-foreground">v{metadata.version}</span>}
        </div>
        <p className="text-sm text-muted-foreground">{missing ? "Install it to use it in a team." : `${pages}${usedBy}`}</p>
        {status?.kind === "setup" && status.reason && <p className="line-clamp-2 text-sm text-amber-700 dark:text-amber-400">{status.reason}</p>}
        {state === "error" && <p role="alert" className="text-sm">Operating catalog unavailable. Open the harness for details.</p>}
        <Link className={cn("inline-block pt-1 text-sm font-medium text-primary hover:underline", focusRing)} to={`/harnesses/${id}`} onClick={stop}>{missing ? "How to install ›" : "Open ›"}</Link>
      </div>
    </article>
  );
}

// How many teams use each harness. It reads the public presets list. If the read fails, the cards show the page count only.
function useTeamCounts() {
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchAgentTeamPresets()
      .then(response => {
        if (cancelled) return;
        const next: Record<string, number> = {};
        for (const preset of response.presets) {
          for (const provider of new Set(preset.slots.map(slot => slot.provider))) next[provider] = (next[provider] ?? 0) + 1;
        }
        setCounts(next);
      })
      .catch(() => { if (!cancelled) setCounts(null); });
    return () => { cancelled = true; };
  }, []);
  return counts;
}

export function HarnessesPage() {
  const { providerId } = useParams();
  const { providers, loading, error } = useProviderContext();
  const ids = Object.keys(harnesses).filter(id => !providerId || providerId === id) as AgentProviderId[];
  const teamCounts = useTeamCounts();
  const single = providerId && ids.length === 1 ? ids[0] : null;
  useDocumentTitle(single ? null : "Harnesses · Claude Deck");
  return <section className="space-y-5">
    {!single && <HarnessBreadcrumb />}
    {!single && <h2 className="text-2xl font-semibold">Harnesses{providerId ? ` · ${harnesses[providerId as AgentProviderId] ?? providerId}` : ""}</h2>}
    {!single && <p>The agent tools on this machine. Open one to see its settings pages.</p>}
    {loading && <p role="status">Loading harness registry…</p>}
    {error && <p role="alert">{error}</p>}
    {!ids.length && <p>Unknown harness. <Link to="/harnesses">Show all harnesses</Link></p>}
    {!error && single && <HarnessPage id={single} metadata={providers.find(p => p.id === single)} registryLoading={loading} />}
    {!error && !single && <div className="grid gap-4 lg:grid-cols-2">{ids.map(id => <HarnessCard key={id} id={id} metadata={providers.find(p => p.id === id)} registryLoading={loading} teamCount={teamCounts?.[id] ?? null} />)}</div>}
  </section>;
}
