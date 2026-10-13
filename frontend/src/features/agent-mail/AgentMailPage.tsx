import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { BookOpen, Inbox, Mail, MessageSquarePlus, Plug, Terminal, Users } from 'lucide-react'
import { toast } from 'sonner'
import { ApiHttpError } from '@/lib/api'
import { clearOperatorToken, getOperatorToken } from '@/features/agent-teams/operatorAuth'
import { useOperatorTokenFlow } from '@/features/agent-teams/useOperatorTokenFlow'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { RefreshButton } from '@/components/shared/RefreshButton'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type {
  AgentMailInstallStatus,
  MailMemberResponse,
  MailMemberUpdate,
  MailMessageCreate,
  MailMessageKind,
  MailMessageResponse,
} from '@/types/agentMail'
import {
  fetchAgentMailInstallStatus,
  fetchAgentMailMessages,
  fetchAgentMailTeam,
  queueAgentMailInboxCheck,
  sendAgentMailMessage,
  updateAgentMailMember,
} from './api'
import { AgentMailHelpDialog } from './AgentMailHelpDialog'
import { ComposeDialog, type ComposePreset } from './ComposeDialog'
import { ConversationsTab } from './ConversationsTab'
import {
  ALL_TEAMS,
  buildConversations,
  membersInTeam,
  teamNames,
  type ChipId,
} from './conversations'
import { connectedHarnessNames, joinNames } from './mailSetup'
import { MemberEditDialog } from './MemberEditDialog'
import { TeamTab, type TeamStatusFilter } from './TeamTab'
import { ThreadDialog } from './ThreadDialog'
import { WaitingPanel } from './WaitingPanel'

const ALL_TEAMS_VALUE = '__all_teams__'

const OPERATIONAL_POLL_INTERVAL_MS = 5000

/** A count in the totals line. It jumps to the panel that lists what the count counts. */
function CountLink({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={`${label}. Go to Waiting on someone`}
      className="rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      onClick={onClick}
    >
      {children}
    </button>
  )
}

