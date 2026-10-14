import { useCallback, useMemo, useRef, useSyncExternalStore } from "react";
import { ApiHttpError, apiClient } from "@/lib/api";

// Shared per-URL read state. No mutation, credential, owner claim or GitHub poll.
export interface ReadState<T> {
  data: T | null;
  error: Error | null;
  refreshing: boolean;
  // A transient error: the next read is scheduled.
  retrying: boolean;
  // A permanent error: polling stopped until a manual refresh.
  stopped: boolean;
}
const POLL_MS = 5000;
const RETRY_MS = [5000, 10000, 30000, 60000];
// The request will fail again until the URL or the server data changes.
const PERMANENT = new Set([400, 401, 404, 410, 422]);
function isPermanent(error: unknown) {
  return error instanceof ApiHttpError && PERMANENT.has(error.status);
}
function retryDelay(failures: number) {
  return RETRY_MS[Math.min(failures, RETRY_MS.length) - 1];
}
class Observation<T> {
  state: ReadState<T> = {
    data: null,
    error: null,
    refreshing: false,
    retrying: false,
    stopped: false,
  };
  listeners = new Set<() => void>();
  timer: ReturnType<typeof setTimeout> | null = null;
  failures = 0;
  generation = 0;
  promise: Promise<void> | null = null;
  readonly endpoint: string;
  constructor(endpoint: string) {
    this.endpoint = endpoint;
  }
  publish(state: ReadState<T>) {
    this.state = state;
    this.listeners.forEach((fn) => fn());
  }
  schedule(delay: number | null) {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (delay !== null && this.listeners.size)
      this.timer = setTimeout(this.tick, delay);
  }
  tick = () => {
    this.timer = null;
    if (document.visibilityState === "visible") void this.refresh();
    else this.schedule(POLL_MS);
  };
  refresh = () => {
    if (this.promise) return this.promise;
    const generation = this.generation;
    this.publish({ ...this.state, refreshing: true });
    this.promise = apiClient<T>(this.endpoint)
      .then((data) => {
        if (generation !== this.generation) return;
        this.failures = 0;
        this.publish({
          data,
          error: null,
          refreshing: false,
          retrying: false,
          stopped: false,
        });
        this.schedule(POLL_MS);
      })
      .catch((error: Error) => {
        if (generation !== this.generation) return;
        const stopped = isPermanent(error);
        this.failures = stopped ? 0 : this.failures + 1;
        this.publish({
          ...this.state,
          error,
          refreshing: false,
          retrying: !stopped,
          stopped,
        });
        this.schedule(stopped ? null : retryDelay(this.failures));
      })
      .finally(() => {
        this.promise = null;
      });
    return this.promise;
  };
  visibleRefresh = () => {
    if (document.visibilityState === "visible" && !this.state.stopped)
      void this.refresh();
  };
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    if (this.listeners.size === 1) {
      if (!this.state.stopped) this.tick();
      document.addEventListener("visibilitychange", this.visibleRefresh);
    }
    return () => {
      this.listeners.delete(fn);
      if (!this.listeners.size) {
        this.schedule(null);
        document.removeEventListener("visibilitychange", this.visibleRefresh);
        queueMicrotask(() => {
          if (!this.listeners.size) {
            this.generation++;
            if (observations.get(this.endpoint) === this)
              observations.delete(this.endpoint);
          }
        });
      }
    };
  };
  snapshot = () => this.state;
}
const observations = new Map<string, Observation<unknown>>();
// A null endpoint holds the read until the caller can build a valid URL.
const IDLE: ReadState<never> = {
  data: null,
  error: null,
  refreshing: true,
  retrying: false,
  stopped: false,
};
const idleRead = {
  subscribe: () => () => undefined,
  snapshot: () => IDLE,
  refresh: () => Promise.resolve(),
};
export function useObservation<T>(endpoint: string | null) {
  let read: Pick<Observation<T>, "subscribe" | "snapshot" | "refresh">;
  if (endpoint === null) read = idleRead;
  else {
    if (!observations.has(endpoint))
      observations.set(endpoint, new Observation(endpoint));
    read = observations.get(endpoint)! as Observation<T>;
  }
  const state = useSyncExternalStore(read.subscribe, read.snapshot) as ReadState<T>;
  return { ...state, refresh: read.refresh };
}

