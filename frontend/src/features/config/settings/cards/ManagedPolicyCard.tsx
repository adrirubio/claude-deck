import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { JsonSetting, SwitchSetting, TextSetting } from '../field-components'
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
        <TextSetting
          id="claudeMd"
          label="Managed CLAUDE.md"
          description="CLAUDE.md-style instructions injected as organization-managed memory. Only honored in managed/policy settings."
          value={getSetting<string>('claudeMd', '')}
          onChange={() => {}}
        />

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

        <JsonSetting
          id="allowedChannelPlugins"
          label="Allowed Channel Plugins"
          description="Plugins that may push channel messages."
          value={getSetting('allowedChannelPlugins', [])}
          onChange={() => {}}
          expected="array"
        />

        <JsonSetting
          id="allowedMcpServers"
          label="Allowed MCP Servers"
          description="Managed allowlist of MCP servers users can configure."
          value={getSetting('allowedMcpServers', [])}
          onChange={() => {}}
          expected="array"
        />

        <JsonSetting
          id="deniedMcpServers"
          label="Denied MCP Servers"
          description="Managed denylist of MCP servers."
          value={getSetting('deniedMcpServers', [])}
          onChange={() => {}}
          expected="array"
        />

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
