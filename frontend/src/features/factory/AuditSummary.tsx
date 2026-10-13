import { useState } from "react";
import { HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { GUIDE_URL, coverageSentence, headlines } from "./auditSummary";
import type { MetricsWindow } from "./auditApi";

interface AuditSummaryProps {
  metrics: MetricsWindow | null;
}

/**
 * #517: the answer to "How is delivery going?" in plain words. The coverage
 * sentence comes first, then the headline results. Each result has a short
 * definition behind a "?" button.
 */
export function AuditSummary({ metrics }: AuditSummaryProps) {
  const [openHelp, setOpenHelp] = useState<string | null>(null);
  const results = headlines(metrics);
  return (
    <section aria-labelledby="delivery-summary" className="space-y-3 rounded border p-3">
      <h3 id="delivery-summary" className="font-semibold">Delivery in this window</h3>
      <p className="text-sm"><span className="font-medium">Coverage:</span> {coverageSentence(metrics)}</p>
      {results.length === 0 ? (
        <p className="text-sm text-muted-foreground">No results loaded yet.</p>
      ) : (
        <dl className="grid grid-cols-2 gap-2 lg:grid-cols-4">
          {results.map((result) => (
            <div key={result.id} className="rounded border bg-muted/30 p-2">
              <dt className="flex items-start justify-between gap-1 text-xs text-muted-foreground">
                <span>{result.label}</span>
                <button
                  type="button"
                  aria-label={`About: ${result.label}`}
                  aria-expanded={openHelp === result.id}
                  aria-controls={`help-${result.id}`}
                  onClick={() => setOpenHelp(openHelp === result.id ? null : result.id)}
                  className="rounded p-0.5 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <HelpCircle aria-hidden="true" className="h-3.5 w-3.5" />
                </button>
              </dt>
              <dd className="text-lg font-semibold">{result.value}</dd>
              {result.detail && <dd className="text-xs text-muted-foreground">{result.detail}</dd>}
              {openHelp === result.id && (
                <dd id={`help-${result.id}`} className={cn("mt-1 text-xs")}>{result.help}</dd>
              )}
            </div>
          ))}
        </dl>
      )}
      <p className="text-xs text-muted-foreground">
        Read the full definitions in the{" "}
        <a href={GUIDE_URL} target="_blank" rel="noreferrer" className="text-primary underline">
          audit and metrics guide
        </a>
        .
      </p>
    </section>
  );
}
