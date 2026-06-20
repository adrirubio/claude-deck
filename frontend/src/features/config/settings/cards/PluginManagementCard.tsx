import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { BooleanMapEditor, JsonSetting, TextSetting } from '../field-components'
import type { SettingsCardProps } from '../types'

const EXTRA_MARKETPLACES_EXAMPLE = `{
  "team-tools": {
    "source": {
      "source": "github",
      "repo": "acme-corp/claude-plugins"
    },
    "autoUpdate": true
  }
}`

const BLOCKED_MARKETPLACES_EXAMPLE = `[
  { "source": "github", "repo": "untrusted/plugins" }
]`

const STRICT_MARKETPLACES_EXAMPLE = `[
  { "source": "github", "repo": "acme-corp/approved-plugins" }
]`

export function PluginManagementCard({ getSetting, getSettingRaw, updateSetting, scope }: SettingsCardProps) {
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
            Map plugin IDs to enabled or disabled state. Format: plugin-name@marketplace.
          </p>
          <BooleanMapEditor
            value={getSetting<Record<string, boolean>>('enabledPlugins', {})}
            onChange={(v) => updateSetting('enabledPlugins', v)}
            placeholder="e.g., formatter@team-tools"
          />
        </div>

        <JsonSetting
          id="extraKnownMarketplaces"
          label="Extra Marketplaces"
          description="Named marketplace sources made available to the current scope."
          value={getSettingRaw('extraKnownMarketplaces')}
          onChange={(v) => updateSetting('extraKnownMarketplaces', v)}
          expected="object"
          placeholder={EXTRA_MARKETPLACES_EXAMPLE}
        />

        {scope === 'managed' && (
          <>
            <JsonSetting
              id="blockedMarketplaces"
              label="Blocked Marketplaces"
              description="Managed blocklist of marketplace sources."
              value={getSettingRaw('blockedMarketplaces')}
              onChange={(v) => updateSetting('blockedMarketplaces', v)}
              expected="array"
              placeholder={BLOCKED_MARKETPLACES_EXAMPLE}
            />

            <TextSetting
              id="pluginTrustMessage"
              label="Plugin Trust Message"
              description="Custom warning message shown when loading plugins."
              value={getSetting<string>('pluginTrustMessage', '')}
              onChange={(v) => updateSetting('pluginTrustMessage', v)}
              placeholder="Only install plugins from trusted sources."
            />

            <JsonSetting
              id="strictKnownMarketplaces"
              label="Strict Known Marketplaces"
              description="Managed allowlist of marketplace sources users may add or install from."
              value={getSettingRaw('strictKnownMarketplaces')}
              onChange={(v) => updateSetting('strictKnownMarketplaces', v)}
              expected="array"
              placeholder={STRICT_MARKETPLACES_EXAMPLE}
            />
          </>
        )}
      </CardContent>
    </Card>
  )
}
