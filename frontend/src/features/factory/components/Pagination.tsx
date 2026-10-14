import { Button } from "@/components/ui/button";
import type { ListState } from "../reads";
import { Time } from "./Time";

export function Pagination<T>({
  state,
}: {
  state: ListState<T> & { more: () => void; restart: () => void };
}) {
  return (
    <div className="flex flex-wrap items-center gap-3" aria-live="polite">
      {state.paused && (
        <p className="text-sm">
          Updates are paused while you browse older results.
          {state.needsRefresh ? " The data changed. Refresh to see it." : ""}
        </p>
      )}
      {(state.data?.has_more || state.paused) && (
        <Button
          variant="outline"
          aria-disabled={
            !state.data?.has_more || (state.paused && state.refreshing)
          }
          onClick={state.data?.has_more ? state.more : () => undefined}
        >
          {!state.data?.has_more
            ? "No more results"
            : state.paused && state.refreshing
              ? "Loading more…"
              : "Load more"}
        </Button>
      )}
      <Button variant="outline" onClick={state.restart}>
        Refresh from start
      </Button>
      {state.data && (
        <>
          <span className="text-sm">
            {state.data.rows.length} loaded / {state.data.total} matching
          </span>
          <Time value={state.data.generated_at} />
        </>
      )}
    </div>
  );
}
