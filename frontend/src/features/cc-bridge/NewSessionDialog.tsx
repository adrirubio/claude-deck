import { useState, useEffect, useMemo, useRef, type KeyboardEvent } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { MODAL_SIZES } from '@/lib/constants'
import { claudeProjectFolderFromPath, cn } from '@/lib/utils'
import { formatTimestamp } from '@/features/usage/utils'
import type { ProjectResponse } from '@/types/projects'
import { spawnSession } from './api'
import { useSessionsApi } from '@/hooks/useSessionsApi'
import { fetchProviderLaunchOptions } from '@/hooks/useProviders'
import { useProjectContext } from '@/contexts/ProjectContext'
import { useProviderContext } from '@/contexts/ProviderContext'
import type { AgentProviderId, ProviderLaunchOptionsResponse } from '@/types/providers'
import type { SlotLaunchOptions } from '@/types/agentTeams'
import { ProviderLaunchOptionsFields } from '@/features/providers/ProviderLaunchOptionsFields'
import type {
  SpawnSessionRequest,
} from './types'
import type { SessionSummary } from '@/types/sessions'

type Mode = 'plain' | 'worktree' | 'resume' | 'fork'

interface NewSessionDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSpawned: (tmuxTarget: string) => void
  initialProvider?: AgentProviderId
}

const MODE_OPTIONS: { value: Mode; label: string }[] = [
  { value: 'plain', label: 'Plain' },
  { value: 'worktree', label: 'Worktree' },
  { value: 'resume', label: 'Resume' },
]

const CODEX_MODE_OPTIONS: { value: Mode; label: string }[] = [
  { value: 'plain', label: 'New' },
  { value: 'resume', label: 'Resume' },
  { value: 'fork', label: 'Fork' },
]

const COPILOT_MODE_OPTIONS: { value: Mode; label: string }[] = [
  { value: 'plain', label: 'New' },
  { value: 'resume', label: 'Resume' },
]

const OPENCODE_MODE_OPTIONS: { value: Mode; label: string }[] = [
  { value: 'plain', label: 'New' },
  { value: 'resume', label: 'Resume' },
]

const PLATFORM_STORAGE_KEY = 'cc-bridge.platform'
const DEFAULT_LAUNCH_OPTIONS: SlotLaunchOptions = { no_alt_screen: true }

type Platform = 'anthropic' | 'bedrock'

interface RememberedPlatform {
  platform: Platform
  aws_region: string
  aws_profile: string
  bedrock_model: string
}

function loadRememberedPlatform(): RememberedPlatform {
  const fallback: RememberedPlatform = { platform: 'anthropic', aws_region: '', aws_profile: '', bedrock_model: '' }
  try {
    const raw = localStorage.getItem(PLATFORM_STORAGE_KEY)
    if (!raw) return fallback
    const parsed = JSON.parse(raw) as Partial<RememberedPlatform>
    return {
      platform: parsed.platform === 'bedrock' ? 'bedrock' : 'anthropic',
      aws_region: typeof parsed.aws_region === 'string' ? parsed.aws_region : '',
      aws_profile: typeof parsed.aws_profile === 'string' ? parsed.aws_profile : '',
      bedrock_model: typeof parsed.bedrock_model === 'string' ? parsed.bedrock_model : '',
    }
  } catch {
    return fallback
  }
}

function matchesProjectSearch(project: ProjectResponse, query: string) {
  const terms = query
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)

  if (terms.length === 0) return true

  const searchable = `${project.name} ${project.path}`.toLowerCase()
  return terms.every((term) => searchable.includes(term))
}

function stringOption(options: SlotLaunchOptions, key: keyof SlotLaunchOptions) {
  const value = options[key]
  return typeof value === 'string' ? value : ''
}

function boolOption(options: SlotLaunchOptions, key: keyof SlotLaunchOptions) {
  return options[key] === true
}

function withDefaultLaunchOptions(options: SlotLaunchOptions = {}) {
  return { ...DEFAULT_LAUNCH_OPTIONS, ...options }
}

