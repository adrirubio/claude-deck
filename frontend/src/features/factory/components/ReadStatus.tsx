import { Link } from "react-router-dom";
import { ApiHttpError } from "@/lib/api";
import type { ReadState } from "../reads";
import { anchor } from "./styles";

export function ReadStatus<T>({
  state,
  back,
}: {
  state: ReadState<T>;
  back?: { to: string; label: string };
}) {
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
      {error && state.retrying && <p>Retrying…</p>}
      {error && state.stopped && back && (
        <Link className={anchor} to={back.to}>
          {back.label}
        </Link>
      )}
    </div>
  );
}
