import { Link } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import { harnesses } from "@/features/factory/filterHelpers";
import { SURFACE_GROUPS } from "@/features/harnesses/surfaceCatalog";
import { availablePages, focusRing } from "@/features/harnesses/harnessPages";
import type { AgentProviderId, AgentProviderStatus, ProviderOperations } from "@/types/providers";

/** Harnesses › Claude Code › MCP servers. Every part except the current one is a link. */
export function HarnessBreadcrumb({ harnessId, page }: { harnessId?: AgentProviderId; page?: string }) {
  const link = `${focusRing} hover:underline`;
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground">
        <li>{harnessId ? <Link className={link} to="/harnesses">Harnesses</Link> : <span aria-current="page" className="font-medium text-foreground">Harnesses</span>}</li>
        {harnessId && <>
          <li aria-hidden="true">›</li>
          <li>{page ? <Link className={link} to={`/harnesses/${harnessId}`}>{harnesses[harnessId]}</Link> : <span aria-current="page" className="font-medium text-foreground">{harnesses[harnessId]}</span>}</li>
        </>}
        {harnessId && page && <>
          <li aria-hidden="true">›</li>
          <li><span aria-current="page" className="font-medium text-foreground">{page}</span></li>
        </>}
      </ol>
    </nav>
  );
}

/** The pages of one harness, grouped as on the harness page, with the current page marked. */
export function HarnessSubNav({ harnessId, metadata, catalog, current }: { harnessId: AgentProviderId; metadata?: AgentProviderStatus; catalog: ProviderOperations | null; current: string }) {
  const pages = catalog ? availablePages(harnessId, metadata, catalog) : [];
  return (
    <nav aria-label={`${harnesses[harnessId]} pages`} className="space-y-4 text-sm md:border-r md:pr-3">
      <Link className={cn("inline-flex items-center gap-1 text-muted-foreground hover:underline", focusRing)} to={`/harnesses/${harnessId}`}><ChevronLeft className="h-3 w-3" aria-hidden="true" />{harnesses[harnessId]}</Link>
      {SURFACE_GROUPS.map(group => {
        const inGroup = pages.filter(page => page.info.group === group);
        if (!inGroup.length) return null;
        return (
          <div key={group} className="space-y-1">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{group}</p>
            <ul className="space-y-0.5">
              {inGroup.map(({ surface, info }) => (
                <li key={surface}>
                  <Link
                    to={`/harnesses/${harnessId}/${surface}`}
                    aria-current={surface === current ? "page" : undefined}
                    className={cn("block rounded border-l-4 px-2 py-1.5 hover:bg-accent", focusRing, surface === current ? "border-primary bg-accent font-semibold text-foreground" : "border-transparent text-muted-foreground")}
                  >{info.name}</Link>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}