// Several reads at once, for a page that combines the same data as its cards.
// Each endpoint keeps its own shared state, so a card that reads one of them
// adds no request. The snapshot stays the same object until one state changes.
export function useObservations<T>(endpoints: string[]) {
  const key = endpoints.join("\n");
  const reads = useMemo(
    () =>
      key
        ? key.split("\n").map((endpoint) => {
            if (!observations.has(endpoint))
              observations.set(endpoint, new Observation(endpoint));
            return observations.get(endpoint)! as Observation<T>;
          })
        : [],
    [key],
  );
  const last = useRef<ReadState<T>[]>([]);
  const subscribe = useCallback(
    (listener: () => void) => {
      const stops = reads.map((read) => read.subscribe(listener));
      return () => stops.forEach((stop) => stop());
    },
    [reads],
  );
  const snapshot = useCallback(() => {
    const next = reads.map((read) => read.snapshot());
    const previous = last.current;
    if (previous.length === next.length && previous.every((state, i) => state === next[i]))
      return previous;
    last.current = next;
    return next;
  }, [reads]);
  const states = useSyncExternalStore(subscribe, snapshot);
  const refresh = useCallback(
    () => Promise.all(reads.map((read) => read.refresh())).then(() => undefined),
    [reads],
  );
  return { states, refresh };
}

