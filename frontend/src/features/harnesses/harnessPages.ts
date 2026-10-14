import { useEffect } from "react";
import { nativeAccess, surfaceRegistry, type NativeSurface } from "@/features/native-settings/surfaceRegistry";
import { surfaceInfo } from "@/features/harnesses/surfaceCatalog";
import type { AgentProviderId, AgentProviderStatus, ProviderOperations } from "@/types/providers";

export const focusRing = "rounded-sm focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

/** The pages that a harness has, with the access that the loaded catalog grants. The harness page and the sub-navigation both read this list. */
export function availablePages(id: AgentProviderId, metadata: AgentProviderStatus | undefined, catalog: ProviderOperations) {
  return (Object.keys(surfaceInfo) as NativeSurface[])
    .filter(surface => surfaceRegistry[id][surface])
    .map(surface => ({ surface, info: surfaceInfo[surface]!, access: nativeAccess(id, surface, metadata, catalog) }))
    .filter((page): page is typeof page & { access: NonNullable<typeof page.access> } => page.access !== null);
}

/** Sets the browser tab title while the page is shown. It restores the previous title when the page goes away. */
export function useDocumentTitle(title: string | null) {
  useEffect(() => {
    if (!title) return;
    const previous = document.title;
    document.title = title;
    return () => { document.title = previous; };
  }, [title]);
}
