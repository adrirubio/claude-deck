import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { SwitchSetting, TextSetting, ListEditor, ObjectArrayEditor } from '../field-components'
import type { SettingsCardProps } from '../types'

export function PluginManagementCard({ getSetting, updateSetting, scope }: SettingsCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Plugins</CardTitle>
        <CardDescription>Manage plugins and marketplace sources</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2">
          <Label>Enabled Plugins</Label>
          <p className="text-sm text-muted-foreground">
            Plugins to load. Use &quot;plugin-name@marketplace&quot; or a local path.
          </p>
          <ListEditor
            value={getSetting<string[]>('enabledPlugins', [])}
            onChange={(v) => updateSetting('enabledPlugins', v)}
            placeholder="e.g., plugin-name@marketplace or /path/to/plugin"
          />
        </div>

        <div className="grid gap-2">
          <Label>Extra Marketplaces</Label>
          <p className="text-sm text-muted-foreground">
            Additional plugin marketplaces beyond the defaults.
          </p>
          <ObjectArrayEditor
            value={getSetting<{ name: string; url: string }[]>('extraKnownMarketplaces', [])}
            onChange={(v) => updateSetting('extraKnownMarketplaces', v)}
            field1Placeholder="Marketplace name"
            field2Placeholder="https://marketplace.example.com"
          />
        </div>

        {scope === 'managed' && (
          <>
            <div className="grid gap-2">
              <Label>Blocked Marketplaces</Label>
              <p className="text-sm text-muted-foreground">
                Marketplace identifiers to block.
              </p>
              <ListEditor
                value={getSetting<string[]>('blockedMarketplaces', [])}
                onChange={(v) => updateSetting('blockedMarketplaces', v)}
                placeholder="e.g., untrusted-marketplace"
              />
            </div>

            <TextSetting
              id="pluginTrustMessage"
              label="Plugin Trust Message"
              description="Custom warning message shown when loading plugins."
              value={getSetting<string>('pluginTrustMessage', '')}
              onChange={(v) => updateSetting('pluginTrustMessage', v)}
              placeholder="Only install plugins from trusted sources."
            />

            <SwitchSetting
              label="Strict Known Marketplaces"
              description="Restrict available marketplaces to only known/managed ones"
              checked={getSetting<boolean>('strictKnownMarketplaces', false)}
              onCheckedChange={(v) => updateSetting('strictKnownMarketplaces', v)}
            />
          </>
        )}
      </CardContent>
    </Card>
  )
}
