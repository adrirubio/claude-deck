import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { BookOpen, Inbox, Mail, MessageSquarePlus, Plug, Terminal, Users } from 'lucide-react'
import { toast } from 'sonner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { RefreshButton } from '@/components/shared/RefreshButton'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
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
import { connectedHarnessNames, joinNames } from './mailSetup'
import { MemberEditDialog } from './MemberEditDialog'
import { RequestsTab, type RequestKindFilter, type RequestStatusFilter } from './RequestsTab'
import { TeamTab, type TeamStatusFilter } from './TeamTab'
import { ThreadDialog } from './ThreadDialog'

const OPERATIONAL_POLL_INTERVAL_MS = 5000

export function AgentMailPage() {
  const [members, setMembers] = useState<MailMemberResponse[]>([])
  const [messages, setMessages] = useState<MailMessageResponse[]>([])
  const [installStatus, setInstallStatus] = useState<AgentMailInstallStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [installLoading, setInstallLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('team')
  const [teamSearch, setTeamSearch] = useState('')
  const [teamStatus, setTeamStatus] = useState<TeamStatusFilter>('all')
  const [requestSearch, setRequestSearch] = useState('')
  const [requestKind, setRequestKind] = useState<RequestKindFilter>('all')
  const [requestStatus, setRequestStatus] = useState<RequestStatusFilter>('all')
  const [editingMember, setEditingMember] = useState<MailMemberResponse | null>(null)
  const [composeOpen, setComposeOpen] = useState(false)
  const [composePreset, setComposePreset] = useState<ComposePreset | null>(null)
  const [threadMessage, setThreadMessage] = useState<MailMessageResponse | null>(null)
  const [helpOpen, setHelpOpen] = useState(false)
  const [nudgingMemberId, setNudgingMemberId] = useState<number | null>(null)

  const loadOperationalData = useCallback(async (showLoading = true) => {
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
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to load Agent Mail')
    } finally {
      if (showLoading) {
        setLoading(false)
      }
    }
  }, [])

  const loadInstallData = useCallback(async () => {
    setInstallLoading(true)
    try {
      setInstallStatus(await fetchAgentMailInstallStatus())
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to load install status')
    } finally {
      setInstallLoading(false)
    }
  }, [])

  const refreshAll = useCallback(async () => {
    await Promise.all([loadOperationalData(), loadInstallData()])
  }, [loadInstallData, loadOperationalData])

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
      void loadOperationalData(false)
    }, OPERATIONAL_POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [loadOperationalData])

  const stats = useMemo(() => {
    const connected = members.filter((member) => member.status === 'connected').length
    const observed = members.filter((member) => member.status === 'observed').length
    const unread = members.reduce((total, member) => total + member.unread_count, 0)
    const pending = members.reduce((total, member) => total + member.pending_count, 0)
    const unseenPending = members.reduce((total, member) => total + member.unseen_pending_count, 0)
    const stalePending = members.reduce((total, member) => total + member.stale_pending_count, 0)
    return { connected, observed, unread, pending, unseenPending, stalePending }
  }, [members])

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
  const showCodexRegistrationNotice = !installLoading && codexReady && stats.connected === 0 && stats.observed > 0

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
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-3xl font-bold">
            <Mail className="h-8 w-8" />
            Agent Mail
          </h1>
          <p className="mt-1 text-muted-foreground">
            Coordinate local agent sessions through structured context requests and handoffs.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <RefreshButton onClick={refreshAll} loading={loading || installLoading} />
          <Button variant="outline" onClick={() => setHelpOpen(true)}>
            <BookOpen className="mr-2 h-4 w-4" />
            How it works
          </Button>
          <Button onClick={() => openCompose('context_request')}>
            <MessageSquarePlus className="mr-2 h-4 w-4" />
            New request
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
        <span><span className="font-semibold">{members.length}</span> participants</span>
        <span><span className="font-semibold">{stats.connected}</span> connected</span>
        <span><span className="font-semibold">{stats.observed}</span> observed only</span>
        <span className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{stats.unread} unread</Badge>
          <Badge variant="outline" className={stats.pending ? 'border-amber-300 text-amber-700 dark:text-amber-300' : ''}>
            {stats.pending} pending
          </Badge>
          {stats.unseenPending > 0 && (
            <Badge variant="outline" className="border-blue-300 text-blue-700 dark:text-blue-300">
              {stats.unseenPending} unseen
            </Badge>
          )}
          {stats.stalePending > 0 && (
            <Badge variant="outline" className="border-amber-300 text-amber-700 dark:text-amber-300">
              {stats.stalePending} stale
            </Badge>
          )}
        </span>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid h-auto w-full grid-cols-2 md:w-[360px]">
          <TabsTrigger value="team" className="gap-2">
            <Users className="h-4 w-4" />
            Team
          </TabsTrigger>
          <TabsTrigger value="requests" className="gap-2">
            <Inbox className="h-4 w-4" />
            Requests
          </TabsTrigger>
        </TabsList>
        <TabsContent value="team" className="mt-4">
          <TeamTab
            members={members}
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
        <TabsContent value="requests" className="mt-4">
          <RequestsTab
            messages={messages}
            members={members}
            loading={loading}
            search={requestSearch}
            kindFilter={requestKind}
            statusFilter={requestStatus}
            onSearchChange={setRequestSearch}
            onKindFilterChange={setRequestKind}
            onStatusFilterChange={setRequestStatus}
            onOpenThread={setThreadMessage}
            onCompose={openCompose}
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
