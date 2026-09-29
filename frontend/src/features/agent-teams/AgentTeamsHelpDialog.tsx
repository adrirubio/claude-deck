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
              <li>On the Autonomy tab, add a watched repo with its primary checkout and issue labels.</li>
              <li>Check that the repo has GitHub authentication and an enabled Leader slot.</li>
              <li>Label an issue with the dispatch label, then enable autonomy to start polling.</li>
              <li>Watch Activity for progress; use an operator token only for protected recovery actions.</li>
            </ol>
            <p>Design-labeled issues follow the human-review design pipeline. Code auto-merge depends on each repo&apos;s merge policy.</p>
          </HelpSection>
        </div>
      </DialogContent>
    </Dialog>
  )
}
