import { useState, useEffect, useCallback } from 'react'
import { useSessionsApi } from '@/hooks/useSessionsApi'
import { SessionCard } from './SessionCard'
import type { SessionSummary } from '@/types/sessions'

interface Props {
  projectFolder: string | null
}

export function SessionList({ projectFolder }: Props) {
  const { listSessions } = useSessionsApi()
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading] = useState(true)

  const loadSessions = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listSessions({
        project_folder: projectFolder || undefined,
        limit: 50,
        sort_by: 'date',
        sort_order: 'desc',
      })
      setSessions(data.sessions)
    } catch (err) {
      console.error('Failed to load sessions:', err)
    } finally {
      setLoading(false)
    }
  }, [listSessions, projectFolder])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  if (loading) {
    return <div className="text-center py-8">Loading sessions...</div>
  }

  if (sessions.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No sessions found
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {sessions.map(session => (
        <SessionCard
          key={`${session.project_folder}/${session.id}`}
          session={session}
        />
      ))}
    </div>
  )
}
