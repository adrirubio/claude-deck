import { useEffect, useState, useCallback, useRef } from 'react'
import { Gauge } from 'lucide-react'
import { RefreshButton } from '@/components/shared/RefreshButton'
import { useContextApi } from '@/hooks/useContextApi'
import { ActiveSessionsList } from './ActiveSessionsList'
import { ContextGauge } from './ContextGauge'
import { ContextTimelineChart } from './ContextTimelineChart'
import { ContentBreakdownChart } from './ContentBreakdownChart'
import { FileConsumptionTable } from './FileConsumptionTable'
import { CacheEfficiencyCard } from './CacheEfficiencyCard'
import { ProjectionsCard } from './ProjectionsCard'
import type { ActiveSessionContext, ContextAnalysis } from '@/types/context'

export function ContextPage() {
  const { getActiveSessions, getSessionContext } = useContextApi()
  const [sessions, setSessions] = useState<ActiveSessionContext[]>([])
  const [selectedSession, setSelectedSession] = useState<ActiveSessionContext | null>(null)
  const [analysis, setAnalysis] = useState<ContextAnalysis | null>(null)
  const [loading, setLoading] = useState(true)
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchSessions = useCallback(async () => {
    try {
      const data = await getActiveSessions()
      setSessions(data.sessions)
    } catch {
      // Silently handle polling errors
    } finally {
      setLoading(false)
    }
  }, [getActiveSessions])

  const fetchAnalysis = useCallback(async (session: ActiveSessionContext) => {
    setAnalysisLoading(true)
    try {
      const data = await getSessionContext(session.project_folder, session.session_id)
      setAnalysis(data.analysis)
    } catch {
      setAnalysis(null)
    } finally {
      setAnalysisLoading(false)
    }
  }, [getSessionContext])

  const handleSelect = useCallback((session: ActiveSessionContext) => {
    setSelectedSession(session)
    fetchAnalysis(session)
  }, [fetchAnalysis])

  const handleRefresh = useCallback(async () => {
    setLoading(true)
    await fetchSessions()
    if (selectedSession) {
      await fetchAnalysis(selectedSession)
    }
  }, [fetchSessions, fetchAnalysis, selectedSession])

  // Initial fetch + auto-poll
  useEffect(() => {
    fetchSessions()

    const startPolling = () => {
      intervalRef.current = setInterval(fetchSessions, 10_000)
    }

    const handleVisibility = () => {
      if (document.hidden) {
        if (intervalRef.current) clearInterval(intervalRef.current)
      } else {
        fetchSessions()
        startPolling()
      }
    }

    startPolling()
    document.addEventListener('visibilitychange', handleVisibility)

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [fetchSessions])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Gauge className="h-8 w-8" />
            Context Window
          </h1>
          <p className="text-muted-foreground">
            Analyze context window usage across active sessions
          </p>
        </div>
        <RefreshButton onClick={handleRefresh} loading={loading} />
      </div>

      {/* Active Sessions */}
      <ActiveSessionsList
        sessions={sessions}
        selectedId={selectedSession?.session_id}
        onSelect={handleSelect}
      />

      {/* Analysis */}
      {analysisLoading && (
        <div className="py-8 text-center">
          <p className="text-muted-foreground">Analyzing session...</p>
        </div>
      )}

      {analysis && !analysisLoading && (
        <div className="space-y-4">
          {/* Top row: gauge + projections + cache */}
          <div className="grid gap-4 md:grid-cols-3">
            <div className="flex items-center justify-center">
              <ContextGauge
                percentage={analysis.context_percentage}
                currentTokens={analysis.current_context_tokens}
                maxTokens={analysis.max_context_tokens}
                model={analysis.model}
              />
            </div>
            <ProjectionsCard
              avgTokensPerTurn={analysis.avg_tokens_per_turn}
              estimatedTurnsRemaining={analysis.estimated_turns_remaining}
              contextZone={analysis.context_zone}
              totalTurns={analysis.total_turns}
            />
            <CacheEfficiencyCard cache={analysis.cache_efficiency} />
          </div>

          {/* Charts */}
          <ContextTimelineChart
            snapshots={analysis.snapshots}
            maxTokens={analysis.max_context_tokens}
          />

          <div className="grid gap-4 md:grid-cols-2">
            <ContentBreakdownChart categories={analysis.content_categories} />
            <FileConsumptionTable files={analysis.file_consumptions} />
          </div>
        </div>
      )}
    </div>
  )
}
