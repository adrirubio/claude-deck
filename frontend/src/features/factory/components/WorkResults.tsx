import { useLayoutEffect, useRef } from "react";
import type { WorkProjection } from "@/types/factory";
import { useCursorList } from "../reads";
import { Pagination } from "./Pagination";
import { ReadStatus } from "./ReadStatus";
import { WorkTable } from "./WorkTable";

export function WorkResults({ query = "" }: { query?: string }) {
  const state = useCursorList<WorkProjection>(
    `factory/work-items${query ? `?${query}` : ""}`,
    "items",
    (row) => row.item.id,
  );
  const root = useRef<HTMLDivElement>(null);
  const { getPosition, rememberPosition } = state;
  useLayoutEffect(() => {
    const element = root.current;
    if (!element) return;
    const main = element.closest("main") ?? document.documentElement;
    const table = element.querySelector<HTMLElement>("[data-work-table]");
    const position = getPosition();
    if (position) {
      const link = [
        ...element.querySelectorAll<HTMLAnchorElement>("a[href]"),
      ].find(
        (candidate) =>
          candidate.getAttribute("href") === position.focusHref &&
          candidate.textContent === position.focusText,
      );
      link?.focus({ preventScroll: true });
      main.scrollTop = position.top;
      if (table) table.scrollLeft = position.left;
    }
    return () => {
      const active = document.activeElement;
      rememberPosition({
        top: main.scrollTop,
        left:
          element.querySelector<HTMLElement>("[data-work-table]")?.scrollLeft ??
          0,
        focusHref:
          active instanceof HTMLAnchorElement && element.contains(active)
            ? active.getAttribute("href")
            : null,
        focusText:
          active instanceof HTMLAnchorElement && element.contains(active)
            ? active.textContent
            : null,
      });
    };
  }, [getPosition, rememberPosition]);
  return (
    <div ref={root} className="space-y-4">
      <ReadStatus state={state} />
      {state.data && (
        <>
          {state.data.rows.length ? (
            <WorkTable rows={state.data.rows} />
          ) : (
            <p>
              No work matches these filters. Clear filters to inspect the whole
              factory.
            </p>
          )}
          <Pagination state={state} />
        </>
      )}
    </div>
  );
}
