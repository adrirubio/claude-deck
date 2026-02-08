import { useState, useEffect, useCallback } from 'react'
import { Settings, Eye, Edit, Shield } from 'lucide-react'
import type { ConfigFileListResponse, ConfigValue } from '@/types/config'
import { RefreshButton } from '@/components/shared/RefreshButton'
import { ConfigFileList } from './ConfigFileList'
import { ConfigFileViewer } from './ConfigFileViewer'
import { SettingsEditor } from './SettingsEditor'
import { ScopeResolver } from './ScopeResolver'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { apiClient, buildEndpoint } from '@/lib/api'
import { useProjectContext } from '@/contexts/ProjectContext'
import { toast } from 'sonner'

export function ConfigViewerPage() {
  const { activeProject } = useProjectContext()
  const [data, setData] = useState<ConfigFileListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'editor' | 'scopes' | 'viewer'>('editor')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const endpoint = buildEndpoint('config/files', { project_path: activeProject?.path })
      const response = await apiClient<ConfigFileListResponse>(endpoint)
      setData(response)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load config files'
      setError(message)
      toast.error(message)
    } finally {
      setLoading(false)
    }
  }, [activeProject?.path])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const handleOverrideInLocal = async (key: string, value: ConfigValue) => {
    const parts = key.split('.')
    const settings: Record<string, ConfigValue> = {}
    let current: Record<string, ConfigValue> = settings
    for (let i = 0; i < parts.length - 1; i++) {
      const nested: Record<string, ConfigValue> = {}
      current[parts[i]] = nested
      current = nested
    }
    current[parts[parts.length - 1]] = value

    try {
      await apiClient('config/settings', {
        method: 'PUT',
        body: JSON.stringify({
          scope: 'local',
          settings,
          project_path: activeProject?.path
        })
      })
      toast.success(`Setting "${key}" copied to local scope`)
      fetchData()
    } catch {
      toast.error('Failed to copy setting to local scope')
    }
  }

  return (
    <div className="space-y-6 h-full flex flex-col">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Settings className="h-8 w-8" />
            Configuration
          </h1>
          <p className="text-muted-foreground">
            View and edit Claude Code configuration
          </p>
        </div>
        <RefreshButton onClick={fetchData} loading={loading} />
      </div>

      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)} className="flex-1 flex flex-col overflow-hidden">
        <TabsList className="w-fit">
          <TabsTrigger value="editor" className="flex items-center gap-2">
            <Edit className="h-4 w-4" />
            Settings Editor
          </TabsTrigger>
          <TabsTrigger value="scopes" className="flex items-center gap-2">
            <Shield className="h-4 w-4" />
            Scope Resolver
          </TabsTrigger>
          <TabsTrigger value="viewer" className="flex items-center gap-2">
            <Eye className="h-4 w-4" />
            Raw Viewer
          </TabsTrigger>
        </TabsList>

        <TabsContent value="editor" className="flex-1 overflow-auto mt-4">
          <SettingsEditor onSave={fetchData} />
        </TabsContent>

        <TabsContent value="scopes" className="flex-1 overflow-auto mt-4">
          <ScopeResolver onOverride={activeProject ? handleOverrideInLocal : undefined} />
        </TabsContent>

        <TabsContent value="viewer" className="flex-1 overflow-hidden mt-4">
          {error && (
            <Card className="border-destructive mb-4">
              <CardHeader>
                <CardTitle className="text-destructive">Error</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm">{error}</p>
              </CardContent>
            </Card>
          )}

          <div className="grid grid-cols-12 gap-6 h-full overflow-hidden">
            <div className="col-span-4 overflow-y-auto">
              <Card className="h-full">
                <CardHeader>
                  <CardTitle>Config Files</CardTitle>
                </CardHeader>
                <CardContent>
                  {loading && !data && (
                    <p className="text-sm text-muted-foreground">Loading files...</p>
                  )}
                  {data && (
                    <ConfigFileList
                      files={data.files}
                      selectedFile={selectedFile}
                      onSelectFile={setSelectedFile}
                    />
                  )}
                </CardContent>
              </Card>
            </div>

            <div className="col-span-8 overflow-y-auto">
              <ConfigFileViewer filePath={selectedFile} />
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
