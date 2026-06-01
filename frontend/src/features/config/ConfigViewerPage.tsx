import { useState, useEffect, useCallback } from 'react'
import { Settings, Eye, Edit, Shield } from 'lucide-react'
import type { ConfigFileListResponse, ConfigValue } from '@/types/config'
import { RefreshButton } from '@/components/shared/RefreshButton'
import { ConfigFileList } from './ConfigFileList'
import { ConfigFileViewer } from './ConfigFileViewer'
import { CodexDiagnosticsCard } from './CodexDiagnosticsCard'
import { CodexInventoryCard } from './CodexInventoryCard'
import { CodexProfileResolverCard } from './CodexProfileResolverCard'
import { CodexSettingsEditor } from './CodexSettingsEditor'
import { SettingsEditor } from './settings'
import { ScopeResolver } from './ScopeResolver'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { apiClient, buildEndpoint } from '@/lib/api'
import { useProjectContext } from '@/contexts/ProjectContext'
import { useProviderContext } from '@/contexts/ProviderContext'
import {
  fetchCodexFeatureInventory,
  fetchCodexMcpInventory,
  fetchCodexPluginInventory,
  fetchProviderDoctor,
} from '@/hooks/useProviders'
import type {
  CodexConfigResponse,
  CodexFeatureInventoryResponse,
  CodexMcpInventoryResponse,
  CodexPluginInventoryResponse,
  ProviderDoctorResponse,
} from '@/types/providers'
import { toast } from 'sonner'

