import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ExternalLink } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { useNavigate } from 'react-router-dom'
import type { SessionSummary } from '@/types/sessions'

interface Props {
  session: SessionSummary
}

export function SessionCard({ session }: Props) {
  const navigate = useNavigate()
  const sizeKB = (session.size_bytes / 1024).toFixed(1)
  const timeAgo = formatDistanceToNow(new Date(session.modified_at), { addSuffix: true })

  const handleClick = (e: React.MouseEvent) => {
    const url = `/sessions/${session.project_folder}/${session.id}`

    if (e.ctrlKey || e.metaKey || e.button === 1) {
      // Ctrl+click, Cmd+click, or middle-click: open in new window
      window.open(url, '_blank', 'noopener,noreferrer')
    } else {
      navigate(url)
    }
  }

  const handleOpenInNewWindow = (e: React.MouseEvent) => {
    e.stopPropagation()
    const url = `/sessions/${session.project_folder}/${session.id}`
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  return (
    <Card
      className="cursor-pointer hover:bg-accent transition-colors group"
      onClick={handleClick}
      onAuxClick={handleClick}
    >
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <Badge variant="secondary">{session.project_name}</Badge>
              <span className="text-xs text-muted-foreground">{timeAgo}</span>
            </div>
            <p className="text-sm line-clamp-2">{session.summary}</p>
            <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
              <span>{session.total_messages} messages</span>
              <span>{session.total_tool_calls} tools</span>
              <span>{sizeKB} KB</span>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleOpenInNewWindow}
            className="opacity-0 group-hover:opacity-100 transition-opacity"
            title="Open in new window"
          >
            <ExternalLink className="h-4 w-4" />
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
