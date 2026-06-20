import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SelectSetting, SwitchSetting } from '../field-components'
import { NOTIFICATION_CHANNEL_OPTIONS } from '../constants'
import type { SettingsCardProps } from '../types'

export function RemoteControlCard({ getSetting, updateSetting }: SettingsCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Remote Control & Notifications</CardTitle>
        <CardDescription>Claude Code remote session access and terminal notification behavior</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <SwitchSetting
          label="Connect Remote Control at Startup"
          description="Automatically connect Remote Control for each interactive Claude Code session."
          checked={getSetting<boolean>('remoteControlAtStartup', false)}
          onCheckedChange={(v) => updateSetting('remoteControlAtStartup', v)}
        />

        <SwitchSetting
          label="Disable Remote Control"
          description="Block remote-control startup, flags, and in-session toggles."
          checked={getSetting<boolean>('disableRemoteControl', false)}
          onCheckedChange={(v) => updateSetting('disableRemoteControl', v)}
        />

        <SwitchSetting
          label="Push When Input Is Needed"
          description="Send a mobile push notification when a permission prompt or question needs attention."
          checked={getSetting<boolean>('inputNeededNotifEnabled', false)}
          onCheckedChange={(v) => updateSetting('inputNeededNotifEnabled', v)}
        />

        <SwitchSetting
          label="Push When Claude Decides"
          description="Allow Claude to send proactive push notifications, such as when a long task finishes."
          checked={getSetting<boolean>('agentPushNotifEnabled', false)}
          onCheckedChange={(v) => updateSetting('agentPushNotifEnabled', v)}
        />

        <SelectSetting
          id="preferredNotifChannel"
          label="Terminal Notification Channel"
          description="How Claude Code notifies you for task completion and permission prompts."
          value={getSetting<string>('preferredNotifChannel', '')}
          onValueChange={(v) => updateSetting('preferredNotifChannel', v)}
          placeholder="Auto"
          options={NOTIFICATION_CHANNEL_OPTIONS}
        />
      </CardContent>
    </Card>
  )
}
