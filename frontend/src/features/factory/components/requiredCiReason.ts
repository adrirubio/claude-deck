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
