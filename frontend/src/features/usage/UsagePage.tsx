import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { BarChart3 } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { RefreshButton } from '@/components/shared/RefreshButton'
import { useUsageApi } from '@/hooks/useUsageApi'
import { useProjectContext } from '@/contexts/ProjectContext'
import { UsageSummaryCards } from './UsageSummaryCards'
import { DailyUsageChart } from './DailyUsageChart'
import { CostChart } from './CostChart'
import { SessionUsageTable } from './SessionUsageTable'
import { BlocksView } from './BlocksView'
import { MonthlyUsageChart } from './MonthlyUsageChart'
import type {
  UsageSummary,
  DailyUsage,
  SessionUsage,
  MonthlyUsage,
  SessionBlock,
} from '@/types/usage'

export function UsagePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { projects, activeProject } = useProjectContext()
  const { getSummary, getDaily, getSessions, getMonthly, getBlocks } = useUsageApi()

  const [selectedProject, setSelectedProject] = useState<string | null>(
    activeProject?.path || searchParams.get('project') || null
  )
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Data states
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [dailyData, setDailyData] = useState<DailyUsage[]>([])
  const [sessionData, setSessionData] = useState<SessionUsage[]>([])
  const [monthlyData, setMonthlyData] = useState<MonthlyUsage[]>([])
  const [blocks, setBlocks] = useState<SessionBlock[]>([])
  const [activeBlock, setActiveBlock] = useState<SessionBlock | undefined>()
  const [totalSessionCost, setTotalSessionCost] = useState(0)
  const [totalBlockCost, setTotalBlockCost] = useState(0)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = selectedProject ? { project_path: selectedProject } : undefined

      // Fetch all data in parallel
      const [summaryRes, dailyRes, sessionRes, monthlyRes, blockRes] = await Promise.all([
        getSummary(params),
        getDaily(params),
        getSessions({ ...params, limit: 100 }),
        getMonthly(params),
        getBlocks({ ...params, recent: true }),
      ])

      setSummary(summaryRes.summary)
      setDailyData(dailyRes.data)
      setSessionData(sessionRes.data)
      setTotalSessionCost(sessionRes.total_cost)
      setMonthlyData(monthlyRes.data)
      setBlocks(blockRes.data)
      setActiveBlock(blockRes.active_block)
      setTotalBlockCost(blockRes.total_cost)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load usage data')
    } finally {
      setLoading(false)
    }
  }, [selectedProject, getSummary, getDaily, getSessions, getMonthly, getBlocks])

  useEffect(() => {
    loadData()
  }, [loadData])

  const handleProjectChange = (value: string) => {
    const path = value === 'all' ? null : value
    setSelectedProject(path)
    setSearchParams(path ? { project: path } : {})
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <BarChart3 className="h-8 w-8" />
            Usage Tracking
          </h1>
          <p className="text-muted-foreground">
            Monitor your Claude Code token usage and costs
          </p>
        </div>
        <RefreshButton onClick={loadData} loading={loading} />
      </div>

      {/* Error Display */}
      {error && (
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-destructive">Error</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm">{error}</p>
          </CardContent>
        </Card>
      )}

      {/* Project Filter */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle>Filter</CardTitle>
          <CardDescription>Filter usage data by project</CardDescription>
        </CardHeader>
        <CardContent>
          <Select value={selectedProject || 'all'} onValueChange={handleProjectChange}>
            <SelectTrigger className="w-[300px]">
              <SelectValue placeholder="All projects" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Projects</SelectItem>
              {projects.map(p => (
                <SelectItem key={p.path} value={p.path}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      {/* Summary Cards */}
      <UsageSummaryCards summary={summary} loading={loading} />

      {/* Tabbed Views */}
      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="daily">Daily</TabsTrigger>
          <TabsTrigger value="sessions">Sessions</TabsTrigger>
          <TabsTrigger value="monthly">Monthly</TabsTrigger>
          <TabsTrigger value="blocks">
            Blocks
            {activeBlock && (
              <span className="ml-1 w-2 h-2 bg-success rounded-full animate-pulse" />
            )}
          </TabsTrigger>
        </TabsList>

        {/* Overview Tab */}
        <TabsContent value="overview" className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <CostChart data={dailyData} loading={loading} />
            <MonthlyUsageChart data={monthlyData} loading={loading} />
          </div>
          <DailyUsageChart data={dailyData.slice(0, 14)} loading={loading} />
        </TabsContent>

        {/* Daily Tab */}
        <TabsContent value="daily" className="space-y-4">
          <DailyUsageChart data={dailyData} loading={loading} />
          <CostChart data={dailyData} loading={loading} />
        </TabsContent>

        {/* Sessions Tab */}
        <TabsContent value="sessions">
          <SessionUsageTable
            data={sessionData}
            loading={loading}
            totalCost={totalSessionCost}
          />
        </TabsContent>

        {/* Monthly Tab */}
        <TabsContent value="monthly">
          <MonthlyUsageChart data={monthlyData} loading={loading} />
        </TabsContent>

        {/* Blocks Tab */}
        <TabsContent value="blocks">
          <BlocksView
            blocks={blocks}
            activeBlock={activeBlock}
            loading={loading}
            totalCost={totalBlockCost}
          />
        </TabsContent>
      </Tabs>
    </div>
  )
}
