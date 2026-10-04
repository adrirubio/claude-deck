import { useSyncExternalStore } from "react";
import { apiClient } from "@/lib/api";

// Shared per-URL read state. No mutation, credential, owner claim or GitHub poll.
export interface ReadState<T> {
  data: T | null;
  error: Error | null;
  refreshing: boolean;
}
class Observation<T> {
  state: ReadState<T> = { data: null, error: null, refreshing: false };
  listeners = new Set<() => void>();
  timer: ReturnType<typeof setInterval> | null = null;
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
  refresh = () => {
    if (this.promise) return this.promise;
    const generation = this.generation;
    this.publish({ ...this.state, refreshing: true });
    this.promise = apiClient<T>(this.endpoint)
      .then((data) => {
        if (generation === this.generation)
          this.publish({ data, error: null, refreshing: false });
      })
      .catch((error: Error) => {
        if (generation === this.generation)
          this.publish({ ...this.state, error, refreshing: false });
      })
      .finally(() => {
        this.promise = null;
      });
    return this.promise;
  };
  visibleRefresh = () => {
    if (document.visibilityState === "visible") void this.refresh();
  };
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    if (this.listeners.size === 1) {
      this.visibleRefresh();
      this.timer = setInterval(this.visibleRefresh, 5000);
      document.addEventListener("visibilitychange", this.visibleRefresh);
    }
    return () => {
      this.listeners.delete(fn);
      if (!this.listeners.size) {
        if (this.timer) clearInterval(this.timer);
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
export function useObservation<T>(endpoint: string) {
  if (!observations.has(endpoint))
    observations.set(endpoint, new Observation(endpoint));
  const read = observations.get(endpoint)! as Observation<T>;
  const state = useSyncExternalStore(read.subscribe, read.snapshot);
  return { ...state, refresh: read.refresh };
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
  };
  listeners = new Set<() => void>();
  timer: ReturnType<typeof setInterval> | null = null;
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
      });
    } catch (error) {
      if (
        generation === this.generation &&
        (cursor || request === this.firstRequest)
      )
        this.publish({
          ...this.state,
          error: error as Error,
          refreshing: false,
        });
    }
  }
  poll = () => {
    if (
      this.state.paused ||
      this.state.refreshing ||
      document.visibilityState !== "visible"
    )
      return;
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
    });
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
      this.timer = setInterval(this.poll, 5000);
      document.addEventListener("visibilitychange", this.poll);
    }
    return () => {
      this.listeners.delete(fn);
      if (!this.listeners.size) {
        if (this.timer) clearInterval(this.timer);
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
