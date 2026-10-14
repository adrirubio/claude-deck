import { Link } from "react-router-dom";
import { ApiHttpError } from "@/lib/api";
import type { ReadState } from "../reads";
import { anchor } from "./styles";

// The request can never succeed for this ID: the thing does not exist.
const MISSING_STATUS = [400, 404, 410, 422];

export function ReadStatus<T>({
  state,
  back,
  missing,
}: {
  state: ReadState<T>;
  back?: { to: string; label: string };
  // Name of the thing the page shows, for example "work item".
  missing?: string;
}) {
  const error = state.error;
  const absent =
    Boolean(missing) &&
    !state.data &&
    error instanceof ApiHttpError &&
    MISSING_STATUS.includes(error.status);
  return (
    <div aria-live="polite" className="text-sm">
      {/* A background refresh with data on screen shows nothing: no shift, no announcement. */}
      {state.refreshing && !state.data && <p>Loading…</p>}
      {absent && (
        <p role="alert" className="rounded border border-destructive p-3">
          This {missing} does not exist.
        </p>
      )}
      {error && !absent && (
        <p role="alert" className="rounded border border-destructive p-3">
          {state.data
            ? "Data may be out of date. The refresh failed. The last good data stays visible. "
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
          <span aria-hidden="true">‹ </span>
          {back.label}
        </Link>
      )}
    </div>
  );
}
