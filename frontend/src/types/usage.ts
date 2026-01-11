/**
 * TypeScript types for usage tracking
 */

export interface TokenCounts {
  input_tokens: number
  output_tokens: number
  cache_creation_tokens: number
  cache_read_tokens: number
}

export interface ModelBreakdown {
  model: string
  input_tokens: number
  output_tokens: number
  cache_creation_tokens: number
  cache_read_tokens: number
  cost: number
}

export interface DailyUsage {
  date: string // YYYY-MM-DD
  input_tokens: number
  output_tokens: number
  cache_creation_tokens: number
  cache_read_tokens: number
  total_cost: number
  models_used: string[]
  model_breakdowns: ModelBreakdown[]
  project?: string
}

export interface SessionUsage {
  session_id: string
  project_path: string
  input_tokens: number
  output_tokens: number
  cache_creation_tokens: number
  cache_read_tokens: number
  total_cost: number
  last_activity: string // YYYY-MM-DD
  versions: string[]
  models_used: string[]
  model_breakdowns: ModelBreakdown[]
}

export interface MonthlyUsage {
  month: string // YYYY-MM
  input_tokens: number
  output_tokens: number
  cache_creation_tokens: number
  cache_read_tokens: number
  total_cost: number
  models_used: string[]
  model_breakdowns: ModelBreakdown[]
  project?: string
}

export interface SessionBlock {
  id: string // ISO timestamp of block start
  start_time: string // ISO timestamp
  end_time: string // ISO timestamp (start + 5 hours)
  actual_end_time?: string // Last activity in block
  is_active: boolean
  is_gap: boolean
  input_tokens: number
  output_tokens: number
  cache_creation_tokens: number
  cache_read_tokens: number
  cost_usd: number
  models: string[]
  // Projections for active blocks
  burn_rate_tokens_per_minute?: number
  burn_rate_cost_per_hour?: number
  projected_total_tokens?: number
  projected_total_cost?: number
  remaining_minutes?: number
}

export interface UsageSummary {
  total_cost: number
  total_input_tokens: number
  total_output_tokens: number
  total_cache_creation_tokens: number
  total_cache_read_tokens: number
  total_tokens: number
  project_count: number
  session_count: number
  models_used: string[]
  date_range_start?: string
  date_range_end?: string
}

// API Response types

export interface DailyUsageListResponse {
  data: DailyUsage[]
  totals: TokenCounts
  total_cost: number
}

export interface SessionUsageListResponse {
  data: SessionUsage[]
  totals: TokenCounts
  total_cost: number
  total: number
}

export interface MonthlyUsageListResponse {
  data: MonthlyUsage[]
  totals: TokenCounts
  total_cost: number
}

export interface BlockUsageListResponse {
  data: SessionBlock[]
  active_block?: SessionBlock
  totals: TokenCounts
  total_cost: number
}

export interface UsageSummaryResponse {
  summary: UsageSummary
}
