import { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { ClipboardList, Search, Calendar, HardDrive, FileText } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { RefreshButton } from '@/components/shared/RefreshButton'
import { usePlansApi } from '@/hooks/usePlansApi'
import { useProviderContext } from '@/contexts/ProviderContext'
import { CLICKABLE_CARD } from '@/lib/constants'
import { formatBytes } from '@/types/backup'
import type { PlanSummary, PlanStatsResponse } from '@/types/plans'

function formatRelativeDate(isoDate: string): string {
  const date = new Date(isoDate)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`
  return date.toLocaleDateString()
}

function groupByDate(plans: PlanSummary[]): { label: string; plans: PlanSummary[] }[] {
  const now = new Date()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const weekStart = new Date(todayStart.getTime() - 7 * 86400000)
  const monthStart = new Date(todayStart.getTime() - 30 * 86400000)

  const groups: Record<string, PlanSummary[]> = {
    'Today': [],
    'This Week': [],
    'This Month': [],
    'Older': [],
  }

  for (const plan of plans) {
    const date = new Date(plan.modified_at)
    if (date >= todayStart) groups['Today'].push(plan)
    else if (date >= weekStart) groups['This Week'].push(plan)
    else if (date >= monthStart) groups['This Month'].push(plan)
    else groups['Older'].push(plan)
  }

  return Object.entries(groups)
    .filter(([, plans]) => plans.length > 0)
    .map(([label, plans]) => ({ label, plans }))
}

export function PlansPage() {
  const navigate = useNavigate()
  const { listPlans, getStats } = usePlansApi()
  const { selectedProviderId } = useProviderContext()
  const [plans, setPlans] = useState<PlanSummary[]>([])
  const [stats, setStats] = useState<PlanStatsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [plansData, statsData] = await Promise.all([
        listPlans(),
        getStats(),
      ])
      setPlans(plansData.plans)
      setStats(statsData)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load plans')
    } finally {
      setLoading(false)
    }
  }, [listPlans, getStats])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const providerPlans = useMemo(
    () => plans.filter((plan) => (plan.source ?? 'claude-code') === selectedProviderId),
    [plans, selectedProviderId],
  )
  const providerStats = stats?.source === selectedProviderId ? stats : null

  // Client-side filtering by search query
  const filteredPlans = useMemo(() => {
    if (!searchQuery.trim()) return providerPlans
    const q = searchQuery.toLowerCase()
    return providerPlans.filter(
      p => p.title.toLowerCase().includes(q) ||
           p.excerpt.toLowerCase().includes(q) ||
           p.slug.toLowerCase().includes(q)
    )
  }, [providerPlans, searchQuery])

  const grouped = useMemo(() => groupByDate(filteredPlans), [filteredPlans])
  const isCodex = selectedProviderId === 'codex-cli'
  const sourceDescription = isCodex
    ? 'Browse Codex update_plan snapshots from local session history'
    : 'Browse and search your Claude Code execution plans'
  const planNoun = isCodex ? 'Plan Snapshots' : 'Total Plans'
  const sizeDescription = isCodex ? 'Source JSONL data' : 'Combined plan files'
  const emptyText = isCodex
    ? 'No Codex plan snapshots found'
    : 'No plans found'
  const searchPlaceholder = isCodex
    ? 'Search snapshots by step, repo, or session...'
    : 'Search plans by title, content, or slug...'

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <ClipboardList className="h-8 w-8" />
            Plans
          </h1>
          <p className="text-muted-foreground">
            {sourceDescription}
          </p>
        </div>
        <RefreshButton onClick={fetchData} loading={loading} />
      </div>

      {error && (
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-destructive">Error</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      )}

      {/* Stats Row */}
      {providerStats && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>{planNoun}</CardDescription>
              <CardTitle className="text-3xl">{providerStats.total_plans}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                {isCodex ? 'Latest snapshots per Codex thread' : 'Execution plan files'}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Date Range</CardDescription>
              <CardTitle className="text-lg">
                {providerStats.oldest_date
                  ? `${new Date(providerStats.oldest_date).toLocaleDateString()} — ${new Date(providerStats.newest_date!).toLocaleDateString()}`
                  : 'No plans'}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <Calendar className="h-3 w-3" />
                <span>{isCodex ? 'First to latest snapshot' : 'First to latest plan'}</span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>{isCodex ? 'Source Size' : 'Total Size'}</CardDescription>
              <CardTitle className="text-3xl">{formatBytes(providerStats.total_size_bytes)}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <HardDrive className="h-3 w-3" />
                <span>{sizeDescription}</span>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder={searchPlaceholder}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="pl-10"
        />
      </div>

      {/* Plan List */}
      {loading && providerPlans.length === 0 ? (
        <Card>
          <CardContent className="py-8">
            <p className="text-center text-muted-foreground">Loading plans...</p>
          </CardContent>
        </Card>
      ) : filteredPlans.length === 0 ? (
        <Card>
          <CardContent className="py-8">
            <p className="text-center text-muted-foreground">
              {searchQuery ? 'No plans match your search' : emptyText}
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6">
          {grouped.map(group => (
            <div key={group.label}>
              <h2 className="text-sm font-semibold text-muted-foreground mb-3">{group.label}</h2>
              <div className="space-y-2">
                {group.plans.map(plan => (
                  <Card
                    key={plan.filename}
                    className={CLICKABLE_CARD}
                    onClick={() => navigate(`/plans/${encodeURIComponent(plan.filename)}`)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        navigate(`/plans/${encodeURIComponent(plan.filename)}`)
                      }
                    }}
                    tabIndex={0}
                    role="button"
                  >
                    <CardContent className="py-4">
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <FileText className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                            <h3 className="font-medium truncate">{plan.title}</h3>
                          </div>
                          <p className="text-sm text-muted-foreground line-clamp-2">
                            {plan.excerpt}
                          </p>
                          {isCodex && plan.step_count != null && (
                            <div className="flex flex-wrap gap-2 mt-2">
                              <Badge variant="secondary" className="text-xs">
                                {plan.step_count} step{plan.step_count !== 1 ? 's' : ''}
                              </Badge>
                              <Badge variant="outline" className="text-xs">
                                {plan.completed_count ?? 0} completed
                              </Badge>
                              <Badge variant="outline" className="text-xs">
                                {plan.in_progress_count ?? 0} active
                              </Badge>
                              <Badge variant="outline" className="text-xs">
                                {plan.pending_count ?? 0} pending
                              </Badge>
                            </div>
                          )}
                        </div>
                        <div className="flex flex-col items-end gap-1 flex-shrink-0">
                          <span
                            className="text-xs text-muted-foreground"
                            title={new Date(plan.modified_at).toLocaleString()}
                          >
                            {formatRelativeDate(plan.modified_at)}
                          </span>
                          <Badge variant="outline" className="text-xs">
                            {isCodex ? plan.source_label : formatBytes(plan.size_bytes)}
                          </Badge>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
