import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { ArrowLeft, FileText, Calendar, HardDrive, Code, Table, GitBranch } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { MarkdownRenderer } from '@/components/shared/MarkdownRenderer'
import { RefreshButton } from '@/components/shared/RefreshButton'
import { usePlansApi } from '@/hooks/usePlansApi'
import { formatBytes } from '@/types/backup'
import type { PlanDetail } from '@/types/plans'

export function PlanDetailPage() {
  const { filename } = useParams<{ filename: string }>()
  const navigate = useNavigate()
  const { getPlan } = usePlansApi()
  const [plan, setPlan] = useState<PlanDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchPlan = useCallback(async () => {
    if (!filename) return
    setLoading(true)
    setError(null)
    try {
      const data = await getPlan(filename)
      setPlan(data.plan)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load plan')
    } finally {
      setLoading(false)
    }
  }, [filename, getPlan])

  useEffect(() => {
    fetchPlan()
  }, [fetchPlan])

  const backButton = (
    <Button variant="ghost" size="sm" onClick={() => navigate('/plans')} className="mb-2">
      <ArrowLeft className="h-4 w-4 mr-2" />
      Back to Plans
    </Button>
  )

  if (loading) {
    return (
      <div className="space-y-6">
        {backButton}
        <Card>
          <CardContent className="py-8">
            <p className="text-center text-muted-foreground">Loading plan...</p>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (error || !plan) {
    return (
      <div className="space-y-6">
        {backButton}
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-destructive">Error</CardTitle>
            <CardDescription>{error || 'Plan not found'}</CardDescription>
          </CardHeader>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          {backButton}
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <FileText className="h-8 w-8" />
            {plan.title}
          </h1>
          <div className="flex items-center gap-3 mt-2 text-sm text-muted-foreground">
            <span className="flex items-center gap-1" title={new Date(plan.modified_at).toLocaleString()}>
              <Calendar className="h-3 w-3" />
              {new Date(plan.modified_at).toLocaleDateString()}
            </span>
            <span className="flex items-center gap-1">
              <HardDrive className="h-3 w-3" />
              {formatBytes(plan.size_bytes)}
            </span>
            {plan.code_block_count > 0 && (
              <span className="flex items-center gap-1">
                <Code className="h-3 w-3" />
                {plan.code_block_count} code block{plan.code_block_count !== 1 ? 's' : ''}
              </span>
            )}
            {plan.table_count > 0 && (
              <span className="flex items-center gap-1">
                <Table className="h-3 w-3" />
                {plan.table_count} table{plan.table_count !== 1 ? 's' : ''}
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-1 font-mono">
            {plan.filename}
          </p>
        </div>
        <RefreshButton onClick={fetchPlan} loading={loading} />
      </div>

      {/* Table of Contents */}
      {plan.headings.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Contents</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="text-sm space-y-1">
              {plan.headings.map((heading, i) => (
                <li key={i} className="text-muted-foreground hover:text-foreground">
                  {heading}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* Plan Content */}
      <Card>
        <CardContent className="pt-6">
          <MarkdownRenderer content={plan.content} />
        </CardContent>
      </Card>

      {/* Linked Sessions */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <GitBranch className="h-4 w-4" />
            Linked Sessions
          </CardTitle>
          <CardDescription>
            Sessions that used this plan (matched by slug: {plan.slug})
          </CardDescription>
        </CardHeader>
        <CardContent>
          {plan.linked_sessions.length === 0 ? (
            <p className="text-sm text-muted-foreground">No linked sessions found</p>
          ) : (
            <div className="space-y-3">
              {plan.linked_sessions.map((session) => (
                <div
                  key={session.session_id}
                  className="flex items-center justify-between p-3 border rounded-lg"
                >
                  <div className="space-y-1">
                    <Link
                      to={`/sessions/${session.project_folder}/${session.session_id}`}
                      className="text-sm font-mono text-primary hover:underline"
                    >
                      {session.session_id.substring(0, 8)}...
                    </Link>
                    <p className="text-xs text-muted-foreground">
                      {session.project_name}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {session.git_branch && (
                      <Badge variant="outline" className="text-xs">
                        <GitBranch className="h-3 w-3 mr-1" />
                        {session.git_branch}
                      </Badge>
                    )}
                    {session.first_seen && (
                      <span className="text-xs text-muted-foreground">
                        {new Date(session.first_seen).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
