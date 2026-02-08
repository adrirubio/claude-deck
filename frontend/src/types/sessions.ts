/**
 * TypeScript types for session transcripts
 */

export interface ContentBlock {
  type: string
  text?: string
  thinking?: string
  name?: string
  id?: string
  input?: Record<string, unknown>
  content?: string | Record<string, unknown> | unknown[]
  is_error?: boolean
  source?: Record<string, string>
}

export interface SessionMessage {
  type: 'user' | 'assistant'
  timestamp: string
  content: ContentBlock[]
  model?: string
  usage?: Record<string, number | Record<string, number>>
}

export interface SessionConversation {
  user_text: string
  timestamp: string
  messages: SessionMessage[]
  is_continuation: boolean
  token_count?: number
}

export interface SessionSummary {
  id: string
  project_folder: string
  project_name: string
  summary: string
  modified_at: string
  size_bytes: number
  total_messages: number
  total_tool_calls: number
}

export interface SessionDetail {
  id: string
  project_folder: string
  project_name: string
  conversations: SessionConversation[]
  total_messages: number
  total_tool_calls: number
  total_tokens?: number
  models_used: string[]
}

export interface SessionProject {
  folder: string
  name: string
  session_count: number
  most_recent: string
}

export interface SessionListResponse {
  sessions: SessionSummary[]
  total: number
}

export interface SessionProjectListResponse {
  projects: SessionProject[]
  total_sessions: number
}

export interface SessionDetailResponse {
  session: SessionDetail
  current_page: number
  total_pages: number
  prompts_per_page: number
}

export interface SessionStatsResponse {
  total_sessions: number
  sessions_today: number
  sessions_this_week: number
  most_active_project?: string
  total_messages: number
}
