import { Card, CardContent } from '@/components/ui/card'
import { CLICKABLE_CARD } from '@/lib/constants'
import { cn } from '@/lib/utils'
import type { CCSession } from './types'

interface SessionCardProps {
  session: CCSession
  isSelected: boolean
  onClick: () => void
}

export function SessionCard({ session, isSelected, onClick }: SessionCardProps) {
  const projectName = session.cwd.split('/').pop() || session.cwd

  return (
    <Card
      className={cn(
        CLICKABLE_CARD,
        isSelected && 'border-primary bg-primary/5'
      )}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick()
        }
      }}
      tabIndex={0}
      role="button"
    >
      <CardContent className="p-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium truncate">{session.session_name}</span>
          <span className="h-2 w-2 rounded-full bg-green-500 shrink-0" />
        </div>
        <p className="text-xs text-muted-foreground truncate mt-1" title={session.cwd}>
          {projectName}
        </p>
        <p className="text-xs text-muted-foreground mt-0.5">
          {session.tmux_target}
        </p>
      </CardContent>
    </Card>
  )
}