export function NewSessionDialog({ open, onOpenChange, onSpawned, initialProvider }: NewSessionDialogProps) {
  const { providers, selectedProviderId } = useProviderContext()
  const defaultProvider = initialProvider ?? selectedProviderId
  const [provider, setProvider] = useState<AgentProviderId>(defaultProvider)
  const [directory, setDirectory] = useState('')
  const [projectSearch, setProjectSearch] = useState('')
  const [mode, setMode] = useState<Mode>('plain')
  const [worktreeName, setWorktreeName] = useState('')
  const [skipPermissions, setSkipPermissions] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [launchOptions, setLaunchOptions] = useState<SlotLaunchOptions>(() => ({ ...DEFAULT_LAUNCH_OPTIONS }))
  const [codexSessionId, setCodexSessionId] = useState('')
  const [useLast, setUseLast] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [recentSessions, setRecentSessions] = useState<SessionSummary[]>([])
  const [selectedSession, setSelectedSession] = useState<SessionSummary | null>(null)
  const [loadingSessions, setLoadingSessions] = useState(false)
  const [launchDescriptor, setLaunchDescriptor] = useState<ProviderLaunchOptionsResponse | null>(null)
  const [launchDescriptorError, setLaunchDescriptorError] = useState<string | null>(null)
  const projectSearchRef = useRef<HTMLInputElement>(null)
  const projectOptionRefs = useRef<Array<HTMLButtonElement | null>>([])

  const { listSessions } = useSessionsApi()
  const { projects, activeProject } = useProjectContext()
  const isClaude = provider === 'claude-code'
  const isCodex = provider === 'codex-cli'
  const isCopilot = provider === 'copilot-cli'
  const isOpenCode = provider === 'opencode-cli'
  const supportsPlatform = launchDescriptor?.bedrock_supported ?? false
  const isBedrock = supportsPlatform && launchOptions.platform === 'bedrock'
  const modeOptions = isOpenCode
    ? OPENCODE_MODE_OPTIONS
    : isCopilot
      ? COPILOT_MODE_OPTIONS
      : isCodex
        ? CODEX_MODE_OPTIONS
        : MODE_OPTIONS
  const filteredProjects = useMemo(
    () => projects.filter((project) => matchesProjectSearch(project, projectSearch)),
    [projects, projectSearch],
  )
  const resumeProjectPath = directory.trim()
  const resumeProjectFolder = resumeProjectPath
    ? claudeProjectFolderFromPath(resumeProjectPath)
    : undefined

  function selectProject(project: ProjectResponse) {
    setDirectory(project.path)
    setSelectedSession(null)
    setError(null)
  }

  function focusProjectOption(index: number) {
    projectOptionRefs.current[index]?.focus()
  }

  function handleProjectSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown' && filteredProjects.length > 0) {
      event.preventDefault()
      focusProjectOption(0)
      return
    }

    if (event.key === 'Enter' && filteredProjects.length === 1) {
      event.preventDefault()
      selectProject(filteredProjects[0])
    }
  }

  function handleProjectOptionKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      focusProjectOption(Math.min(index + 1, filteredProjects.length - 1))
      return
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault()
      if (index === 0) {
        projectSearchRef.current?.focus()
      } else {
        focusProjectOption(index - 1)
      }
    }
  }

  useEffect(() => {
    if (open && !directory.trim() && activeProject?.path) {
      setDirectory(activeProject.path)
    }
  }, [open, activeProject?.path, directory])

  // Prefill the remembered platform selection when the dialog opens.
  useEffect(() => {
    if (!open) return
    const remembered = loadRememberedPlatform()
    setLaunchOptions((current) => withDefaultLaunchOptions({
      ...current,
      platform: remembered.platform,
      aws_region: remembered.aws_region,
      aws_profile: remembered.aws_profile,
      bedrock_model: remembered.bedrock_model,
    }))
  }, [open])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLaunchDescriptor(null)
    setLaunchDescriptorError(null)
    fetchProviderLaunchOptions(provider)
      .then((descriptor) => {
        if (!cancelled) {
          setLaunchDescriptor(descriptor)
          setLaunchDescriptorError(null)
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setLaunchDescriptor(null)
          setLaunchDescriptorError(err instanceof Error ? err.message : 'Failed to load provider options')
        }
      })
    return () => { cancelled = true }
  }, [open, provider])

  // Fetch sessions when switching to resume mode
  useEffect(() => {
    if (mode !== 'resume' || !isClaude) return
    let cancelled = false
    setSelectedSession(null)
    setRecentSessions([])
    if (!resumeProjectFolder) {
      setLoadingSessions(false)
      return () => { cancelled = true }
    }
    setLoadingSessions(true)
    listSessions({
      project_folder: resumeProjectFolder,
      limit: 20,
      sort_by: 'date',
      sort_order: 'desc',
    })
      .then((data) => { if (!cancelled) setRecentSessions(data.sessions) })
      .catch(() => { if (!cancelled) setRecentSessions([]) })
      .finally(() => { if (!cancelled) setLoadingSessions(false) })
    return () => { cancelled = true }
  }, [mode, isClaude, listSessions, resumeProjectFolder])

  // Reset state when dialog closes
  useEffect(() => {
    if (!open) {
      setDirectory('')
      setProvider(defaultProvider)
      setProjectSearch('')
      setMode('plain')
      setWorktreeName('')
      setSkipPermissions(false)
      setPrompt('')
      setLaunchOptions({ ...DEFAULT_LAUNCH_OPTIONS })
      setCodexSessionId('')
      setUseLast(true)
      setError(null)
      setSelectedSession(null)
      setRecentSessions([])
      setLaunchDescriptor(null)
      setLaunchDescriptorError(null)
      setSubmitting(false)
    }
  }, [open, defaultProvider])

  const canLaunch = (() => {
    if (submitting) return false
    if (isCodex && (mode === 'resume' || mode === 'fork')) {
      return directory.trim().length > 0 && (useLast || codexSessionId.trim().length > 0)
    }
    if (isCopilot && mode === 'resume') {
      return directory.trim().length > 0 && (useLast || codexSessionId.trim().length > 0)
    }
    if (isOpenCode && mode === 'resume') {
      return directory.trim().length > 0 && (useLast || codexSessionId.trim().length > 0)
    }
    if (isClaude && mode === 'resume') return directory.trim().length > 0 && selectedSession !== null
    return directory.trim().length > 0
  })()

  async function handleLaunch() {
    setError(null)
    setSubmitting(true)

    try {
      const optionModel = stringOption(launchOptions, 'model').trim()
      const optionProfile = stringOption(launchOptions, 'profile').trim()
      const optionProfileV2 = stringOption(launchOptions, 'profile_v2').trim()
      const optionSandbox = stringOption(launchOptions, 'sandbox').trim()
      const optionApprovalPolicy = stringOption(launchOptions, 'approval_policy').trim()
      const optionAgent = stringOption(launchOptions, 'agent').trim()
      const optionContextTier = stringOption(launchOptions, 'context_tier').trim()
      const optionReasoningEffort = stringOption(launchOptions, 'reasoning_effort').trim()
      const optionAwsRegion = stringOption(launchOptions, 'aws_region').trim()
      const optionAwsProfile = stringOption(launchOptions, 'aws_profile').trim()
      const optionBedrockModel = stringOption(launchOptions, 'bedrock_model').trim()
      const optionPlatform = stringOption(launchOptions, 'platform') === 'bedrock' ? 'bedrock' : 'anthropic'

      if (supportsPlatform) {
        try {
          localStorage.setItem(
            PLATFORM_STORAGE_KEY,
            JSON.stringify({
              platform: optionPlatform,
              aws_region: optionAwsRegion,
              aws_profile: optionAwsProfile,
              bedrock_model: optionBedrockModel,
            }),
          )
        } catch {
          // Persisting the platform preference is best-effort; ignore storage failures.
        }
      }
      const request: SpawnSessionRequest = {
        provider,
        directory: directory.trim(),
        mode,
        ...(provider === 'claude-code' && mode === 'worktree' && worktreeName.trim() && { worktree_name: worktreeName.trim() }),
        ...(provider === 'claude-code' && mode === 'resume' && selectedSession && {
          session_id: selectedSession.id,
          project_folder: selectedSession.project_folder,
        }),
        ...(provider === 'claude-code' && skipPermissions && { skip_permissions: true }),
        ...(isCodex && prompt.trim() && { prompt: prompt.trim() }),
        ...((isCopilot || isOpenCode) && prompt.trim() && { prompt: prompt.trim() }),
        ...(isCodex && !isBedrock && optionModel && { model: optionModel }),
        ...((isCopilot || isOpenCode) && optionModel && { model: optionModel }),
        ...(isCodex && optionProfile && { profile: optionProfile }),
        ...(isCodex && optionProfileV2 && { profile_v2: optionProfileV2 }),
        ...(isCodex && optionSandbox && { sandbox: optionSandbox }),
        ...(isCodex && optionApprovalPolicy && { approval_policy: optionApprovalPolicy }),
        ...(isCodex && boolOption(launchOptions, 'search') && { search: true }),
        ...(isCodex && { no_alt_screen: boolOption(launchOptions, 'no_alt_screen') }),
        ...(isCodex && boolOption(launchOptions, 'dangerously_bypass_approvals_and_sandbox') && {
          dangerously_bypass_approvals_and_sandbox: true,
        }),
        ...(isCodex && (mode === 'resume' || mode === 'fork') && {
          use_last: useLast,
          ...(!useLast && codexSessionId.trim() && { session_id: codexSessionId.trim() }),
        }),
        ...(isCopilot && mode === 'resume' && {
          use_last: useLast,
          ...(!useLast && codexSessionId.trim() && { session_id: codexSessionId.trim() }),
        }),
        ...(isOpenCode && mode === 'resume' && {
          use_last: useLast,
          ...(!useLast && codexSessionId.trim() && { session_id: codexSessionId.trim() }),
        }),
        ...((isCopilot || isOpenCode) && optionAgent && { agent: optionAgent }),
        ...(isCopilot && optionContextTier && { context_tier: optionContextTier }),
        ...((isCodex || isCopilot) && optionReasoningEffort && { reasoning_effort: optionReasoningEffort }),
        ...(isCopilot && boolOption(launchOptions, 'plan') && { plan: true }),
        ...(isCopilot && boolOption(launchOptions, 'remote') && { remote: true }),
        ...(isCopilot && boolOption(launchOptions, 'allow_all') && { allow_all: true }),
        ...(isCopilot && boolOption(launchOptions, 'no_ask_user') && { no_ask_user: true }),
        ...(isBedrock && { platform: 'bedrock' as const }),
        ...(isBedrock && optionAwsRegion && { aws_region: optionAwsRegion }),
        ...(isBedrock && optionAwsProfile && { aws_profile: optionAwsProfile }),
        ...(isBedrock && (isClaude || isCodex) && optionBedrockModel && { bedrock_model: optionBedrockModel }),
      }

      const response = await spawnSession(request)
      onSpawned(response.tmux_target)
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to spawn session')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(MODAL_SIZES.MD, 'overflow-y-auto')}>
        <DialogHeader>
          <DialogTitle>New Agent Session</DialogTitle>
          <DialogDescription>
            Launch a new agent CLI instance in a tmux session.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 min-w-0">
          <div className="space-y-1.5">
            <Label>Provider</Label>
            <Select
              value={provider}
              onValueChange={(value) => {
                setProvider(value as AgentProviderId)
                setMode('plain')
                setSelectedSession(null)
                setLaunchOptions({ ...DEFAULT_LAUNCH_OPTIONS })
                setError(null)
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {providers.map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {item.display_name}{!item.installed ? ' (missing)' : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Mode selector */}
          <div className="space-y-1.5">
            <Label>Mode</Label>
            <div className="flex gap-1 rounded-md bg-muted p-1">
              {modeOptions.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={cn(
                    'flex-1 px-3 py-1.5 rounded text-sm font-medium transition-colors',
                    mode === opt.value
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                  onClick={() => {
                    setMode(opt.value)
                    setSelectedSession(null)
                    setError(null)
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Directory input */}
          <div className="space-y-2">
            {projects.length > 0 && (
              <div className="space-y-1.5">
                <Label htmlFor="session-project-search">Project</Label>
                <Input
                  ref={projectSearchRef}
                  id="session-project-search"
                  type="search"
                  value={projectSearch}
                  onChange={(event) => setProjectSearch(event.target.value)}
                  onKeyDown={handleProjectSearchKeyDown}
                  placeholder="Search projects by name or path"
                  autoComplete="off"
                  aria-controls="session-project-results"
                />
                <div
                  id="session-project-results"
                  aria-label="Projects"
                  className="max-h-48 overflow-y-auto rounded-md border border-border bg-background"
                >
                  {filteredProjects.length === 0 ? (
                    <div className="px-3 py-6 text-center text-sm text-muted-foreground">
                      No projects match.
                    </div>
                  ) : (
                    filteredProjects.map((project, index) => {
                      const selected = project.path === directory.trim()
                      return (
                        <button
                          key={project.id}
                          ref={(element) => {
                            projectOptionRefs.current[index] = element
                          }}
                          type="button"
                          aria-pressed={selected}
                          className={cn(
                            'block w-full min-w-0 border-b px-3 py-2 text-left transition-colors last:border-b-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
                            selected ? 'bg-primary/10 text-foreground' : 'hover:bg-muted/50',
                          )}
                          onClick={() => selectProject(project)}
                          onKeyDown={(event) => handleProjectOptionKeyDown(event, index)}
                        >
                          <span className="block truncate text-sm font-medium">
                            {project.name}
                          </span>
                          <span className="block truncate text-xs text-muted-foreground">
                            {project.path}
                          </span>
                        </button>
                      )
                    })
                  )}
                </div>
              </div>
            )}
            <Label htmlFor="session-directory">Project Directory</Label>
            <Input
              id="session-directory"
              value={directory}
              onChange={(e) => {
                setDirectory(e.target.value)
                setSelectedSession(null)
                setError(null)
              }}
              placeholder="/home/user/project"
              autoComplete="off"
            />
          </div>

          {/* Worktree name (only in worktree mode) */}
          {isClaude && mode === 'worktree' && (
            <div className="space-y-1.5">
              <Label htmlFor="worktree-name">Worktree Name</Label>
              <Input
                id="worktree-name"
                value={worktreeName}
                onChange={(e) => setWorktreeName(e.target.value)}
                placeholder="feature-name"
              />
              <p className="text-xs text-muted-foreground">
                Optional. A git worktree will be created for isolated development.
              </p>
            </div>
          )}

          {/* Resume session picker */}
          {isClaude && mode === 'resume' && (
            <div className="space-y-1.5">
              <Label>Recent Sessions</Label>
              {loadingSessions ? (
                <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
                  Loading sessions...
                </div>
              ) : recentSessions.length === 0 ? (
                <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
                  No recent sessions found.
                </div>
              ) : (
                <div className="max-h-48 w-full overflow-y-auto rounded-md border">
                  {recentSessions.map((session) => (
                    <button
                      key={session.id}
                      type="button"
                      className={cn(
                        'block w-full min-w-0 text-left px-3 py-2 border-b last:border-b-0 transition-colors',
                        selectedSession?.id === session.id
                          ? 'border-l-2 border-l-primary bg-primary/5'
                          : 'hover:bg-muted/50'
                      )}
                      onClick={() => setSelectedSession(session)}
                    >
                      <div className="flex items-center justify-between gap-2 min-w-0">
                        <span className="text-sm font-medium truncate min-w-0">
                          {session.project_name}
                        </span>
                        <span className="text-xs text-muted-foreground shrink-0">
                          {formatTimestamp(session.modified_at)}
                        </span>
                      </div>
                      {session.summary && (
                        <p className="text-xs text-muted-foreground mt-0.5 truncate">
                          {session.summary}
                        </p>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {(isCodex || isCopilot || isOpenCode) && (mode === 'resume' || mode === 'fork') && (
            <div className="space-y-2">
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="codex-use-last"
                  checked={useLast}
                  onCheckedChange={(checked) => setUseLast(checked === true)}
                />
                <Label htmlFor="codex-use-last" className="cursor-pointer">
                  Use last {isOpenCode ? 'OpenCode' : isCopilot ? 'Copilot' : 'Codex'} session
                </Label>
              </div>
              {!useLast && (
                <div className="space-y-1.5">
                  <Label htmlFor="codex-session-id">{isOpenCode ? 'OpenCode' : isCopilot ? 'Copilot' : 'Codex'} Session ID</Label>
                  <Input
                    id="codex-session-id"
                    value={codexSessionId}
                    onChange={(e) => setCodexSessionId(e.target.value)}
                    placeholder="session id"
                  />
                </div>
              )}
            </div>
          )}

          {launchDescriptor && (
            <ProviderLaunchOptionsFields
              provider={provider}
              value={launchOptions}
              onChange={setLaunchOptions}
              descriptor={launchDescriptor}
              disabled={submitting}
            />
          )}

          {launchDescriptorError && (
            <p className="text-xs text-destructive">
              Could not load provider launch options. {launchDescriptorError}
            </p>
          )}

          {(isCodex || isCopilot || isOpenCode) && (
            <div className="space-y-1.5">
              <Label htmlFor="session-prompt">Initial Prompt</Label>
              <Input
                id="session-prompt"
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="Optional prompt"
              />
            </div>
          )}

          {isClaude && (
            <div className="space-y-1">
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="skip-permissions"
                  checked={skipPermissions}
                  onCheckedChange={(checked) => setSkipPermissions(checked === true)}
                />
                <Label htmlFor="skip-permissions" className="cursor-pointer">
                  Skip permission prompts
                </Label>
              </div>
              <p className="text-xs text-destructive/80 ml-6">
                Allows Claude to run tools without asking for confirmation
              </p>
            </div>
          )}

          {/* Error message */}
          {error && (
            <div className="rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleLaunch} disabled={!canLaunch}>
            {submitting ? 'Launching...' : 'Launch'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
