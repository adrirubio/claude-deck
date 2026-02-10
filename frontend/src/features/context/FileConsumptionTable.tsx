import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import type { FileConsumption } from '@/types/context'

interface FileConsumptionTableProps {
  files: FileConsumption[]
  showHelp?: boolean
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`
  return String(n)
}

function shortenPath(path: string): string {
  const parts = path.split('/')
  if (parts.length <= 3) return path
  return '.../' + parts.slice(-3).join('/')
}

export function FileConsumptionTable({ files, showHelp }: FileConsumptionTableProps) {
  if (files.length === 0) {
    return null
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Top File Reads</CardTitle>
        {showHelp && (
          <CardDescription>
            Files read during this session. Repeated reads of the same file consume extra tokens each time, which can fill the context window faster.
          </CardDescription>
        )}
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left">
                <th className="pb-2 font-medium text-muted-foreground">File</th>
                <th className="pb-2 font-medium text-muted-foreground text-right">Reads</th>
                <th className="pb-2 font-medium text-muted-foreground text-right">Est. Tokens</th>
              </tr>
            </thead>
            <tbody>
              {files.slice(0, 20).map((file) => (
                <tr key={file.file_path} className="border-b border-border/50">
                  <td className="py-1.5 font-mono text-xs" title={file.file_path}>
                    {shortenPath(file.file_path)}
                    {file.read_count > 1 && (
                      <Badge variant="secondary" className="ml-2 text-[10px] px-1 py-0">
                        x{file.read_count}
                      </Badge>
                    )}
                  </td>
                  <td className="py-1.5 text-right tabular-nums">{file.read_count}</td>
                  <td className="py-1.5 text-right tabular-nums">{formatTokens(file.estimated_tokens)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}
