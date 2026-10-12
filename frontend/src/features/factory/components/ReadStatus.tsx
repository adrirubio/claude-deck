import { ApiHttpError } from "@/lib/api";
import type { ReadState } from "../reads";

export function ReadStatus<T>({ state }: { state: ReadState<T> }) {
  const error = state.error;
  return (
    <div aria-live="polite" className="text-sm">
      {state.refreshing && (
        <p>{state.data ? "Refreshing observation…" : "Loading…"}</p>
      )}
      {error && (
        <p role="alert" className="rounded border border-destructive p-3">
          {state.data
            ? "Stale data — refresh failed. Last successful observation remains visible. "
            : ""}
          {error instanceof ApiHttpError && error.status === 404
            ? "Not found. "
            : ""}
          {error.message}
          {error instanceof ApiHttpError && (error.code || error.blockCode)
            ? ` (${error.code ?? error.blockCode})`
            : ""}
        </p>
      )}
    </div>
  );
}
