import { ChevronRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { CodexProfileResolution, CodexProfileSource } from '@/types/providers'

interface CodexProfileResolverCardProps {
  resolution: CodexProfileResolution | null | undefined
}

function formatValue(value: unknown): string {
  if (value === undefined) return 'unset'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

function ProfileSourceRow({ source }: { source: CodexProfileSource }) {
  return (
    <div className="rounded-md border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{source.name}</p>
          {source.path && (
            <code className="mt-1 block max-w-full truncate rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
              {source.path}
            </code>
          )}
        </div>
        <Badge variant={source.parse_error ? 'destructive' : 'outline'}>{source.source}</Badge>
      </div>
      {source.parse_error ? (
        <p className="mt-2 text-xs text-destructive">{source.parse_error}</p>
      ) : source.overrides.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {source.overrides.map((override) => (
            <Badge key={override.key} variant="secondary">
              {override.key}: {formatValue(override.base)} {'->'} {formatValue(override.value)}
            </Badge>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">No safe setting overrides detected.</p>
      )}
    </div>
  )
}

export function CodexProfileResolverCard({ resolution }: CodexProfileResolverCardProps) {
  if (!resolution) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Profile Resolution</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-md border p-3">
            <p className="text-sm font-medium">Active Profile</p>
            <p className="mt-1 truncate text-2xl font-semibold">{resolution.active_profile ?? 'Default'}</p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-sm font-medium">Profile v2</p>
            <p className="mt-1 truncate text-2xl font-semibold">{resolution.active_profile_v2 ?? 'Unset'}</p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-sm font-medium">Profiles Found</p>
            <p className="mt-1 text-2xl font-semibold">{resolution.profiles.length}</p>
          </div>
        </div>

        {(resolution.missing_references.length > 0 || resolution.malformed_profiles.length > 0) && (
          <div className="space-y-2">
            {resolution.missing_references.map((missing) => (
              <p
                key={`${missing.reference}:${missing.name}`}
                className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
              >
                Missing {missing.reference} profile "{missing.name}"
                {missing.expected_file ? ` at ${missing.expected_file}` : ' with an unsafe file reference'}
              </p>
            ))}
            {resolution.malformed_profiles.map((profile) => (
              <p
                key={`${profile.name}:${profile.path}`}
                className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
              >
                Malformed profile "{profile.name}": {profile.parse_error}
              </p>
            ))}
          </div>
        )}

        {resolution.active_sources.length > 0 ? (
          <div className="space-y-2">
            <p className="text-sm font-medium">Active Sources</p>
            {resolution.active_sources.map((source) => (
              <ProfileSourceRow key={`${source.source}:${source.name}:${source.path ?? ''}`} source={source} />
            ))}
          </div>
        ) : (
          <p className="rounded-md border p-3 text-sm text-muted-foreground">
            No active profile overrides are applied.
          </p>
        )}

        <details className="group rounded-md border">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-medium">
            <ChevronRight className="h-4 w-4 transition-transform group-open:rotate-90" />
            Effective safe summary
          </summary>
          <pre className="max-h-72 overflow-auto border-t bg-muted p-3 text-xs">
            {JSON.stringify(resolution.effective_summary, null, 2)}
          </pre>
        </details>
      </CardContent>
    </Card>
  )
}
