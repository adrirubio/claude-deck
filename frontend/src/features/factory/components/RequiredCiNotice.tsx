import type { RequiredCIUnreadableSignal } from "@/types/agentTeams";

// Only the four fixed reason codes reach the screen. Any other value falls back
// to the "unknown" text, so a raw server string is never shown.
const REASON_TEXT: Record<RequiredCIUnreadableSignal["reason"], string> = {
  permission_missing: "The GitHub token or App has no permission to read the checks.",
  workflow_missing: "GitHub shows no workflow for the required checks.",
  api_error: "GitHub did not answer the request for the checks.",
  unknown: "Deck does not know why the checks cannot be read.",
};

export function requiredCiReason(reason: string | null | undefined) {
  return REASON_TEXT[reason as RequiredCIUnreadableSignal["reason"]] ?? REASON_TEXT.unknown;
}

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