export function ConfigViewerPage() {
  const { activeProject } = useProjectContext()
  const { selectedProviderId, selectedProvider } = useProviderContext()
  const [data, setData] = useState<ConfigFileListResponse | null>(null)
  const [codexConfig, setCodexConfig] = useState<CodexConfigResponse | null>(null)
  const [codexDoctor, setCodexDoctor] = useState<ProviderDoctorResponse | null>(null)
  const [codexDoctorError, setCodexDoctorError] = useState<string | null>(null)
  const [codexFeatureInventory, setCodexFeatureInventory] = useState<CodexFeatureInventoryResponse | null>(null)
  const [codexFeatureError, setCodexFeatureError] = useState<string | null>(null)
  const [codexMcpInventory, setCodexMcpInventory] = useState<CodexMcpInventoryResponse | null>(null)
  const [codexPluginInventory, setCodexPluginInventory] = useState<CodexPluginInventoryResponse | null>(null)
  const [codexMcpError, setCodexMcpError] = useState<string | null>(null)
  const [codexPluginError, setCodexPluginError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'editor' | 'scopes' | 'viewer'>('editor')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      if (selectedProviderId === 'codex-cli') {
        const filesPromise = apiClient<ConfigFileListResponse>('codex-config/files')
        const configPromise = apiClient<CodexConfigResponse>('codex-config')
        const doctorPromise = fetchProviderDoctor('codex-cli')
          .then((doctor) => ({ doctor, error: null }))
          .catch((err) => ({
            doctor: null,
            error: err instanceof Error ? err.message : 'Failed to load Codex diagnostics',
          }))
        const featuresPromise = fetchCodexFeatureInventory()
          .then((inventory) => ({ inventory, error: null }))
          .catch((err) => ({
            inventory: null,
            error: err instanceof Error ? err.message : 'Failed to load Codex feature inventory',
          }))
        const mcpPromise = fetchCodexMcpInventory()
          .then((inventory) => ({ inventory, error: null }))
          .catch((err) => ({
            inventory: null,
            error: err instanceof Error ? err.message : 'Failed to load Codex MCP inventory',
          }))
        const pluginsPromise = fetchCodexPluginInventory()
          .then((inventory) => ({ inventory, error: null }))
          .catch((err) => ({
            inventory: null,
            error: err instanceof Error ? err.message : 'Failed to load Codex plugin inventory',
          }))

        const [files, config, doctorResult, featuresResult, mcpResult, pluginResult] = await Promise.all([
          filesPromise,
          configPromise,
          doctorPromise,
          featuresPromise,
          mcpPromise,
          pluginsPromise,
        ])
        setData(files)
        setCodexConfig(config)
        setCodexDoctor(doctorResult.doctor)
        setCodexDoctorError(doctorResult.error)
        setCodexFeatureInventory(featuresResult.inventory)
        setCodexFeatureError(featuresResult.error)
        setCodexMcpInventory(mcpResult.inventory)
        setCodexMcpError(mcpResult.error)
        setCodexPluginInventory(pluginResult.inventory)
        setCodexPluginError(pluginResult.error)
        if (activeTab === 'scopes') setActiveTab('editor')
      } else {
        const endpoint = buildEndpoint('config/files', { project_path: activeProject?.path })
        const response = await apiClient<ConfigFileListResponse>(endpoint)
        setData(response)
        setCodexConfig(null)
        setCodexDoctor(null)
        setCodexDoctorError(null)
        setCodexFeatureInventory(null)
        setCodexFeatureError(null)
        setCodexMcpInventory(null)
        setCodexPluginInventory(null)
        setCodexMcpError(null)
        setCodexPluginError(null)
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load config files'
      setError(message)
      toast.error(message)
    } finally {
      setLoading(false)
    }
  }, [activeProject?.path, selectedProviderId, activeTab])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  useEffect(() => {
    setSelectedFile(null)
  }, [selectedProviderId])

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
            View {selectedProvider?.display_name ?? 'agent'} configuration
          </p>
        </div>
        <RefreshButton onClick={fetchData} loading={loading} />
      </div>

      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)} className="flex-1 flex flex-col overflow-hidden">
        <TabsList className="w-fit">
          <TabsTrigger value="editor" className="flex items-center gap-2">
            <Edit className="h-4 w-4" />
            {selectedProviderId === 'codex-cli' ? 'Overview' : 'Settings Editor'}
          </TabsTrigger>
          {selectedProviderId === 'claude-code' && (
            <TabsTrigger value="scopes" className="flex items-center gap-2">
              <Shield className="h-4 w-4" />
              Scope Resolver
            </TabsTrigger>
          )}
          <TabsTrigger value="viewer" className="flex items-center gap-2">
            <Eye className="h-4 w-4" />
            Raw Viewer
          </TabsTrigger>
        </TabsList>

        <TabsContent value="editor" className="flex-1 overflow-auto mt-4">
          {selectedProviderId === 'codex-cli' ? (
            <div className="space-y-4">
              {!codexConfig?.exists && (
                <Card>
                  <CardContent className="pt-6">
                    <p className="text-sm text-muted-foreground">No ~/.codex/config.toml file found. Saving will create it.</p>
                  </CardContent>
                </Card>
              )}
              <CodexSettingsEditor
                key={JSON.stringify(codexConfig?.summary ?? {})}
                config={codexConfig}
                featureInventory={codexFeatureInventory}
                featureInventoryError={codexFeatureError}
                onSaved={fetchData}
              />
              <CodexProfileResolverCard resolution={codexConfig?.profile_resolution} />
              <CodexDiagnosticsCard
                doctor={codexDoctor}
                loading={loading}
                error={codexDoctorError}
                onRefresh={fetchData}
              />
              <CodexInventoryCard
                mcp={codexMcpInventory}
                plugins={codexPluginInventory}
                mcpError={codexMcpError}
                pluginError={codexPluginError}
                loading={loading}
                onRefresh={fetchData}
              />
            </div>
          ) : (
            <SettingsEditor onSave={fetchData} />
          )}
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
              <ConfigFileViewer
                filePath={selectedFile}
                rawEndpoint={selectedProviderId === 'codex-cli' ? 'codex-config/file' : 'config/raw'}
              />
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
