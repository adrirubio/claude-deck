import type { ConfigValue, SettingsScope } from '@/types/config'

export interface SettingsCardProps {
  getSetting: <T extends ConfigValue = ConfigValue>(path: string, defaultValue: T) => T
  getSettingRaw: (path: string) => ConfigValue | undefined
  updateSetting: (path: string, value: ConfigValue) => void
  scope: SettingsScope
}
