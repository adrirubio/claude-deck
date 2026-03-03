export interface CCSession {
  tmux_target: string
  session_name: string
  window_name: string
  pane_id: string
  cwd: string
  pid: string
  status: string
}

export interface CCSessionsResponse {
  sessions: CCSession[]
  count: number
}

export interface CCPreviewResponse {
  target: string
  content: string
}

export interface CCTokenResponse {
  token: string
}

export interface SpawnSessionRequest {
  directory: string
  mode: 'plain' | 'worktree' | 'resume'
  worktree_name?: string
  session_id?: string
  project_folder?: string
  skip_permissions?: boolean
}

export interface SpawnSessionResponse {
  tmux_target: string
  session_name: string
}

export interface KillSessionResponse {
  killed: boolean
  error?: string
}
