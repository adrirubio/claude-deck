import { useState, useEffect, useCallback } from 'react'
import { useParams, useSearchParams, useNavigate } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ChevronLeft, ChevronRight, ArrowLeft } from 'lucide-react'
import { useSessionsApi } from '@/hooks/useSessionsApi'
import { ConversationList } from './ConversationList'
import type { SessionDetail } from '@/types/sessions'

export function SessionViewPage() {
  const { projectFolder, sessionId } = useParams<{ projectFolder: string; sessionId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const { getSessionDetail } = useSessionsApi()

  const [session, setSession] = useState<SessionDetail | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadSession = useCallback(async (page: number) => {
    if (!projectFolder || !sessionId) return

    setLoading(true)
    setError(null)
    try {
      const data = await getSessionDetail(projectFolder, sessionId, page)
      setSession(data.session)
      setCurrentPage(data.current_page)
      setTotalPages(data.total_pages)
    } catch (err) {
      console.error('Failed to load session:', err)
      setError(err instanceof Error ? err.message : 'Failed to load session')
    } finally {
      setLoading(false)
    }
  }, [getSessionDetail, projectFolder, sessionId])

  useEffect(() => {
    const page = parseInt(searchParams.get('page') || '1', 10)
    setCurrentPage(page)
    loadSession(page)
  }, [sessionId, projectFolder, searchParams, loadSession])

  const handlePageChange = (newPage: number) => {
    setSearchParams({ page: newPage.toString() })
  }

  const handleBack = () => {
    navigate('/sessions')
  }

  if (!projectFolder || !sessionId) {
    return (
      <div className="space-y-6">
        <div className="text-center py-8">
          <p className="text-muted-foreground">Invalid session URL</p>
          <Button onClick={handleBack} className="mt-4">
            Back to Sessions
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="sm" onClick={handleBack}>
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back
        </Button>
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <h1 className="text-3xl font-bold">Session: {sessionId}</h1>
            {session && <Badge variant="secondary">{session.project_name}</Badge>}
          </div>
          <p className="text-muted-foreground">
            Full conversation view
          </p>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-destructive">Error</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm">{error}</p>
            <Button onClick={() => loadSession(currentPage)} className="mt-4">
              Retry
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Loading State */}
      {loading && !session && (
        <div className="py-12 text-center">
          <p className="text-muted-foreground">Loading session...</p>
        </div>
      )}

      {/* Session Content */}
      {!loading && session && (
        <>
          {/* Session Stats */}
          <Card>
            <CardContent className="pt-6">
              <div className="flex gap-6 text-sm">
                <div className="flex flex-col">
                  <span className="text-muted-foreground">Messages</span>
                  <span className="text-2xl font-bold">{session.total_messages}</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-muted-foreground">Tool Calls</span>
                  <span className="text-2xl font-bold">{session.total_tool_calls}</span>
                </div>
                {session.models_used.length > 0 && (
                  <div className="flex flex-col">
                    <span className="text-muted-foreground">Models</span>
                    <div className="flex gap-1 mt-1">
                      {session.models_used.map(model => (
                        <Badge key={model} variant="outline" className="text-xs">
                          {model}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Conversations */}
          <ConversationList conversations={session.conversations} />

          {/* Pagination */}
          {totalPages > 1 && (
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <Button
                    variant="outline"
                    onClick={() => handlePageChange(currentPage - 1)}
                    disabled={currentPage === 1 || loading}
                  >
                    <ChevronLeft className="h-4 w-4 mr-1" />
                    Previous
                  </Button>
                  <span className="text-sm text-muted-foreground">
                    Page {currentPage} of {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    onClick={() => handlePageChange(currentPage + 1)}
                    disabled={currentPage === totalPages || loading}
                  >
                    Next
                    <ChevronRight className="h-4 w-4 ml-1" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
