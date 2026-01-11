import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import type { RawFileContent } from '@/types/config'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { JsonViewer } from '@/components/shared/JsonViewer'

interface ConfigFileViewerProps {
  filePath: string | null
}

export function ConfigFileViewer({ filePath }: ConfigFileViewerProps) {
  const [content, setContent] = useState<RawFileContent | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!filePath) {
      setContent(null)
      return
    }

    const fetchContent = async () => {
      setLoading(true)
      setError(null)

      try {
        const result = await api.get<RawFileContent>(`config/raw?path=${encodeURIComponent(filePath)}`)
        setContent(result)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load file')
      } finally {
        setLoading(false)
      }
    }

    fetchContent()
  }, [filePath])

  if (!filePath) {
    return (
      <Card className="h-full flex items-center justify-center">
        <CardContent className="pt-6">
          <p className="text-sm text-muted-foreground text-center">
            Select a file to view its content
          </p>
        </CardContent>
      </Card>
    )
  }

  if (loading) {
    return (
      <Card className="h-full">
        <CardHeader>
          <CardTitle>Loading...</CardTitle>
          <CardDescription>{filePath}</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Loading file content...</p>
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card className="h-full border-destructive">
        <CardHeader>
          <CardTitle className="text-destructive">Error</CardTitle>
          <CardDescription>{filePath}</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm">{error}</p>
        </CardContent>
      </Card>
    )
  }

  if (!content || !content.exists) {
    return (
      <Card className="h-full">
        <CardHeader>
          <CardTitle>File Not Found</CardTitle>
          <CardDescription>{filePath}</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">This file does not exist.</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="h-full flex flex-col">
      <CardHeader>
        <CardTitle className="text-lg">{filePath.split('/').pop()}</CardTitle>
        <CardDescription className="text-xs">{filePath}</CardDescription>
      </CardHeader>
      <CardContent className="flex-1 overflow-auto">
        <JsonViewer data={content.content} />
      </CardContent>
    </Card>
  )
}
