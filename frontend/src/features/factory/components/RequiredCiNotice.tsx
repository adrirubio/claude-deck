import type { RequiredCIUnreadableSignal } from "@/types/agentTeams";
import { requiredCiReason } from "./requiredCiReason";

// The warning on the Work item page. It grants no action: retry and recovery
// stay in the item remedies below it.
export function RequiredCiNotice({
  signal,
  pullRequest,
}: {
  signal: RequiredCIUnreadableSignal;
  pullRequest: number | null;
}) {
  return (
    <section
      aria-label={signal.label}
      className="space-y-2 rounded-lg border border-amber-500 p-4 text-sm"
    >
      <h3 className="font-semibold">
        <span aria-hidden="true">⚠ </span>
        {signal.label}
      </h3>
      <p>
        Deck cannot read the required checks
        {pullRequest ? ` for PR #${pullRequest}` : ""}, so it cannot verify the
        change. {requiredCiReason(signal.reason)}
      </p>
      {signal.next_steps.length > 0 && (
        <ul className="list-disc space-y-1 pl-5">
          {signal.next_steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
