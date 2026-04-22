import { useState } from 'react'
import { Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { API_BASE_URL } from '@/lib/constants'
import { buildEndpoint } from '@/lib/api'

type Dataset = 'summary' | 'daily' | 'sessions' | 'monthly' | 'blocks'
type Format = 'json' | 'csv'

const DATASET_OPTIONS: { value: Dataset; label: string }[] = [
  { value: 'daily', label: 'Daily' },
  { value: 'sessions', label: 'Sessions' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'blocks', label: 'Billing Blocks' },
  { value: 'summary', label: 'Summary' },
]

interface ExportCardProps {
  projectPath: string | null
}

export function ExportCard({ projectPath }: ExportCardProps) {
  const [dataset, setDataset] = useState<Dataset>('daily')
  const [format, setFormat] = useState<Format>('csv')

  const handleDownload = () => {
    const endpoint = buildEndpoint('usage/export', {
      dataset,
      format,
      project_path: projectPath ?? undefined,
    })
    // Trigger a real download so the browser honors Content-Disposition
    const url = `${API_BASE_URL}${endpoint}`
    const a = document.createElement('a')
    a.href = url
    a.rel = 'noopener'
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle>Export</CardTitle>
        <CardDescription>
          Download usage data as JSON or CSV. Export respects the project filter above.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap items-center gap-3">
          <Select value={dataset} onValueChange={(v) => setDataset(v as Dataset)}>
            <SelectTrigger className="w-[180px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DATASET_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={format} onValueChange={(v) => setFormat(v as Format)}>
            <SelectTrigger className="w-[120px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="csv">CSV</SelectItem>
              <SelectItem value="json">JSON</SelectItem>
            </SelectContent>
          </Select>

          <Button onClick={handleDownload}>
            <Download className="h-4 w-4 mr-2" />
            Download
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
