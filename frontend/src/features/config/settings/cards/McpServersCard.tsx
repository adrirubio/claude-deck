import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { SwitchSetting, ListEditor } from '../field-components'
import type { SettingsCardProps } from '../types'

export function McpServersCard({ getSetting, updateSetting }: SettingsCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>MCP Servers (.mcp.json)</CardTitle>
        <CardDescription>Control auto-approval of MCP servers defined in project .mcp.json files</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <SwitchSetting
          label="Enable All Project MCP Servers"
          description="Automatically approve all MCP servers defined in project .mcp.json files"
          checked={getSetting<boolean>('enableAllProjectMcpServers', false)}
          onCheckedChange={(v) => updateSetting('enableAllProjectMcpServers', v)}
        />

        <div className="grid gap-2">
          <Label>Enabled MCP Servers</Label>
          <p className="text-sm text-muted-foreground">
            Specific servers to approve from .mcp.json
          </p>
          <ListEditor
            value={getSetting<string[]>('enabledMcpjsonServers', [])}
            onChange={(v) => updateSetting('enabledMcpjsonServers', v)}
            placeholder="e.g., my-mcp-server"
          />
        </div>

        <div className="grid gap-2">
          <Label>Disabled MCP Servers</Label>
          <p className="text-sm text-muted-foreground">
            Specific servers to reject from .mcp.json
          </p>
          <ListEditor
            value={getSetting<string[]>('disabledMcpjsonServers', [])}
            onChange={(v) => updateSetting('disabledMcpjsonServers', v)}
            placeholder="e.g., untrusted-server"
          />
        </div>
      </CardContent>
    </Card>
  )
}
