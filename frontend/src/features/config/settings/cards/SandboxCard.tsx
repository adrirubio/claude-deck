import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { SwitchSetting, NumberSetting, ListEditor } from '../field-components'
import type { SettingsCardProps } from '../types'

export function SandboxCard({ getSetting, updateSetting, scope }: SettingsCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Sandbox</CardTitle>
        <CardDescription>Sandbox and security settings</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <SwitchSetting
          label="Enable Sandbox"
          description="Run commands in an isolated environment"
          checked={getSetting<boolean>('sandbox.enabled', false)}
          onCheckedChange={(v) => updateSetting('sandbox.enabled', v)}
        />

        <SwitchSetting
          label="Auto-Allow Bash if Sandboxed"
          description="Automatically allow bash commands when sandbox is enabled"
          checked={getSetting<boolean>('sandbox.autoAllowBashIfSandboxed', false)}
          onCheckedChange={(v) => updateSetting('sandbox.autoAllowBashIfSandboxed', v)}
        />

        <SwitchSetting
          label="Allow Unsandboxed Commands"
          description="Allow the dangerouslyDisableSandbox escape hatch"
          checked={getSetting<boolean>('sandbox.allowUnsandboxedCommands', true)}
          onCheckedChange={(v) => updateSetting('sandbox.allowUnsandboxedCommands', v)}
        />

        <SwitchSetting
          label="Weaker Nested Sandbox"
          description="Use weaker sandbox for unprivileged Docker containers"
          checked={getSetting<boolean>('sandbox.enableWeakerNestedSandbox', false)}
          onCheckedChange={(v) => updateSetting('sandbox.enableWeakerNestedSandbox', v)}
        />

        <div className="grid gap-2">
          <Label>Excluded Commands</Label>
          <p className="text-sm text-muted-foreground">
            Commands that bypass sandbox isolation
          </p>
          <ListEditor
            value={getSetting<string[]>('sandbox.excludedCommands', [])}
            onChange={(v) => updateSetting('sandbox.excludedCommands', v)}
            placeholder="Add command..."
          />
        </div>

        <div className="grid gap-2">
          <Label>Allowed Domains</Label>
          <p className="text-sm text-muted-foreground">
            Network domains accessible from sandbox
          </p>
          <ListEditor
            value={getSetting<string[]>('sandbox.network.allowedDomains', [])}
            onChange={(v) => updateSetting('sandbox.network.allowedDomains', v)}
            placeholder="Add domain..."
          />
        </div>

        <div className="grid gap-2">
          <Label>Allowed Unix Sockets</Label>
          <p className="text-sm text-muted-foreground">
            Unix socket paths accessible in sandbox
          </p>
          <ListEditor
            value={getSetting<string[]>('sandbox.network.allowUnixSockets', [])}
            onChange={(v) => updateSetting('sandbox.network.allowUnixSockets', v)}
            placeholder="e.g., ~/.ssh/agent-socket"
          />
        </div>

        <SwitchSetting
          label="Allow All Unix Sockets"
          description="Allow all Unix socket connections in sandbox"
          checked={getSetting<boolean>('sandbox.network.allowAllUnixSockets', false)}
          onCheckedChange={(v) => updateSetting('sandbox.network.allowAllUnixSockets', v)}
        />

        <SwitchSetting
          label="Allow Local Binding"
          description="Allow localhost binding in sandbox (macOS only)"
          checked={getSetting<boolean>('sandbox.network.allowLocalBinding', false)}
          onCheckedChange={(v) => updateSetting('sandbox.network.allowLocalBinding', v)}
        />

        <div className="grid grid-cols-2 gap-4">
          <NumberSetting
            id="httpProxyPort"
            label="HTTP Proxy Port"
            value={getSetting<string | number>('sandbox.network.httpProxyPort', '')}
            onChange={(v) => updateSetting('sandbox.network.httpProxyPort', v)}
            placeholder="8080"
          />
          <NumberSetting
            id="socksProxyPort"
            label="SOCKS5 Proxy Port"
            value={getSetting<string | number>('sandbox.network.socksProxyPort', '')}
            onChange={(v) => updateSetting('sandbox.network.socksProxyPort', v)}
            placeholder="8081"
          />
        </div>

        {/* Filesystem Rules */}
        <div className="grid gap-2">
          <Label>Allowed Read Paths</Label>
          <p className="text-sm text-muted-foreground">
            Gitignore-style patterns for allowed filesystem read paths
          </p>
          <ListEditor
            value={getSetting<string[]>('sandbox.filesystem.allowRead', [])}
            onChange={(v) => updateSetting('sandbox.filesystem.allowRead', v)}
            placeholder="e.g., /tmp/**, *.log"
          />
        </div>

        <div className="grid gap-2">
          <Label>Denied Read Paths</Label>
          <p className="text-sm text-muted-foreground">
            Gitignore-style patterns for blocked filesystem read paths
          </p>
          <ListEditor
            value={getSetting<string[]>('sandbox.filesystem.denyRead', [])}
            onChange={(v) => updateSetting('sandbox.filesystem.denyRead', v)}
            placeholder="e.g., /etc/shadow, ~/.ssh/**"
          />
        </div>

        {scope === 'managed' && (
          <>
            <SwitchSetting
              label="Allow Managed Read Paths Only"
              description="Only allow filesystem read paths defined in managed settings"
              checked={getSetting<boolean>('sandbox.filesystem.allowManagedReadPathsOnly', false)}
              onCheckedChange={(v) => updateSetting('sandbox.filesystem.allowManagedReadPathsOnly', v)}
            />
            <SwitchSetting
              label="Allow Managed Domains Only"
              description="Only allow network domains defined in managed settings"
              checked={getSetting<boolean>('sandbox.network.allowManagedDomainsOnly', false)}
              onCheckedChange={(v) => updateSetting('sandbox.network.allowManagedDomainsOnly', v)}
            />
          </>
        )}
      </CardContent>
    </Card>
  )
}
