// Plan History Browser types matching backend schemas

export interface PlanSummary {
  filename: string
  slug: string
  title: string
  excerpt: string
  modified_at: string
  size_bytes: number
  source: string
  source_label: string
  project_path?: string | null
  session_id?: string | null
  git_branch?: string | null
  step_count?: number | null
  pending_count?: number | null
  in_progress_count?: number | null
  completed_count?: number | null
  history_count?: number | null
}

export interface PlanLinkedSession {
  session_id: string
  project_folder: string
  project_name: string
  git_branch?: string
  first_seen?: string
  last_seen?: string
}

export interface PlanDetail {
  filename: string
  slug: string
  title: string
  content: string
  modified_at: string
  size_bytes: number
  headings: string[]
  code_block_count: number
  table_count: number
  linked_sessions: PlanLinkedSession[]
  source: string
  source_label: string
  project_path?: string | null
  session_id?: string | null
  git_branch?: string | null
  git_sha?: string | null
  step_count?: number | null
  pending_count?: number | null
  in_progress_count?: number | null
  completed_count?: number | null
  history_count?: number | null
}

export interface PlanSearchResult {
  filename: string
  slug: string
  title: string
  matches: string[]
  modified_at: string
  source: string
  source_label: string
}

export interface PlanListResponse {
  plans: PlanSummary[]
  total: number
}

export interface PlanDetailResponse {
  plan: PlanDetail
}

export interface PlanSearchResponse {
  results: PlanSearchResult[]
  query: string
  total: number
}

export interface PlanStatsResponse {
  total_plans: number
  oldest_date: string | null
  newest_date: string | null
  total_size_bytes: number
  source: string
  source_label: string
}
