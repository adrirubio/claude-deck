import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { CLICKABLE_CARD } from '@/lib/constants'
import type { ActiveSessionContext } from '@/types/context'

interface ActiveSessionsListProps {
  sessions: ActiveSessionContext[]
  selectedId?: string
  onSelect: (session: ActiveSessionContext) => void
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`
  return String(n)
}

function getProgressColor(pct: number): string {
  if (pct >= 95) return '[&>div]:bg-red-500'
  if (pct >= 80) return '[&>div]:bg-orange-500'
  if (pct >= 50) return '[&>div]:bg-yellow-500'
  return '[&>div]:bg-green-500'
}

export function ActiveSessionsList({ sessions, selectedId, onSelect }: ActiveSessionsListProps) {
  if (sessions.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center">
          <p className="text-muted-foreground">No active sessions detected.</p>
          <p className="text-xs text-muted-foreground mt-1">
            Sessions appear here when a Claude Code instance has been active within the last hour.
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
      {sessions.map((session) => {
        const isSelected = selectedId === session.session_id
        return (
          <Card
            key={`${session.project_folder}/${session.session_id}`}
            className={`${CLICKABLE_CARD} ${isSelected ? 'border-primary' : ''}`}
            onClick={() => onSelect(session)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onSelect(session)
              }
            }}
            tabIndex={0}
            role="button"
          >
            <CardContent className="pt-4 pb-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-medium text-sm truncate">{session.project_name}</span>
                <div className="flex gap-1">
                  {session.is_active && (
                    <Badge variant="default" className="text-[10px] px-1.5 py-0 bg-green-600">
                      Active
                    </Badge>
                  )}
                  <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                    {session.model.replace('claude-', '').split('-20')[0]}
                  </Badge>
                </div>
              </div>
              <code className="text-xs text-muted-foreground">{session.session_id.slice(0, 8)}</code>
              <div className="space-y-1">
                <div className="flex justify-between text-xs">
                  <span className="text-muted-foreground">Context</span>
                  <span className="font-medium">
                    {session.context_percentage.toFixed(0)}% ({formatTokens(session.current_context_tokens)})
                  </span>
                </div>
                <Progress
                  value={session.context_percentage}
                  className={`h-2 ${getProgressColor(session.context_percentage)}`}
                />
              </div>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
