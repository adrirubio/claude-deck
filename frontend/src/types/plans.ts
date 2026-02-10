// Plan History Browser types matching backend schemas

export interface PlanSummary {
  filename: string
  slug: string
  title: string
  excerpt: string
  modified_at: string
  size_bytes: number
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
}

export interface PlanSearchResult {
  filename: string
  slug: string
  title: string
  matches: string[]
  modified_at: string
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
}
