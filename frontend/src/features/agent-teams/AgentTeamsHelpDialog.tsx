import { BookOpen, GitBranch, Inbox, Rocket, UsersRound } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { MODAL_SIZES } from '@/lib/constants'

interface AgentTeamsHelpDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

function HelpSection({
  icon: Icon,
  title,
  children,
}: {
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

export function AgentTeamsHelpDialog({ open, onOpenChange }: AgentTeamsHelpDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={MODAL_SIZES.MD}>
        <DialogHeader>
          <DialogTitle>Agent Teams guide</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <HelpSection icon={UsersRound} title="What a team slot is">
            <p>
              A team is a saved roster of named slots. Each slot stores a provider, repository,
              role, charter, UI color, and optional bootstrap prompt. When launched from Agent Teams, each
              slot receives its own Agent Mail identity.
            </p>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">Provider</Badge>
              <Badge variant="outline">Repo</Badge>
              <Badge variant="outline">Role</Badge>
              <Badge variant="outline">Charter</Badge>
              <Badge variant="outline">Color</Badge>
            </div>
          </HelpSection>

          <HelpSection icon={Inbox} title="Same-repo planner and reviewer">
            <p>
              Use separate slots when two agents work in the same repository but need distinct
              roles, inboxes, and routing. For example, create one slot named Planner and one slot
              named Reviewer, both pointing at the same repo.
            </p>
            <p>
              Manually started same-repo sessions can collapse into one repo-level participant.
              Launching through Agent Teams gives Agent Mail a durable slot identity for each role.
            </p>
          </HelpSection>

          <HelpSection icon={Rocket} title="Launch and reuse rules">
            <ol className="list-decimal space-y-1 pl-5">
              <li>Create the slots with distinct names and role prompts.</li>
              <li>Use Plan launch to confirm what will spawn or reuse.</li>
              <li>Launch from Agent Teams so MCP, hooks, and tmux observation attach to the slot.</li>
              <li>Use reuse only when the existing sessions already belong to the intended slots.</li>
              <li>An unbound pane blocks the normal plan. Only an operator can review its target and PID, then explicitly adopt it; do not adopt an unknown pane as Leader.</li>
            </ol>
          </HelpSection>

          <HelpSection icon={BookOpen} title="After launch">
            <p>
              Use Agent Mail for the actual coordination. Agents should call <code>deck_whoami</code>
              to confirm their slot identity, then use <code>deck_request_context</code>,
              <code> deck_reply</code>, and handoffs to coordinate.
            </p>
          </HelpSection>

          <HelpSection icon={GitBranch} title="Autonomous GitHub dispatch">
            <ol className="list-decimal space-y-1 pl-5">
              <li>Put <code>github_token</code> in <code>backend/.env</code> for polling private repos and restart Deck. App-backed dispatch also needs GitHub App settings; App settings alone do not authenticate the watcher.</li>
              <li>Add a watched repo with an existing primary checkout under your home directory.</li>
              <li>The first enabled Roster slot is the Leader; launch it before enabling autonomy. The Role text does not select it.</li>
              <li>Add the dispatch label to a GitHub issue, then enable autonomy. Area labels route to a matching owner; otherwise Deck uses expertise, then the Leader.</li>
              <li>Watch Activity. The operator token protects roster and watched-repo settings, team launch, autonomy, recovery policy, and operator remedies. It is separate from the GitHub polling token and stays in this browser tab.</li>
            </ol>
            <p>Design-labeled issues follow the human-review design pipeline. Code auto-merge depends on each repo&apos;s merge policy.</p>
            <p>Issues move from queued to dispatched, verifying, and human review or merge. Escalation means Deck stopped and needs attention. Recovery lets an owner continue an escalated issue with an open PR after a Leader-approved, bounded scope revision.</p>
            <p><a href="https://github.com/adrirubio/claude-deck/blob/master/docs/autonomy.md" target="_blank" rel="noreferrer" className="text-primary underline">Read the autonomy operator guide</a>.</p>
          </HelpSection>
        </div>
      </DialogContent>
    </Dialog>
  )
}