export interface Page<T> {
  generated_at: string;
  total: number;
  has_more: boolean;
  next_cursor: string | null;
  rows: T[];
}
export interface ListState<T> extends ReadState<Page<T>> {
  paused: boolean;
  needsRefresh: boolean;
}
export interface ListPosition {
  top: number;
  left: number;
  focusHref: string | null;
  focusText: string | null;
}
class CursorList<T> {
  position: ListPosition | null = null;
  getPosition = () => this.position;
  rememberPosition = (position: ListPosition) => {
    if (this.state.paused) this.position = position;
  };
  state: ListState<T> = {
    data: null,
    error: null,
    refreshing: false,
    paused: false,
    needsRefresh: false,
    retrying: false,
    stopped: false,
  };
  listeners = new Set<() => void>();
  timer: ReturnType<typeof setTimeout> | null = null;
  failures = 0;
  generation = 0;
  firstRequest = 0;
  readonly endpoint: string;
  readonly rowsKey: string;
  readonly id: (row: T) => number;
  constructor(endpoint: string, rowsKey: string, id: (row: T) => number) {
    this.endpoint = endpoint;
    this.rowsKey = rowsKey;
    this.id = id;
  }
  publish(state: ListState<T>) {
    this.state = state;
    this.listeners.forEach((fn) => fn());
  }
  async fetchPage(cursor: string | null, generation: number, request: number) {
    const endpoint =
      this.endpoint +
      (cursor
        ? `${this.endpoint.includes("?") ? "&" : "?"}cursor=${encodeURIComponent(cursor)}`
        : "");
    try {
      const raw = await apiClient<Record<string, unknown>>(endpoint);
      if (
        generation !== this.generation ||
        (!cursor && request !== this.firstRequest)
      )
        return;
      const rows = raw[this.rowsKey] as T[];
      const combined = cursor
        ? [...(this.state.data?.rows ?? []), ...rows]
        : rows;
      const unique = [
        ...new Map(combined.map((row) => [this.id(row), row])).values(),
      ];
      this.publish({
        ...this.state,
        data: {
          generated_at: raw.generated_at as string,
          total: raw.total as number,
          has_more: raw.has_more as boolean,
          next_cursor: raw.next_cursor as string | null,
          rows: unique,
        },
        error: null,
        refreshing: false,
        retrying: false,
        stopped: false,
      });
      if (!cursor) {
        this.failures = 0;
        this.schedule(POLL_MS);
      }
    } catch (error) {
      if (
        generation === this.generation &&
        (cursor || request === this.firstRequest)
      ) {
        // A failed older page is shown; only a first-page read retries.
        const stopped = !cursor && isPermanent(error);
        const retrying = !cursor && !stopped;
        this.failures = retrying ? this.failures + 1 : 0;
        this.publish({
          ...this.state,
          error: error as Error,
          refreshing: false,
          retrying,
          stopped,
        });
        if (!cursor) this.schedule(retrying ? retryDelay(this.failures) : null);
      }
    }
  }
  schedule(delay: number | null) {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (delay !== null && this.listeners.size)
      this.timer = setTimeout(this.tick, delay);
  }
  tick = () => {
    this.timer = null;
    this.poll();
  };
  poll = () => {
    if (this.state.stopped) return;
    if (
      this.state.paused ||
      this.state.refreshing ||
      document.visibilityState !== "visible"
    ) {
      this.schedule(POLL_MS);
      return;
    }
    this.publish({ ...this.state, refreshing: true });
    void this.fetchPage(null, this.generation, ++this.firstRequest);
  };
  more = () => {
    const cursor = this.state.data?.next_cursor;
    if (!cursor || (this.state.refreshing && this.state.paused)) return;
    // Synchronous generation change prevents an in-flight first page from landing.
    this.generation++;
    this.publish({ ...this.state, paused: true, refreshing: true });
    void this.fetchPage(cursor, this.generation, this.firstRequest);
  };
  restart = () => {
    this.position = null;
    this.generation++;
    this.publish({
      data: null,
      error: null,
      paused: false,
      refreshing: false,
      needsRefresh: false,
      retrying: false,
      stopped: false,
    });
    this.failures = 0;
    this.poll();
  };
  markDirty = () => this.publish({ ...this.state, needsRefresh: true });
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    if (this.listeners.size === 1) {
      // A different URL in this list family is an explicit filter change.
      // Detail navigation leaves the current paused URL cached without polling.
      const family = this.endpoint.split("?")[0];
      lists.forEach((list, endpoint) => {
        if (
          endpoint !== this.endpoint &&
          endpoint.split("?")[0] === family &&
          !list.listeners.size
        ) {
          list.generation++;
          lists.delete(endpoint);
        }
      });
      this.poll();
      document.addEventListener("visibilitychange", this.poll);
    }
    return () => {
      this.listeners.delete(fn);
      if (!this.listeners.size) {
        this.schedule(null);
        document.removeEventListener("visibilitychange", this.poll);
        queueMicrotask(() => {
          if (!this.listeners.size) {
            if (!this.state.paused) {
              this.generation++;
              if (lists.get(this.endpoint) === this)
                lists.delete(this.endpoint);
            }
            // A paused page may still be fetching its next cursor. Let it finish
            // while detached; no timers remain and detail actions can mark it dirty.
          }
        });
      }
    };
  };
  snapshot = () => this.state;
}
const lists = new Map<string, CursorList<unknown>>();
export function useCursorList<T>(
  endpoint: string,
  rowsKey: string,
  id: (row: T) => number,
) {
  if (!lists.has(endpoint))
    lists.set(
      endpoint,
      new CursorList(endpoint, rowsKey, id as (row: unknown) => number),
    );
  const list = lists.get(endpoint)! as CursorList<T>;
  return {
    ...useSyncExternalStore(list.subscribe, list.snapshot),
    more: list.more,
    restart: list.restart,
    getPosition: list.getPosition,
    rememberPosition: list.rememberPosition,
  };
}
export function markWorkListsDirty() {
  lists.forEach((list, endpoint) => {
    if (endpoint.startsWith("factory/work-items")) list.markDirty();
  });
}
// Used by fixture tests to isolate shared read generations.
export function resetFactoryReads() {
  observations.clear();
  lists.clear();
}
