/**
 * TypeScript types for context window analysis
 */

export interface ContextSnapshot {
  turn_number: number
  timestamp: string
  total_context_tokens: number
  input_tokens: number
  cache_creation_tokens: number
  cache_read_tokens: number
  output_tokens: number
  model: string
  context_percentage: number
}

export interface ContentCategory {
  category: string
  estimated_chars: number
  estimated_tokens: number
  percentage: number
}

export interface FileConsumption {
  file_path: string
  read_count: number
  total_chars: number
  estimated_tokens: number
}

export interface CacheEfficiency {
  total_cache_read: number
  total_cache_creation: number
  total_uncached: number
  hit_ratio: number
}

export interface ContextCategoryItem {
  name: string
  estimated_tokens: number
}

export interface ContextCompositionCategory {
  category: string
  estimated_tokens: number
  percentage: number
  color: string
  items?: ContextCategoryItem[]
}

export interface ContextComposition {
  categories: ContextCompositionCategory[]
  total_tokens: number
  context_limit: number
  model: string
}

export interface ContextAnalysis {
  session_id: string
  project_folder: string
  project_name: string
  model: string
  current_context_tokens: number
  max_context_tokens: number
  context_percentage: number
  snapshots: ContextSnapshot[]
  content_categories: ContentCategory[]
  file_consumptions: FileConsumption[]
  cache_efficiency: CacheEfficiency
  avg_tokens_per_turn: number
  estimated_turns_remaining: number
  context_zone: string
  total_turns: number
  composition?: ContextComposition
}

export interface ContextAnalysisResponse {
  analysis: ContextAnalysis
}

export interface ActiveSessionContext {
  session_id: string
  project_folder: string
  project_name: string
  model: string
  context_percentage: number
  current_context_tokens: number
  max_context_tokens: number
  is_active: boolean
  last_activity: string
}

export interface ActiveSessionsResponse {
  sessions: ActiveSessionContext[]
}
