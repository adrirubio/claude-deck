import { AlertCircle, CheckCircle2, ChevronRight, CircleHelp, RefreshCw } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { ProviderDoctorCheck, ProviderDoctorResponse } from '@/types/providers'

interface CodexDiagnosticsCardProps {
  doctor: ProviderDoctorResponse | null
  loading: boolean
  error: string | null
  onRefresh: () => void
}

const SENSITIVE_KEY_PATTERN = /(token|secret|password|credential|api[_-]?key|auth|cookie|session)/i

function redactSensitiveValues(value: unknown, parentKey = ''): unknown {
  if (value === null || value === undefined) return value

  if (Array.isArray(value)) {
    return value.map((item) => redactSensitiveValues(item, parentKey))
  }

  if (typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, child]) => [
        key,
        SENSITIVE_KEY_PATTERN.test(key) || SENSITIVE_KEY_PATTERN.test(parentKey)
          ? '[redacted]'
          : redactSensitiveValues(child, key),
      ]),
    )
  }

  if (SENSITIVE_KEY_PATTERN.test(parentKey)) {
    return '[redacted]'
  }

  return value
}

function getCheck(report: ProviderDoctorResponse['report'], id: string): ProviderDoctorCheck | null {
  return report?.checks?.[id] ?? null
}

function statusBadgeVariant(status?: string | null): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'ok') return 'default'
  if (status === 'error') return 'destructive'
  if (status === 'warn') return 'secondary'
  return 'outline'
}

function StatusIcon({ status }: { status?: string | null }) {
  if (status === 'ok') return <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
  if (status === 'error') return <AlertCircle className="h-4 w-4 text-destructive" />
  return <CircleHelp className="h-4 w-4 text-muted-foreground" />
}

function CheckRow({ label, check }: { label: string; check: ProviderDoctorCheck | null }) {
  return (
    <div className="flex items-start gap-2 rounded-md border p-3">
      <StatusIcon status={check?.status} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium">{label}</p>
          <Badge variant={statusBadgeVariant(check?.status)} className="shrink-0">
            {check?.status ?? 'unknown'}
          </Badge>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {check?.summary ?? 'No diagnostic check returned.'}
        </p>
      </div>
    </div>
  )
}

export function CodexDiagnosticsCard({ doctor, loading, error, onRefresh }: CodexDiagnosticsCardProps) {
  const report = doctor?.report ?? null
  const authCheck = getCheck(report, 'auth.credentials')
  const configCheck = getCheck(report, 'config.load')
  const installationCheck = getCheck(report, 'installation')
  const safeJson = redactSensitiveValues(doctor)

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>Codex Diagnostics</CardTitle>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={onRefresh}
          disabled={loading}
          title="Refresh diagnostics"
        >
          <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-3">
          <div>
            <p className="text-xs text-muted-foreground">Overall</p>
            <div className="mt-1 flex items-center gap-2">
              <StatusIcon status={report?.overallStatus} />
              <Badge variant={statusBadgeVariant(report?.overallStatus)}>
                {report?.overallStatus ?? 'unknown'}
              </Badge>
            </div>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Codex Version</p>
            <p className="mt-1 font-medium">{report?.codexVersion ?? 'Unknown'}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Doctor Exit</p>
            <p className="mt-1 font-medium">{doctor?.exit_code ?? 'Not run'}</p>
          </div>
        </div>

        {doctor?.parse_error && (
          <p className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {doctor.parse_error}
          </p>
        )}

        {error && (
          <p className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </p>
        )}

        {doctor?.stderr && (
          <p className="rounded-md border p-3 text-sm text-muted-foreground">
            {doctor.stderr}
          </p>
        )}

        <div className="grid gap-3 md:grid-cols-3">
          <CheckRow label="Auth" check={authCheck} />
          <CheckRow label="Config" check={configCheck} />
          <CheckRow label="Install" check={installationCheck} />
        </div>

        <details className="group rounded-md border">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-medium">
            <ChevronRight className="h-4 w-4 transition-transform group-open:rotate-90" />
            Redacted doctor JSON
          </summary>
          <pre className="max-h-80 overflow-auto border-t bg-muted p-3 text-xs">
            {JSON.stringify(safeJson, null, 2)}
          </pre>
        </details>
      </CardContent>
    </Card>
  )
}
