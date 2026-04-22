import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { ListEditor, SwitchSetting } from '../field-components'
import type { SettingsCardProps } from '../types'

/**
 * Managed-only policy controls. Only rendered when viewing the managed scope —
 * the editor wraps the whole grid in a disabled fieldset, so fields surface as
 * read-only. Claude Deck is not a policy authoring tool; this card exists so
 * users can see what policy their org has pushed.
 */
export function ManagedPolicyCard({ getSetting, scope }: SettingsCardProps) {
  if (scope !== 'managed') return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Managed Policy</CardTitle>
        <CardDescription>
          Controls set by your organization's managed settings. Displayed here for visibility.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <SwitchSetting
          label="Allow Managed Hooks Only"
          description="Reject user/project hooks — only hooks defined in managed settings run."
          checked={getSetting<boolean>('allowManagedHooksOnly', false)}
          onCheckedChange={() => {}}
        />

        <SwitchSetting
          label="Allow Managed MCP Servers Only"
          description="Reject MCP servers that aren't declared in managed settings."
          checked={getSetting<boolean>('allowManagedMcpServersOnly', false)}
          onCheckedChange={() => {}}
        />

        <SwitchSetting
          label="Allow Managed Permission Rules Only"
          description="Reject user/project permission rules outside of the managed allow/deny/ask lists."
          checked={getSetting<boolean>('allowManagedPermissionRulesOnly', false)}
          onCheckedChange={() => {}}
        />

        <SwitchSetting
          label="Disable Skill Shell Execution"
          description="Block skills from running shell commands."
          checked={getSetting<boolean>('disableSkillShellExecution', false)}
          onCheckedChange={() => {}}
        />

        <SwitchSetting
          label="Force Remote Settings Refresh"
          description="Force the client to refresh managed settings from the remote source on every launch."
          checked={getSetting<boolean>('forceRemoteSettingsRefresh', false)}
          onCheckedChange={() => {}}
        />

        <SwitchSetting
          label="Channels Enabled"
          description="Enable the channels feature for this deployment."
          checked={getSetting<boolean>('channelsEnabled', false)}
          onCheckedChange={() => {}}
        />

        <div className="grid gap-2">
          <Label>Allowed Channel Plugins</Label>
          <p className="text-sm text-muted-foreground">
            Plugins that may be installed from channels.
          </p>
          <ListEditor
            value={getSetting<string[]>('allowedChannelPlugins', [])}
            onChange={() => {}}
          />
        </div>

        <div className="grid gap-2">
          <Label>Allowed MCP Servers (managed)</Label>
          <ListEditor
            value={getSetting<string[]>('allowedMcpServers', [])}
            onChange={() => {}}
          />
        </div>

        <div className="grid gap-2">
          <Label>Denied MCP Servers (managed)</Label>
          <ListEditor
            value={getSetting<string[]>('deniedMcpServers', [])}
            onChange={() => {}}
          />
        </div>

        <SwitchSetting
          label="Allow Managed Read Paths Only"
          description="Sandbox: only allow filesystem read paths defined in managed settings."
          checked={getSetting<boolean>('sandbox.filesystem.allowManagedReadPathsOnly', false)}
          onCheckedChange={() => {}}
        />

        <SwitchSetting
          label="Allow Managed Domains Only"
          description="Sandbox: only allow network domains defined in managed settings."
          checked={getSetting<boolean>('sandbox.network.allowManagedDomainsOnly', false)}
          onCheckedChange={() => {}}
        />
      </CardContent>
    </Card>
  )
}
