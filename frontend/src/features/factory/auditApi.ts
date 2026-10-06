import { apiClient } from "@/lib/api";

export interface AuditEventRead {
  id: number;
  occurred_at: string;
  recorded_at: string;
  event_kind: string;
  source: string;
  record_kind: string;
  fact_source?: string | null;
  fact_time?: string | null;
  actor_kind: string;
  actor_reference?: string | null;
  team_preset_id?: number | null;
  scope_id?: number | null;
  item_id?: number | null;
  revision_id?: number | null;
  team_context_key?: string | null;
  scope_context_key?: string | null;
  item_context_key?: string | null;
  context_snapshot?: Record<string, unknown> | null;
  correlation_id?: string | null;
  sanitized_reason?: string | null;
  before_values?: Record<string, unknown> | null;
  after_values?: Record<string, unknown> | null;
  action_outcome?: string | null;
  delivery_outcome?: string | null;
  completion_kind?: string | null;
  human_review_evidence?: Record<string, unknown> | null;
  live_links_available: boolean;
}

export interface AuditEventPage {
  items: AuditEventRead[];
  total: number;
  page: number;
  page_size: number;
  snapshot_labels: string[];
}

export interface MetricSample {
  name: string;
  counting_unit: string;
  value: number | null;
  sample_count: number;
  unknown_count: number;
  excluded_count: number;
  unknown_reasons: string[];
  source: string;
  coverage: string;
}

export interface MetricsWindow {
  window_start: string;
  window_end: string;
  filter_scope: string;
  counting_unit_note: string;
  available_interval_start?: string | null;
  available_interval_end?: string | null;
  missing_intervals: string[];
  instrumentation_start?: string | null;
  metrics: MetricSample[];
}

export async function fetchAuditEvents(params: {
  page?: number;
  pageSize?: number;
  eventKind?: string;
  teamContextKey?: string;
  scopeContextKey?: string;
  itemContextKey?: string;
}): Promise<AuditEventPage> {
  const query = new URLSearchParams();
  if (params.page) query.set("page", String(params.page));
  if (params.pageSize) query.set("page_size", String(params.pageSize));
  if (params.eventKind) query.set("event_kind", params.eventKind);
  if (params.teamContextKey) query.set("team_context_key", params.teamContextKey);
  if (params.scopeContextKey) query.set("scope_context_key", params.scopeContextKey);
  if (params.itemContextKey) query.set("item_context_key", params.itemContextKey);
  return apiClient<AuditEventPage>(`/api/v1/factory/audit-events?${query.toString()}`);
}

export async function fetchMetricsWindow(params: {
  windowStart: string;
  windowEnd: string;
  filterScope?: string;
}): Promise<MetricsWindow> {
  const query = new URLSearchParams({
    window_start: params.windowStart,
    window_end: params.windowEnd,
  });
  if (params.filterScope) query.set("filter_scope", params.filterScope);
  return apiClient<MetricsWindow>(`/api/v1/factory/metrics?${query.toString()}`);
}
