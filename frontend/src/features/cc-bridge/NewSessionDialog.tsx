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
import { fetchCodexLaunchOptions, spawnSession } from './api'
import { useSessionsApi } from '@/hooks/useSessionsApi'
import { useProjectContext } from '@/contexts/ProjectContext'
import { useProviderContext } from '@/contexts/ProviderContext'
import type { AgentProviderId } from '@/types/providers'
import type {
  CodexLaunchModelOption,
  CodexLaunchOptionsResponse,
  CodexLaunchProfileOption,
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

const PLATFORM_STORAGE_KEY = 'cc-bridge.platform'
const DEFAULT_SELECT_VALUE = '__default__'
const CUSTOM_SELECT_VALUE = '__custom__'
const EMPTY_MODEL_OPTIONS: CodexLaunchModelOption[] = []
const EMPTY_PROFILE_OPTIONS: CodexLaunchProfileOption[] = []

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

function optionValues<T extends { value: string }>(options: T[]) {
  return new Set(options.map((option) => option.value))
}

function formatModelOption(option: CodexLaunchModelOption) {
  return option.label && option.label !== option.value
    ? `${option.label} (${option.value})`
    : option.value
}

function formatProfileOption(option: CodexLaunchProfileOption) {
  return option.active ? `${option.label} (active)` : option.label
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
  const [model, setModel] = useState('')
  const [customModel, setCustomModel] = useState(false)
  const [profile, setProfile] = useState('')
  const [customProfile, setCustomProfile] = useState(false)
  const [sandbox, setSandbox] = useState('')
  const [approvalPolicy, setApprovalPolicy] = useState('')
  const [search, setSearch] = useState(false)
  const [noAltScreen, setNoAltScreen] = useState(true)
  const [dangerousBypass, setDangerousBypass] = useState(false)
  const [codexSessionId, setCodexSessionId] = useState('')
  const [useLast, setUseLast] = useState(true)
  const [platform, setPlatform] = useState<Platform>('anthropic')
  const [awsRegion, setAwsRegion] = useState('')
  const [awsProfile, setAwsProfile] = useState('')
  const [bedrockModel, setBedrockModel] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [recentSessions, setRecentSessions] = useState<SessionSummary[]>([])
  const [selectedSession, setSelectedSession] = useState<SessionSummary | null>(null)
  const [loadingSessions, setLoadingSessions] = useState(false)
  const [codexLaunchOptions, setCodexLaunchOptions] = useState<CodexLaunchOptionsResponse | null>(null)
  const [codexLaunchOptionsError, setCodexLaunchOptionsError] = useState<string | null>(null)
  const projectSearchRef = useRef<HTMLInputElement>(null)
  const projectOptionRefs = useRef<Array<HTMLButtonElement | null>>([])

  const { listSessions } = useSessionsApi()
  const { projects, activeProject } = useProjectContext()
  const isCodex = provider === 'codex-cli'
  const isBedrock = platform === 'bedrock'
  const defaultPlatformLabel = isCodex ? 'OpenAI' : 'Anthropic'
  const bedrockHelpText = isCodex
    ? 'Codex uses Amazon Bedrock for this session. Credentials resolve from your shell or AWS config.'
    : 'Uses AWS credentials from the server environment. Region is usually required.'
  const bedrockModelLabel = isCodex ? 'Bedrock model ID (optional)' : 'Model ARN / ID (optional)'
  const bedrockModelPlaceholder = isCodex ? 'openai.gpt-5.5' : 'arn:aws:bedrock:...'
  const modeOptions = isCodex ? CODEX_MODE_OPTIONS : MODE_OPTIONS
  const filteredProjects = useMemo(
    () => projects.filter((project) => matchesProjectSearch(project, projectSearch)),
    [projects, projectSearch],
  )
  const modelOptions = codexLaunchOptions?.model_options ?? EMPTY_MODEL_OPTIONS
  const profileOptions = codexLaunchOptions?.profile_options ?? EMPTY_PROFILE_OPTIONS
  const knownModelValues = useMemo(() => optionValues(modelOptions), [modelOptions])
  const knownProfileValues = useMemo(() => optionValues(profileOptions), [profileOptions])
  const modelSelectValue = customModel || (model && !knownModelValues.has(model))
    ? CUSTOM_SELECT_VALUE
    : model || DEFAULT_SELECT_VALUE
  const profileSelectValue = customProfile || (profile && !knownProfileValues.has(profile))
    ? CUSTOM_SELECT_VALUE
    : profile || DEFAULT_SELECT_VALUE
  const defaultModelLabel = codexLaunchOptions?.default_model
    ? `Default (${codexLaunchOptions.default_model})`
    : 'Default'
  const defaultProfileLabel = codexLaunchOptions?.default_profile
    ? `Default (${codexLaunchOptions.default_profile})`
    : 'Default'
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

  function handleModelSelect(value: string) {
    if (value === DEFAULT_SELECT_VALUE) {
      setCustomModel(false)
      setModel('')
      return
    }
    if (value === CUSTOM_SELECT_VALUE) {
      setCustomModel(true)
      setModel('')
      return
    }
    setCustomModel(false)
    setModel(value)
  }

  function handleProfileSelect(value: string) {
    if (value === DEFAULT_SELECT_VALUE) {
      setCustomProfile(false)
      setProfile('')
      return
    }
    if (value === CUSTOM_SELECT_VALUE) {
      setCustomProfile(true)
      setProfile('')
      return
    }
    setCustomProfile(false)
    setProfile(value)
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
    setPlatform(remembered.platform)
    setAwsRegion(remembered.aws_region)
    setAwsProfile(remembered.aws_profile)
    setBedrockModel(remembered.bedrock_model)
  }, [open])

  useEffect(() => {
    if (!open || !isCodex) return
    let cancelled = false
    fetchCodexLaunchOptions()
      .then((options) => {
        if (!cancelled) {
          setCodexLaunchOptions(options)
          setCodexLaunchOptionsError(null)
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setCodexLaunchOptions(null)
          setCodexLaunchOptionsError(err instanceof Error ? err.message : 'Failed to load Codex options')
        }
      })
    return () => { cancelled = true }
  }, [open, isCodex])

  // Fetch sessions when switching to resume mode
  useEffect(() => {
    if (mode !== 'resume' || isCodex) return
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
  }, [mode, isCodex, listSessions, resumeProjectFolder])

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
      setModel('')
      setCustomModel(false)
      setProfile('')
      setCustomProfile(false)
      setSandbox('')
      setApprovalPolicy('')
      setSearch(false)
      setNoAltScreen(true)
      setDangerousBypass(false)
      setCodexSessionId('')
      setUseLast(true)
      setError(null)
      setSelectedSession(null)
      setRecentSessions([])
      setCodexLaunchOptions(null)
      setCodexLaunchOptionsError(null)
      setSubmitting(false)
    }
  }, [open, defaultProvider])

  const canLaunch = (() => {
    if (submitting) return false
    if (isCodex && (mode === 'resume' || mode === 'fork')) {
      return directory.trim().length > 0 && (useLast || codexSessionId.trim().length > 0)
    }
    if (!isCodex && mode === 'resume') return directory.trim().length > 0 && selectedSession !== null
    return directory.trim().length > 0
  })()

  async function handleLaunch() {
    setError(null)
    setSubmitting(true)

    try {
      try {
        localStorage.setItem(
          PLATFORM_STORAGE_KEY,
          JSON.stringify({
            platform,
            aws_region: awsRegion,
            aws_profile: awsProfile,
            bedrock_model: bedrockModel,
          }),
        )
      } catch {
        // Persisting the platform preference is best-effort; ignore storage failures.
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
        ...(isCodex && !isBedrock && model.trim() && { model: model.trim() }),
        ...(isCodex && profile.trim() && { profile: profile.trim() }),
        ...(isCodex && sandbox && { sandbox }),
        ...(isCodex && approvalPolicy && { approval_policy: approvalPolicy }),
        ...(isCodex && search && { search: true }),
        ...(isCodex && { no_alt_screen: noAltScreen }),
        ...(isCodex && dangerousBypass && { dangerously_bypass_approvals_and_sandbox: true }),
        ...(isCodex && (mode === 'resume' || mode === 'fork') && {
          use_last: useLast,
          ...(!useLast && codexSessionId.trim() && { session_id: codexSessionId.trim() }),
        }),
        ...(isBedrock && { platform: 'bedrock' as const }),
        ...(isBedrock && awsRegion.trim() && { aws_region: awsRegion.trim() }),
        ...(isBedrock && awsProfile.trim() && { aws_profile: awsProfile.trim() }),
        ...(isBedrock && bedrockModel.trim() && { bedrock_model: bedrockModel.trim() }),
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
                setModel('')
                setCustomModel(false)
                setProfile('')
                setCustomProfile(false)
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

          <div className="space-y-1.5">
            <Label>Platform</Label>
            <Select value={platform} onValueChange={(value) => setPlatform(value as Platform)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="anthropic">{defaultPlatformLabel} (default)</SelectItem>
                <SelectItem value="bedrock">Amazon Bedrock</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {isBedrock && (
            <div className="space-y-3 rounded-md border border-border p-3">
              <p className="text-xs text-muted-foreground">
                {bedrockHelpText}
              </p>
              <div className="space-y-1.5">
                <Label htmlFor="aws-region">AWS Region</Label>
                <Input id="aws-region" value={awsRegion} onChange={(e) => setAwsRegion(e.target.value)} placeholder="e.g. us-east-1" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="aws-profile">AWS Profile (optional)</Label>
                <Input id="aws-profile" value={awsProfile} onChange={(e) => setAwsProfile(e.target.value)} placeholder="e.g. bedrock-prod" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="bedrock-model">{bedrockModelLabel}</Label>
                <Input id="bedrock-model" value={bedrockModel} onChange={(e) => setBedrockModel(e.target.value)} placeholder={bedrockModelPlaceholder} />
              </div>
            </div>
          )}

          {/* Worktree name (only in worktree mode) */}
          {!isCodex && mode === 'worktree' && (
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
          {!isCodex && mode === 'resume' && (
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

          {isCodex && (mode === 'resume' || mode === 'fork') && (
            <div className="space-y-2">
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="codex-use-last"
                  checked={useLast}
                  onCheckedChange={(checked) => setUseLast(checked === true)}
                />
                <Label htmlFor="codex-use-last" className="cursor-pointer">
                  Use last Codex session
                </Label>
              </div>
              {!useLast && (
                <div className="space-y-1.5">
                  <Label htmlFor="codex-session-id">Codex Session ID</Label>
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

          {isCodex && (
            <div className="grid grid-cols-2 gap-3">
              {!isBedrock && (
                <div className="space-y-1.5">
                  <Label htmlFor="codex-model">Model</Label>
                  <Select value={modelSelectValue} onValueChange={handleModelSelect}>
                    <SelectTrigger id="codex-model">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={DEFAULT_SELECT_VALUE}>{defaultModelLabel}</SelectItem>
                      {modelOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {formatModelOption(option)}
                        </SelectItem>
                      ))}
                      <SelectItem value={CUSTOM_SELECT_VALUE}>Custom model</SelectItem>
                    </SelectContent>
                  </Select>
                  {modelSelectValue === CUSTOM_SELECT_VALUE && (
                    <Input
                      id="codex-model-custom"
                      value={model}
                      onChange={(event) => setModel(event.target.value)}
                      placeholder="model name"
                      autoComplete="off"
                      aria-label="Custom Codex model"
                    />
                  )}
                </div>
              )}
              <div className="space-y-1.5">
                <Label htmlFor="codex-profile">Profile</Label>
                <Select value={profileSelectValue} onValueChange={handleProfileSelect}>
                  <SelectTrigger id="codex-profile">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={DEFAULT_SELECT_VALUE}>{defaultProfileLabel}</SelectItem>
                    {profileOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {formatProfileOption(option)}
                      </SelectItem>
                    ))}
                    <SelectItem value={CUSTOM_SELECT_VALUE}>Custom profile</SelectItem>
                  </SelectContent>
                </Select>
                {profileSelectValue === CUSTOM_SELECT_VALUE && (
                  <Input
                    id="codex-profile-custom"
                    value={profile}
                    onChange={(event) => setProfile(event.target.value)}
                    placeholder="profile name"
                    autoComplete="off"
                    aria-label="Custom Codex profile"
                  />
                )}
              </div>
              {codexLaunchOptionsError && (
                <p className="col-span-2 text-xs text-destructive">
                  Could not load Codex models and profiles. Custom values are still available.
                </p>
              )}
              <div className="space-y-1.5">
                <Label>Sandbox</Label>
                <Select value={sandbox || 'default'} onValueChange={(value) => setSandbox(value === 'default' ? '' : value)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="default">Default</SelectItem>
                    <SelectItem value="read-only">Read-only</SelectItem>
                    <SelectItem value="workspace-write">Workspace write</SelectItem>
                    <SelectItem value="danger-full-access">Full access</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Approval</Label>
                <Select value={approvalPolicy || 'default'} onValueChange={(value) => setApprovalPolicy(value === 'default' ? '' : value)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="default">Default</SelectItem>
                    <SelectItem value="untrusted">Untrusted</SelectItem>
                    <SelectItem value="on-failure">On failure</SelectItem>
                    <SelectItem value="on-request">On request</SelectItem>
                    <SelectItem value="never">Never</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="col-span-2 space-y-1.5">
                <Label htmlFor="codex-prompt">Initial Prompt</Label>
                <Input id="codex-prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Optional prompt" />
              </div>
            </div>
          )}

          {!isCodex && (
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

          {isCodex && (
            <div className="space-y-2">
              <div className="flex items-center space-x-2">
                <Checkbox id="codex-search" checked={search} onCheckedChange={(checked) => setSearch(checked === true)} />
                <Label htmlFor="codex-search" className="cursor-pointer">Enable web search</Label>
              </div>
              <div className="flex items-center space-x-2">
                <Checkbox id="codex-no-alt-screen" checked={noAltScreen} onCheckedChange={(checked) => setNoAltScreen(checked === true)} />
                <Label htmlFor="codex-no-alt-screen" className="cursor-pointer">Disable alternate screen</Label>
              </div>
              <div className="flex items-center space-x-2">
                <Checkbox id="codex-dangerous" checked={dangerousBypass} onCheckedChange={(checked) => setDangerousBypass(checked === true)} />
                <Label htmlFor="codex-dangerous" className="cursor-pointer text-destructive">Bypass approvals and sandbox</Label>
              </div>
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
