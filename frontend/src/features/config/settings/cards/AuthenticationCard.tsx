import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SelectSetting, TextSetting } from '../field-components'
import { LOGIN_METHOD_OPTIONS } from '../constants'
import type { SettingsCardProps } from '../types'

export function AuthenticationCard({ getSetting, updateSetting, scope }: SettingsCardProps) {
  const isManaged = scope === 'managed'

  return (
    <Card>
      <CardHeader>
        <CardTitle>Authentication</CardTitle>
        <CardDescription>
          Login restrictions (managed) and AWS/OTel credential helpers (Bedrock)
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isManaged && (
          <>
            <SelectSetting
              id="forceLoginMethod"
              label="Force Login Method"
              description="Restrict which authentication method users must use."
              value={getSetting<string>('forceLoginMethod', '')}
              onValueChange={(v) => updateSetting('forceLoginMethod', v)}
              placeholder="Select login method"
              options={LOGIN_METHOD_OPTIONS}
            />
            <TextSetting
              id="forceLoginOrgUUID"
              label="Force Login Org UUID"
              description="Restrict login to a specific organization UUID."
              value={getSetting<string>('forceLoginOrgUUID', '')}
              onChange={(v) => updateSetting('forceLoginOrgUUID', v)}
              placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            />
          </>
        )}

        <TextSetting
          id="awsAuthRefresh"
          label="AWS Auth Refresh Script"
          description="Script (via /bin/sh) that refreshes AWS credentials before each request. Used for Bedrock."
          value={getSetting<string>('awsAuthRefresh', '')}
          onChange={(v) => updateSetting('awsAuthRefresh', v)}
          placeholder="/bin/refresh-aws-auth.sh"
        />

        <TextSetting
          id="awsCredentialExport"
          label="AWS Credential Export Script"
          description="Script that prints AWS credentials as JSON to stdout (for SSO/federation flows)."
          value={getSetting<string>('awsCredentialExport', '')}
          onChange={(v) => updateSetting('awsCredentialExport', v)}
          placeholder="/bin/aws-credentials.sh"
        />

        <TextSetting
          id="otelHeadersHelper"
          label="OTel Headers Helper"
          description="Script that prints headers for OpenTelemetry exporters as JSON."
          value={getSetting<string>('otelHeadersHelper', '')}
          onChange={(v) => updateSetting('otelHeadersHelper', v)}
          placeholder="/bin/otel-headers.sh"
        />
      </CardContent>
    </Card>
  )
}
