import { useState } from 'react'
import { Plus, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { ConfigValue } from '@/types/config'

export function SwitchSetting({ label, description, checked, onCheckedChange }: {
  label: string
  description: string
  checked: boolean
  onCheckedChange: (value: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between">
      <div className="space-y-0.5">
        <Label>{label}</Label>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <Switch checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  )
}

export function NumberSetting({ id, label, description, value, onChange, placeholder }: {
  id: string
  label: string
  description?: string
  value: string | number
  onChange: (value: number | null) => void
  placeholder?: string
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value ? parseInt(e.target.value) : null)}
        placeholder={placeholder}
      />
      {description && (
        <p className="text-xs text-muted-foreground">{description}</p>
      )}
    </div>
  )
}

export function SelectSetting({ id, label, description, value, onValueChange, placeholder, options }: {
  id: string
  label: string
  description?: string
  value: string
  onValueChange: (value: string) => void
  placeholder?: string
  options: { value: string; label: string }[]
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger id={id}>
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {options.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {description && (
        <p className="text-xs text-muted-foreground">{description}</p>
      )}
    </div>
  )
}

export function TextSetting({ id, label, description, value, onChange, placeholder }: {
  id: string
  label: string
  description?: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
      {description && (
        <p className="text-xs text-muted-foreground">{description}</p>
      )}
    </div>
  )
}

type AttributionMode = 'default' | 'custom' | 'none'

export function AttributionField({ id, label, description, defaultText, rawValue, onChange }: {
  id: string
  label: string
  description: string
  defaultText: string
  rawValue: ConfigValue | undefined
  onChange: (value: ConfigValue) => void
}) {
  const mode: AttributionMode = rawValue === undefined ? 'default' : (rawValue === '' ? 'none' : 'custom')
  const customText = typeof rawValue === 'string' ? rawValue : ''

  const handleModeChange = (newMode: string) => {
    if (newMode === 'default') onChange(null)
    else if (newMode === 'none') onChange('')
    else onChange(defaultText)
  }

  return (
    <div className="grid gap-2">
      <Label>{label}</Label>
      <div className="flex items-center gap-2">
        <Tabs value={mode} onValueChange={handleModeChange} className="w-full">
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="default">Default</TabsTrigger>
            <TabsTrigger value="custom">Custom</TabsTrigger>
            <TabsTrigger value="none">None</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
      {mode === 'default' && (
        <p className="text-xs text-muted-foreground font-mono">{defaultText}</p>
      )}
      {mode === 'custom' && (
        <Textarea
          id={id}
          className="font-mono text-sm"
          rows={2}
          value={customText}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {mode === 'none' && (
        <p className="text-xs text-muted-foreground italic">Attribution disabled — nothing will be appended</p>
      )}
      <p className="text-xs text-muted-foreground">{description}</p>
    </div>
  )
}

export function ListEditor({ value: rawValue, onChange, placeholder }: {
  value: string[]
  onChange: (value: string[]) => void
  placeholder?: string
}) {
  const value = Array.isArray(rawValue) ? rawValue : []
  const [newItem, setNewItem] = useState('')

  function addItem() {
    if (newItem.trim() && !value.includes(newItem.trim())) {
      onChange([...value, newItem.trim()])
      setNewItem('')
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Input
          value={newItem}
          onChange={(e) => setNewItem(e.target.value)}
          placeholder={placeholder}
          onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addItem())}
        />
        <Button type="button" size="icon" variant="outline" onClick={addItem}>
          <Plus className="h-4 w-4" />
        </Button>
      </div>
      <div className="flex flex-wrap gap-2">
        {value.map((item, index) => (
          <div
            key={index}
            className="flex items-center gap-1 bg-muted px-2 py-1 rounded text-sm"
          >
            <span>{item}</span>
            <button
              type="button"
              onClick={() => onChange(value.filter((_, i) => i !== index))}
              className="text-muted-foreground hover:text-foreground"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

export function ObjectArrayEditor({ value: rawValue, onChange, field1Label, field2Label, field1Placeholder, field2Placeholder }: {
  value: { name: string; url: string }[]
  onChange: (value: { name: string; url: string }[]) => void
  field1Label?: string
  field2Label?: string
  field1Placeholder?: string
  field2Placeholder?: string
}) {
  const value = Array.isArray(rawValue) ? rawValue : []
  const [newField1, setNewField1] = useState('')
  const [newField2, setNewField2] = useState('')

  function addItem() {
    if (newField1.trim() && newField2.trim()) {
      onChange([...value, { name: newField1.trim(), url: newField2.trim() }])
      setNewField1('')
      setNewField2('')
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Input
          value={newField1}
          onChange={(e) => setNewField1(e.target.value)}
          placeholder={field1Placeholder ?? field1Label ?? 'Name'}
          className="flex-1"
        />
        <Input
          value={newField2}
          onChange={(e) => setNewField2(e.target.value)}
          placeholder={field2Placeholder ?? field2Label ?? 'URL'}
          className="flex-1"
        />
        <Button type="button" size="icon" variant="outline" onClick={addItem}>
          <Plus className="h-4 w-4" />
        </Button>
      </div>
      <div className="space-y-1">
        {value.map((item, index) => (
          <div key={index} className="flex items-center gap-2 bg-muted px-2 py-1 rounded text-sm">
            <span className="font-medium">{item.name}</span>
            <span className="text-muted-foreground truncate flex-1">{item.url}</span>
            <button
              type="button"
              onClick={() => onChange(value.filter((_, i) => i !== index))}
              className="text-muted-foreground hover:text-foreground"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

function formatJson(value: ConfigValue | undefined, fallback: ConfigValue) {
  return JSON.stringify(value ?? fallback, null, 2)
}

export function JsonSetting({ id, label, description, value, onChange, placeholder, rows = 8, expected = 'any' }: {
  id: string
  label: string
  description?: string
  value: ConfigValue | undefined
  onChange: (value: ConfigValue) => void
  placeholder?: string
  rows?: number
  expected?: 'any' | 'object' | 'array'
}) {
  const fallback = expected === 'array' ? [] : expected === 'object' ? {} : null
  const serialized = formatJson(value, fallback)
  const [error, setError] = useState('')

  function validate(next: string, commit: boolean) {
    const trimmed = next.trim()
    if (!trimmed) {
      setError('')
      if (commit) onChange(null)
      return
    }

    try {
      const parsed = JSON.parse(trimmed) as ConfigValue
      if (expected === 'object' && (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))) {
        setError('Expected a JSON object.')
        return
      }
      if (expected === 'array' && !Array.isArray(parsed)) {
        setError('Expected a JSON array.')
        return
      }
      setError('')
      if (commit) onChange(parsed)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid JSON.')
    }
  }

  function handleChange(next: string) {
    validate(next, false)
  }

  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      {description && (
        <p className="text-xs text-muted-foreground">{description}</p>
      )}
      <Textarea
        key={serialized}
        id={id}
        className="font-mono text-xs"
        rows={rows}
        defaultValue={serialized}
        onChange={(e) => handleChange(e.target.value)}
        onBlur={(e) => validate(e.currentTarget.value, true)}
        placeholder={placeholder}
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}

export function BooleanMapEditor({ value: rawValue, onChange, placeholder }: {
  value: Record<string, boolean>
  onChange: (value: Record<string, boolean>) => void
  placeholder?: string
}) {
  const value = rawValue && typeof rawValue === 'object' && !Array.isArray(rawValue) ? rawValue : {}
  const [newKey, setNewKey] = useState('')

  function addItem() {
    const key = newKey.trim()
    if (!key) return
    onChange({ ...value, [key]: true })
    setNewKey('')
  }

  function removeItem(key: string) {
    const updated = { ...value }
    delete updated[key]
    onChange(updated)
  }

  function toggleItem(key: string, enabled: boolean) {
    onChange({ ...value, [key]: enabled })
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Input
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          placeholder={placeholder ?? 'plugin@marketplace'}
          onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addItem())}
        />
        <Button type="button" size="icon" variant="outline" onClick={addItem}>
          <Plus className="h-4 w-4" />
        </Button>
      </div>
      <div className="space-y-1">
        {Object.entries(value).map(([key, enabled]) => (
          <div key={key} className="flex items-center gap-2 bg-muted px-2 py-1 rounded text-sm">
            <span className="font-mono flex-1 truncate">{key}</span>
            <Switch checked={enabled} onCheckedChange={(checked) => toggleItem(key, checked)} />
            <button
              type="button"
              onClick={() => removeItem(key)}
              className="text-muted-foreground hover:text-foreground"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

export function KeyValueEditor({ value, onChange }: {
  value: Record<string, string>
  onChange: (value: Record<string, string>) => void
}) {
  const [newKey, setNewKey] = useState('')
  const [newValue, setNewValue] = useState('')

  function addItem() {
    if (newKey.trim()) {
      onChange({ ...value, [newKey.trim()]: newValue })
      setNewKey('')
      setNewValue('')
    }
  }

  function removeItem(key: string) {
    const updated = { ...value }
    delete updated[key]
    onChange(updated)
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Input
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          placeholder="Key"
          className="flex-1"
        />
        <Input
          value={newValue}
          onChange={(e) => setNewValue(e.target.value)}
          placeholder="Value"
          className="flex-1"
        />
        <Button type="button" size="icon" variant="outline" onClick={addItem}>
          <Plus className="h-4 w-4" />
        </Button>
      </div>
      <div className="space-y-1">
        {Object.entries(value).map(([k, v]) => (
          <div key={k} className="flex items-center gap-2 bg-muted px-2 py-1 rounded text-sm">
            <span className="font-mono">{k}</span>
            <span className="text-muted-foreground">=</span>
            <span className="font-mono flex-1 truncate">{v}</span>
            <button
              type="button"
              onClick={() => removeItem(k)}
              className="text-muted-foreground hover:text-foreground"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
