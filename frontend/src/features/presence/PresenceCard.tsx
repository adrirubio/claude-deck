import { useState, useEffect } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { CLICKABLE_CARD } from '@/lib/constants'
import { cn } from '@/lib/utils'
import { ActivitySparkline } from './ActivitySparkline'
import type { PresenceSession } from '@/types/presence'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface PresenceCardProps {
  session: PresenceSession
  onRemove: (sessionId: string) => void
}

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-green-500',
  idle: 'bg-muted-foreground',
  error: 'bg-red-500',
  stopped: 'bg-muted-foreground',
}

const STATUS_BORDER_TOP: Record<string, string> = {
  active: 'border-t-green-500',
  idle: 'border-t-muted-foreground',
  error: 'border-t-red-500',
  stopped: 'border-t-muted-foreground/50',
}

const STATUS_PULSE: Record<string, string> = {
  active: 'animate-pulse',
  idle: '',
  error: '',
  stopped: '',
}

function formatDuration(startedAt: string): string {
  const start = new Date(startedAt).getTime()
  const now = Date.now()
  const mins = Math.floor((now - start) / 60000)
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  const remainMins = mins % 60
  return `${hours}h ${remainMins}m`
}

function getBasename(filePath: string): string {
  return filePath.split('/').pop() || filePath
}

export function PresenceCard({ session, onRemove }: PresenceCardProps) {
  const [duration, setDuration] = useState(() => formatDuration(session.started_at))

  useEffect(() => {
    if (session.status === 'stopped') return
    const timer = setInterval(() => {
      setDuration(formatDuration(session.started_at))
    }, 1000)
    return () => clearInterval(timer)
  }, [session.started_at, session.status])

  const files = session.modified_files || []
  const visibleFiles = files.slice(-5)
  const extraCount = files.length - visibleFiles.length
  const buckets = session.activity_buckets || []

  return (
    <Card
      className={cn(
        CLICKABLE_CARD,
        'relative overflow-hidden border-t-2',
        STATUS_BORDER_TOP[session.status] || 'border-t-muted'
      )}
      tabIndex={0}
      role="article"
      aria-label={`Session ${session.label || session.session_id}`}
    >
      <CardContent className="p-4 space-y-3">
        {/* Header: status dot + label + duration + remove button */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <span
              className={cn(
                'h-2 w-2 rounded-full shrink-0',
                STATUS_COLORS[session.status],
                STATUS_PULSE[session.status]
              )}
            />
            <span className="font-semibold text-sm truncate">
              {session.label || session.session_id.slice(0, 8)}
            </span>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Badge variant="outline" className="text-xs font-normal" title="Duration since session start">
              {duration}
            </Badge>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={(e) => { e.stopPropagation(); onRemove(session.session_id) }}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); onRemove(session.session_id) } }}
              aria-label="Remove session"
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
        </div>

        {/* Narrative */}
        {session.last_narrative && (
          <div className="rounded-md bg-muted/50 border px-3 py-2">
            <p className="text-xs text-muted-foreground italic line-clamp-2">
              &ldquo;{session.last_narrative}&rdquo;
            </p>
          </div>
        )}

        {/* Modified files */}
        {visibleFiles.length > 0 && (
          <div className="space-y-1">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Modified files
            </span>
            <div className="flex flex-wrap gap-1">
              {visibleFiles.map((f) => (
                <Badge key={f} variant="outline" className="text-[11px] font-mono px-1.5 py-0">
                  {getBasename(f)}
                </Badge>
              ))}
              {extraCount > 0 && (
                <Badge variant="secondary" className="text-[11px] px-1.5 py-0">
                  +{extraCount}
                </Badge>
              )}
            </div>
          </div>
        )}

        {/* Last command */}
        {session.last_command && (
          <div className="flex items-center gap-1.5 rounded bg-muted/50 px-2.5 py-1.5 text-[11px]">
            <span className="text-muted-foreground">$</span>
            <span className="font-mono truncate flex-1">
              {session.last_command.length > 80
                ? session.last_command.slice(0, 80) + '...'
                : session.last_command}
            </span>
            {session.last_command_exit != null && (
              session.last_command_exit === 0 ? (
                <span className="text-green-500 shrink-0">ok</span>
              ) : (
                <span className="text-red-500 shrink-0">exit {session.last_command_exit}</span>
              )
            )}
          </div>
        )}

        {/* Activity sparkline */}
        {buckets.length > 0 && (
          <ActivitySparkline buckets={buckets} />
        )}
      </CardContent>
    </Card>
  )
}
