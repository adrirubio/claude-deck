import { BellRing, BookOpen, CheckCircle2, Inbox, Plug, ShieldAlert } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { MODAL_SIZES } from '@/lib/constants'

interface AgentMailHelpDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

function HelpSection({ icon: Icon, title, children }: {
  icon: typeof BookOpen
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-lg border p-4">
      <div className="mb-3 flex items-center gap-2">
        <Icon className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-semibold">{title}</h3>
      </div>
      <div className="space-y-2 text-sm leading-6 text-muted-foreground">{children}</div>
    </section>
  )
}

export function AgentMailHelpDialog({ open, onOpenChange }: AgentMailHelpDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={MODAL_SIZES.MD}>
        <DialogHeader>
          <DialogTitle>Agent Mail setup</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <HelpSection icon={Plug} title="Required agent configuration">
            <p>
              Agent Mail only works after each agent type has the Claude Deck mail MCP server.
              Claude Code also needs hooks if you want mailbox state injected into the agent
              context automatically.
            </p>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">Claude Code: MCP + hooks</Badge>
              <Badge variant="outline">Codex CLI: MCP</Badge>
            </div>
          </HelpSection>

          <HelpSection icon={CheckCircle2} title="First run checklist">
            <ol className="list-decimal space-y-1 pl-5">
              <li>Use the Install tab to configure Claude Code or Codex.</li>
              <li>Restart or resume the affected agent sessions.</li>
              <li>Have each agent call <code>deck_whoami</code> once from its repo.</li>
              <li>Ask agents to check <code>deck_check_inbox</code> before and after major work.</li>
            </ol>
          </HelpSection>

          <HelpSection icon={BellRing} title="Codex wakeups">
            <p>
              The Codex install is persistent, but non-tmux wakeups need the Codex app-server
              process that Claude Deck starts from the Install tab. When it is running, Deck can
              send an inbox-check turn to connected Codex repos that are not visible through tmux.
            </p>
          </HelpSection>

          <HelpSection icon={Inbox} title="What agents can do">
            <p>
              Agents can request context from another repo expert, create handoffs, reply in
              threads, acknowledge answers, and list the team. The useful tools are
              <code> deck_request_context</code>, <code> deck_create_handoff</code>,
              <code> deck_reply</code>, and <code> deck_ack_message</code>.
            </p>
          </HelpSection>

          <HelpSection icon={ShieldAlert} title="MVP limits">
            <p>
              Visibility is machine-global, members are keyed one-per-repo, and Claude Deck must
              be running for agents to use the mailbox. Git worktrees of the same repository share
              a member identity.
            </p>
          </HelpSection>
        </div>
      </DialogContent>
    </Dialog>
  )
}
