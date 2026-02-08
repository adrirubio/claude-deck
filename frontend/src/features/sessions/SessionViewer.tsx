import { useState, useEffect, useCallback } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ChevronLeft, ChevronRight, Maximize2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useSessionsApi } from '@/hooks/useSessionsApi'
import { ConversationList } from './ConversationList'
import type { SessionDetail } from '@/types/sessions'

interface Props {
  sessionId: string
  projectFolder: string
  open: boolean
  onClose: () => void
}

export function SessionViewer({ sessionId, projectFolder, open, onClose }: Props) {
  const navigate = useNavigate()
  const { getSessionDetail } = useSessionsApi()
  const [session, setSession] = useState<SessionDetail | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [loading, setLoading] = useState(true)

  const loadSession = useCallback(async (page: number) => {
    setLoading(true)
    try {
      const data = await getSessionDetail(projectFolder, sessionId, page)
      setSession(data.session)
      setCurrentPage(data.current_page)
      setTotalPages(data.total_pages)
    } catch (err) {
      console.error('Failed to load session:', err)
    } finally {
      setLoading(false)
    }
  }, [getSessionDetail, projectFolder, sessionId])

  useEffect(() => {
    if (open) {
      loadSession(1)
    }
  }, [sessionId, projectFolder, open, loadSession])

  const handlePageChange = (newPage: number) => {
    loadSession(newPage)
  }

  const handleViewFullScreen = () => {
    const url = `/sessions/${projectFolder}/${sessionId}?page=${currentPage}`
    navigate(url)
  }

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-start justify-between">
            <div className="space-y-1.5">
              <DialogTitle className="flex items-center gap-2">
                Session: {sessionId}
                <Badge variant="secondary">{session?.project_name}</Badge>
              </DialogTitle>
              <DialogDescription>
                View conversation history and messages for this session
              </DialogDescription>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleViewFullScreen}
              className="flex items-center gap-1"
              title="View full screen"
            >
              <Maximize2 className="h-4 w-4" />
            </Button>
          </div>
        </DialogHeader>

        {loading && <div className="py-8 text-center">Loading...</div>}

        {!loading && session && (
          <>
            {/* Session Stats */}
            <div className="flex gap-4 text-sm text-muted-foreground mb-4">
              <span>{session.total_messages} messages</span>
              <span>{session.total_tool_calls} tool calls</span>
              {session.models_used.length > 0 && (
                <span>Models: {session.models_used.join(', ')}</span>
              )}
            </div>

            {/* Conversations */}
            <ConversationList conversations={session.conversations} />

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between mt-4 pt-4 border-t">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handlePageChange(currentPage - 1)}
                  disabled={currentPage === 1}
                >
                  <ChevronLeft className="h-4 w-4 mr-1" />
                  Previous
                </Button>
                <span className="text-sm text-muted-foreground">
                  Page {currentPage} of {totalPages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handlePageChange(currentPage + 1)}
                  disabled={currentPage === totalPages}
                >
                  Next
                  <ChevronRight className="h-4 w-4 ml-1" />
                </Button>
              </div>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