export function AgentMailPage() {
  const { requestToken, tokenDialog } = useOperatorTokenFlow('Agent Mail requires the Director key.')
  const protectedReadsBlocked = useRef(false)
  const pollingEnabled = useRef(false)

  const stopRefusedReads = useCallback((error: unknown) => {
    if (error instanceof ApiHttpError && (error.status === 503 || (error.status >= 400 && error.status < 500))) {
      protectedReadsBlocked.current = true
      pollingEnabled.current = false
      if (error.status === 401) clearOperatorToken()
    }
  }, [])
  const [members, setMembers] = useState<MailMemberResponse[]>([])
  const [messages, setMessages] = useState<MailMessageResponse[]>([])
  const [installStatus, setInstallStatus] = useState<AgentMailInstallStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [installLoading, setInstallLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('team')
  const [teamSearch, setTeamSearch] = useState('')
  const [teamStatus, setTeamStatus] = useState<TeamStatusFilter>('all')
  const [conversationSearch, setConversationSearch] = useState('')
  const [chip, setChip] = useState<ChipId>('all')
  const [team, setTeam] = useState(ALL_TEAMS)
  const [recipientMemberId, setRecipientMemberId] = useState<number | null>(null)
  const waitingRef = useRef<HTMLElement>(null)
  const [editingMember, setEditingMember] = useState<MailMemberResponse | null>(null)
  const [composeOpen, setComposeOpen] = useState(false)
  const [composePreset, setComposePreset] = useState<ComposePreset | null>(null)
  const [threadMessage, setThreadMessage] = useState<MailMessageResponse | null>(null)
  const [helpOpen, setHelpOpen] = useState(false)
  const [nudgingMemberId, setNudgingMemberId] = useState<number | null>(null)

  const loadOperationalData = useCallback(async (showLoading = true) => {
    if (protectedReadsBlocked.current || !getOperatorToken()) return
    if (showLoading) {
      setLoading(true)
    }
    try {
      const [team, roots] = await Promise.all([
        fetchAgentMailTeam(true),
        fetchAgentMailMessages(),
      ])
      setMembers(team.members)
      setMessages(roots)
      pollingEnabled.current = true
    } catch (error) {
      stopRefusedReads(error)
      toast.error(error instanceof Error ? error.message : 'Failed to load Agent Mail')
    } finally {
      if (showLoading) {
        setLoading(false)
      }
    }
  }, [stopRefusedReads])

  const loadInstallData = useCallback(async () => {
    if (protectedReadsBlocked.current || !getOperatorToken()) return
    setInstallLoading(true)
    try {
      setInstallStatus(await fetchAgentMailInstallStatus())
    } catch (error) {
      stopRefusedReads(error)
      toast.error(error instanceof Error ? error.message : 'Failed to load install status')
    } finally {
      setInstallLoading(false)
    }
  }, [stopRefusedReads])

  const refreshAll = useCallback(async () => {
    pollingEnabled.current = false
    if (!await requestToken()) {
      protectedReadsBlocked.current = true
      setLoading(false)
      setInstallLoading(false)
      return
    }
    protectedReadsBlocked.current = false
    pollingEnabled.current = true
    await Promise.all([loadOperationalData(), loadInstallData()])
  }, [loadInstallData, loadOperationalData, requestToken])

  useEffect(() => {
    let cancelled = false
    queueMicrotask(() => {
      if (!cancelled) void refreshAll()
    })
    return () => {
      cancelled = true
    }
  }, [refreshAll])

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (pollingEnabled.current && !protectedReadsBlocked.current) void loadOperationalData(false)
    }, OPERATIONAL_POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [loadOperationalData])

  const teams = useMemo(() => teamNames(members), [members])
  // A team that no member has any more (for example after a delete) shows all teams.
  const activeTeam = teams.includes(team) ? team : ALL_TEAMS
  const teamMembers = useMemo(() => membersInTeam(members, activeTeam), [members, activeTeam])
  const conversations = useMemo(() => buildConversations(messages, members), [messages, members])

  const showWaiting = (memberId: number | null) => {
    setRecipientMemberId(memberId)
    setChip('all')
    setActiveTab('conversations')
  }

  // The count badges point at the panel that lists what they count.
  const goToWaiting = () => {
    const panel = waitingRef.current
    if (!panel) return
    panel.scrollIntoView?.({ block: 'start' })
    panel.focus({ preventScroll: true })
  }

  const stats = useMemo(() => {
    const connected = teamMembers.filter((member) => member.status === 'connected').length
    const observed = teamMembers.filter((member) => member.status === 'observed').length
    const unread = teamMembers.reduce((total, member) => total + member.unread_count, 0)
    const pending = teamMembers.reduce((total, member) => total + member.pending_count, 0)
    const unseenPending = teamMembers.reduce((total, member) => total + member.unseen_pending_count, 0)
    const stalePending = teamMembers.reduce((total, member) => total + member.stale_pending_count, 0)
    return { connected, observed, unread, pending, unseenPending, stalePending }
  }, [teamMembers])

  const claudeReady = Boolean(
    installStatus
    && installStatus.claude_code_hooks_missing.length === 0
    && installStatus.claude_code_mcp_installed
  )
  const codexReady = Boolean(installStatus?.codex_mcp_installed)
  const copilotReady = Boolean(
    installStatus?.copilot_mcp_installed && installStatus.copilot_hooks_missing.length === 0
  )
  const opencodeReady = Boolean(
    installStatus?.opencode_mcp_installed && installStatus.opencode_plugin_events_missing.length === 0
  )
  const hasConfiguredIntegration = claudeReady || codexReady || copilotReady || opencodeReady
  const setUpNames = connectedHarnessNames(installStatus)
  const showSetupNotice = !installLoading && (!hasConfiguredIntegration || members.length === 0)
  const showCodexRegistrationNotice = !installLoading && codexReady
    && !members.some((member) => member.status === 'connected') && members.some((member) => member.status === 'observed')

  const openCompose = (
    kind: Exclude<MailMessageKind, 'answer'> = 'message',
    member?: MailMemberResponse
  ) => {
    setComposePreset({
      kind,
      recipient_member_id: member?.id ?? null,
      subject: kind === 'handoff' && member ? `Handoff: ${member.display_name}` : undefined,
    })
    setComposeOpen(true)
  }

  const handleUpdateMember = async (memberId: number, update: MailMemberUpdate) => {
    try {
      await updateAgentMailMember(memberId, update)
      await loadOperationalData()
      toast.success('Participant updated')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to update participant')
      throw error
    }
  }

  const handleSendMessage = async (message: MailMessageCreate) => {
    try {
      await sendAgentMailMessage(message)
      await loadOperationalData()
      toast.success('Message sent')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to send message')
      throw error
    }
  }

  const handleQueueInboxCheck = async (member: MailMemberResponse) => {
    setNudgingMemberId(member.id)
    try {
      const result = await queueAgentMailInboxCheck(member.id)
      await loadOperationalData(false)
      const method = result.method ? `via ${result.method}` : 'via tmux'
      toast.success(`Queued inbox check for ${member.display_name} ${method}`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to queue inbox check')
    } finally {
      setNudgingMemberId(null)
    }
  }

  return (
    <div className="space-y-4">
      {tokenDialog}
      {installStatus?.mail_capability_tokens_required === false && (
        <Alert variant="destructive">
          <AlertTitle>Agent Mail uses legacy authentication.</AlertTitle>
          <AlertDescription>The opt-out allows unauthenticated reads and legacy registration.
            Writes always need a key.</AlertDescription>
        </Alert>
      )}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-3xl font-bold">
            <Mail className="h-8 w-8" />
            Agent Mail
          </h1>
          <p className="mt-1 text-muted-foreground">
            Messages between your agents, and between you and them.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={activeTeam === ALL_TEAMS ? ALL_TEAMS_VALUE : activeTeam}
            onValueChange={(value) => setTeam(value === ALL_TEAMS_VALUE ? ALL_TEAMS : value)}
          >
            <SelectTrigger aria-label="Team" className="w-[180px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_TEAMS_VALUE}>All teams</SelectItem>
              {teams.map((name) => <SelectItem key={name} value={name}>{name}</SelectItem>)}
            </SelectContent>
          </Select>
          <RefreshButton onClick={refreshAll} loading={loading || installLoading} />
          <Button variant="outline" onClick={() => setHelpOpen(true)}>
            <BookOpen className="mr-2 h-4 w-4" />
            How it works
          </Button>
          <Button onClick={() => openCompose('message')}>
            <MessageSquarePlus className="mr-2 h-4 w-4" />
            Write a message
          </Button>
        </div>
      </div>

      {showSetupNotice && (
        <Alert className="border-amber-300 bg-amber-50/60 dark:bg-amber-950/20">
          <Plug className="h-4 w-4" />
          <AlertTitle>
            {!hasConfiguredIntegration ? 'Agent setup required' : 'No agents registered yet'}
          </AlertTitle>
          <AlertDescription>
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <p>
                {!hasConfiguredIntegration
                  ? 'Install the Agent Mail MCP server for Claude Code, Codex, GitHub Copilot CLI, or OpenCode CLI before agents can send, receive, or answer mailbox requests.'
                  : 'Start or resume an agent in a repository, then have it call deck_whoami once so Claude Deck can attach it to a participant.'}
              </p>
              <div className="flex shrink-0 flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => setHelpOpen(true)}>
                  <BookOpen className="mr-2 h-4 w-4" />
                  Setup notes
                </Button>
                {!hasConfiguredIntegration && (
                  <Link to="/harnesses" className={buttonVariants({ size: 'sm' })}>
                    <Plug className="mr-2 h-4 w-4" />
                    Set up in Harnesses
                  </Link>
                )}
              </div>
            </div>
          </AlertDescription>
        </Alert>
      )}

      {showCodexRegistrationNotice && (
        <Alert className="border-blue-300 bg-blue-50/60 dark:bg-blue-950/20">
          <Terminal className="h-4 w-4" />
          <AlertTitle>Codex MCP installed, agent check-in pending</AlertTitle>
          <AlertDescription>
            Agent Bridge can see the Codex tmux session. Ask that agent to run <code>deck_whoami</code> once from its repository so Agent Mail can mark it connected.
          </AlertDescription>
        </Alert>
      )}

      <div
        role="group"
        aria-label="Agent Mail totals"
        className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border px-4 py-2 text-sm"
      >
        <span><span className="font-semibold">{teamMembers.length}</span> participants</span>
        <span><span className="font-semibold">{stats.connected}</span> connected</span>
        <span><span className="font-semibold">{stats.observed}</span> observed only</span>
        <span className="flex flex-wrap items-center gap-2">
          <CountLink label={`${stats.unread} unread`} onClick={goToWaiting}>
            <Badge variant="secondary">{stats.unread} unread</Badge>
          </CountLink>
          <CountLink label={`${stats.pending} pending`} onClick={goToWaiting}>
            <Badge variant="outline" className={stats.pending ? 'border-amber-300 text-amber-700 dark:text-amber-300' : ''}>
              {stats.pending} pending
            </Badge>
          </CountLink>
          {stats.unseenPending > 0 && (
            <CountLink label={`${stats.unseenPending} unseen`} onClick={goToWaiting}>
              <Badge variant="outline" className="border-blue-300 text-blue-700 dark:text-blue-300">
                {stats.unseenPending} unseen
              </Badge>
            </CountLink>
          )}
          {stats.stalePending > 0 && (
            <CountLink label={`${stats.stalePending} stale`} onClick={goToWaiting}>
              <Badge variant="outline" className="border-amber-300 text-amber-700 dark:text-amber-300">
                {stats.stalePending} stale
              </Badge>
            </CountLink>
          )}
        </span>
      </div>

      <WaitingPanel
        ref={waitingRef}
        members={teamMembers}
        loading={loading}
        recipientMemberId={recipientMemberId}
        onShowRecipient={showWaiting}
      />

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid h-auto w-full grid-cols-2 md:w-[360px]">
          <TabsTrigger value="team" className="gap-2">
            <Users className="h-4 w-4" />
            Team
          </TabsTrigger>
          <TabsTrigger value="conversations" className="gap-2">
            <Inbox className="h-4 w-4" />
            Conversations
          </TabsTrigger>
        </TabsList>
        <TabsContent value="team" className="mt-3">
          <TeamTab
            members={teamMembers}
            loading={loading}
            repoSearch={teamSearch}
            statusFilter={teamStatus}
            onRepoSearchChange={setTeamSearch}
            onStatusFilterChange={setTeamStatus}
            onEdit={setEditingMember}
            onCompose={openCompose}
            onQueueInboxCheck={handleQueueInboxCheck}
            nudgingMemberId={nudgingMemberId}
          />
        </TabsContent>
        <TabsContent value="conversations" className="mt-3">
          <ConversationsTab
            conversations={conversations}
            members={members}
            loading={loading}
            search={conversationSearch}
            chip={chip}
            team={activeTeam}
            recipientMemberId={recipientMemberId}
            messageCount={messages.length}
            onSearchChange={setConversationSearch}
            onChipChange={setChip}
            onClearRecipient={() => setRecipientMemberId(null)}
            onOpenThread={setThreadMessage}
          />
        </TabsContent>
      </Tabs>

      {setUpNames.length > 0 && (
        <p className="text-sm text-muted-foreground">
          Mail is set up for {joinNames(setUpNames)} ·{' '}
          <Link to="/harnesses" className="text-primary underline">Manage in Harnesses</Link>
        </p>
      )}

      <MemberEditDialog
        member={editingMember}
        open={Boolean(editingMember)}
        onOpenChange={(open) => !open && setEditingMember(null)}
        onSave={handleUpdateMember}
      />
      <ComposeDialog
        open={composeOpen}
        members={members}
        preset={composePreset}
        onOpenChange={setComposeOpen}
        onSend={handleSendMessage}
      />
      <ThreadDialog
        message={threadMessage}
        members={members}
        open={Boolean(threadMessage)}
        onOpenChange={(open) => !open && setThreadMessage(null)}
        onChanged={loadOperationalData}
      />
      <AgentMailHelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
    </div>
  )
}
