import { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { ClipboardList, Search, Calendar, HardDrive, FileText } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { RefreshButton } from '@/components/shared/RefreshButton'
import { usePlansApi } from '@/hooks/usePlansApi'
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

  // Client-side filtering by search query
  const filteredPlans = useMemo(() => {
    if (!searchQuery.trim()) return plans
    const q = searchQuery.toLowerCase()
    return plans.filter(
      p => p.title.toLowerCase().includes(q) ||
           p.excerpt.toLowerCase().includes(q) ||
           p.slug.toLowerCase().includes(q)
    )
  }, [plans, searchQuery])

  const grouped = useMemo(() => groupByDate(filteredPlans), [filteredPlans])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <ClipboardList className="h-8 w-8" />
            Plans
          </h1>
          <p className="text-muted-foreground">
            Browse and search your Claude Code execution plans
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
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Total Plans</CardDescription>
              <CardTitle className="text-3xl">{stats.total_plans}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Execution plan files
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Date Range</CardDescription>
              <CardTitle className="text-lg">
                {stats.oldest_date
                  ? `${new Date(stats.oldest_date).toLocaleDateString()} — ${new Date(stats.newest_date!).toLocaleDateString()}`
                  : 'No plans'}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <Calendar className="h-3 w-3" />
                <span>First to latest plan</span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Total Size</CardDescription>
              <CardTitle className="text-3xl">{formatBytes(stats.total_size_bytes)}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <HardDrive className="h-3 w-3" />
                <span>Combined plan files</span>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search plans by title, content, or slug..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="pl-10"
        />
      </div>

      {/* Plan List */}
      {loading && plans.length === 0 ? (
        <Card>
          <CardContent className="py-8">
            <p className="text-center text-muted-foreground">Loading plans...</p>
          </CardContent>
        </Card>
      ) : filteredPlans.length === 0 ? (
        <Card>
          <CardContent className="py-8">
            <p className="text-center text-muted-foreground">
              {searchQuery ? 'No plans match your search' : 'No plans found'}
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
                        </div>
                        <div className="flex flex-col items-end gap-1 flex-shrink-0">
                          <span
                            className="text-xs text-muted-foreground"
                            title={new Date(plan.modified_at).toLocaleString()}
                          >
                            {formatRelativeDate(plan.modified_at)}
                          </span>
                          <Badge variant="outline" className="text-xs">
                            {formatBytes(plan.size_bytes)}
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
