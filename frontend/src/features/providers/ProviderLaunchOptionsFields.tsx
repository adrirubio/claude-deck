import { ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { SlotLaunchOptions } from '@/types/agentTeams'
import type { AgentProviderId, ProviderLaunchOptionsResponse, ProviderLaunchOption } from '@/types/providers'

const DEFAULT_SELECT_VALUE = '__default__'
const CUSTOM_SELECT_VALUE = '__custom__'

interface ProviderLaunchOptionsFieldsProps {
  provider: AgentProviderId | string
  value: SlotLaunchOptions
  onChange: (value: SlotLaunchOptions) => void
  descriptor?: ProviderLaunchOptionsResponse | null
  disabled?: boolean
}

function labelForProvider(provider: string) {
  if (provider === 'codex-cli') return 'OpenAI'
  if (provider === 'claude-code') return 'Anthropic'
  if (provider === 'opencode-cli') return 'OpenCode default'
  return 'Default'
}

function stringValue(value: unknown) {
  return typeof value === 'string' ? value : ''
}

function boolValue(value: unknown) {
  return value === true
}

function formatOption(option: ProviderLaunchOption) {
  if (option.description) return `${option.label} - ${option.description}`
  return option.label
}

function optionValues(options: ProviderLaunchOption[]) {
  return new Set(options.map((option) => option.value))
}

export function ProviderLaunchOptionsFields({
  provider,
  value,
  onChange,
  descriptor,
  disabled = false,
}: ProviderLaunchOptionsFieldsProps) {
  const setOption = (key: keyof SlotLaunchOptions, next: unknown) => {
    const updated = { ...value }
    if (next === '' || next === null || next === undefined || next === false) {
      delete updated[key]
    } else {
      updated[key] = next
    }
    onChange(updated)
  }

  const platform = stringValue(value.platform) || 'anthropic'
  const isBedrock = platform === 'bedrock'
  const model = stringValue(value.model)
  const bedrockModel = stringValue(value.bedrock_model)
  const profile = stringValue(value.profile)
  const modelOptions = descriptor?.model_options ?? []
  const profileOptions = descriptor?.profile_options ?? []
  const knownModels = optionValues(modelOptions)
  const knownProfiles = new Set(profileOptions.map((option) => option.value))
  const modelSelectValue = model && !knownModels.has(model) ? CUSTOM_SELECT_VALUE : model || DEFAULT_SELECT_VALUE
  const profileSelectValue = profile && !knownProfiles.has(profile) ? CUSTOM_SELECT_VALUE : profile || DEFAULT_SELECT_VALUE
  const isCodex = provider === 'codex-cli'
  const isClaude = provider === 'claude-code'
  const isCopilot = provider === 'copilot-cli'
  const isOpenCode = provider === 'opencode-cli'
  const usesSimpleModelInput = isCopilot || isOpenCode || ((isCodex || isClaude) && isBedrock)
  const simpleModelKey: keyof SlotLaunchOptions = (isCodex || isClaude) && isBedrock ? 'bedrock_model' : 'model'
  const simpleModelValue = (isCodex || isClaude) && isBedrock ? bedrockModel : model

  const handleModelSelect = (selected: string) => {
    if (selected === DEFAULT_SELECT_VALUE) {
      setOption('model', '')
      return
    }
    if (selected === CUSTOM_SELECT_VALUE) {
      setOption('model', model)
      return
    }
    setOption('model', selected)
  }

  const handleProfileSelect = (selected: string) => {
    if (selected === DEFAULT_SELECT_VALUE) {
      setOption('profile', '')
      return
    }
    if (selected === CUSTOM_SELECT_VALUE) {
      setOption('profile', profile)
      return
    }
    setOption('profile', selected)
  }

  return (
    <div className="grid gap-4">
      {descriptor?.bedrock_supported && (
        <div className="grid gap-2">
          <Label>Platform</Label>
          <Select
            value={platform}
            onValueChange={(next) => setOption('platform', next === 'anthropic' ? '' : next)}
            disabled={disabled}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="anthropic">{labelForProvider(provider)} (default)</SelectItem>
              <SelectItem value="bedrock">Amazon Bedrock</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}

      {isBedrock && descriptor?.bedrock_supported && (
        <div className="grid gap-3 rounded-md border border-border p-3 md:grid-cols-2">
          <div className="grid gap-2">
            <Label htmlFor="provider-aws-region">AWS Region</Label>
            <Input
              id="provider-aws-region"
              value={stringValue(value.aws_region)}
              onChange={(event) => setOption('aws_region', event.target.value)}
              placeholder="e.g. us-east-1"
              disabled={disabled}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="provider-aws-profile">AWS Profile</Label>
            <Input
              id="provider-aws-profile"
              value={stringValue(value.aws_profile)}
              onChange={(event) => setOption('aws_profile', event.target.value)}
              placeholder="e.g. bedrock-prod"
              disabled={disabled}
            />
          </div>
        </div>
      )}

      {usesSimpleModelInput && (
        <div className="grid gap-2">
          <Label htmlFor="provider-model">{(isCodex || isClaude) && isBedrock ? 'Bedrock model ID' : 'Model'}</Label>
          <Input
            id="provider-model"
            value={simpleModelValue}
            onChange={(event) => setOption(simpleModelKey, event.target.value)}
            placeholder={isCodex && isBedrock ? 'openai.gpt-5.5' : isClaude && isBedrock ? 'arn:aws:bedrock:...' : 'Default'}
            disabled={disabled}
          />
        </div>
      )}

      {isCodex && !isBedrock && (
        <div className="grid gap-2">
          <Label>Model</Label>
          <Select value={modelSelectValue} onValueChange={handleModelSelect} disabled={disabled}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={DEFAULT_SELECT_VALUE}>
                {descriptor?.default_model ? `Default (${descriptor.default_model})` : 'Default'}
              </SelectItem>
              {modelOptions.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {formatOption(option)}
                </SelectItem>
              ))}
              <SelectItem value={CUSTOM_SELECT_VALUE}>Custom model</SelectItem>
            </SelectContent>
          </Select>
          {modelSelectValue === CUSTOM_SELECT_VALUE && (
            <Input
              value={model}
              onChange={(event) => setOption('model', event.target.value)}
              placeholder="model name"
              disabled={disabled}
            />
          )}
        </div>
      )}

      {isCodex && (
        <div className="grid gap-2">
          <Label>Profile</Label>
          <Select value={profileSelectValue} onValueChange={handleProfileSelect} disabled={disabled}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={DEFAULT_SELECT_VALUE}>
                {descriptor?.default_profile ? `Default (${descriptor.default_profile})` : 'Default'}
              </SelectItem>
              {profileOptions.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
              <SelectItem value={CUSTOM_SELECT_VALUE}>Custom profile</SelectItem>
            </SelectContent>
          </Select>
          {profileSelectValue === CUSTOM_SELECT_VALUE && (
            <Input
              value={profile}
              onChange={(event) => setOption('profile', event.target.value)}
              placeholder="profile name"
              disabled={disabled}
            />
          )}
        </div>
      )}

      {descriptor?.reasoning_effort_supported && (
        <div className="grid gap-2">
          <Label>Reasoning effort</Label>
          <Select
            value={stringValue(value.reasoning_effort) || DEFAULT_SELECT_VALUE}
            onValueChange={(next) => setOption('reasoning_effort', next === DEFAULT_SELECT_VALUE ? '' : next)}
            disabled={disabled}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={DEFAULT_SELECT_VALUE}>Default</SelectItem>
              {descriptor.reasoning_effort_options.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {isOpenCode && !descriptor?.reasoning_effort_supported && (
        <p className="text-xs text-muted-foreground">OpenCode TUI launches cannot pin reasoning effort.</p>
      )}

      {(isCopilot || isOpenCode) && (
        <div className="grid gap-2">
          <Label htmlFor="provider-agent">Custom agent</Label>
          <Input
            id="provider-agent"
            value={stringValue(value.agent)}
            onChange={(event) => setOption('agent', event.target.value)}
            placeholder="Default"
            disabled={disabled}
          />
        </div>
      )}

      {isCopilot && (descriptor?.context_tier_options.length ?? 0) > 0 && (
        <div className="grid gap-2">
          <Label>Context</Label>
          <Select
            value={stringValue(value.context_tier) || DEFAULT_SELECT_VALUE}
            onValueChange={(next) => setOption('context_tier', next === DEFAULT_SELECT_VALUE ? '' : next)}
            disabled={disabled}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={DEFAULT_SELECT_VALUE}>Default</SelectItem>
              {descriptor?.context_tier_options.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {isCopilot && (
        <div className="grid gap-3 rounded-md border border-border p-3 md:grid-cols-2">
          {[
            ['plan', 'Plan mode'],
            ['remote', 'Remote control'],
            ['allow_all', 'Allow all'],
            ['no_ask_user', 'No ask user'],
          ].map(([key, label]) => (
            <label key={key} className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={boolValue(value[key])}
                onCheckedChange={(checked) => setOption(key as keyof SlotLaunchOptions, checked === true)}
                disabled={disabled}
              />
              {label}
            </label>
          ))}
        </div>
      )}

      {isCodex && (
        <Collapsible>
          <CollapsibleTrigger asChild>
            <Button type="button" variant="ghost" size="sm" className="w-fit px-0" disabled={disabled}>
              <ChevronDown className="mr-1 h-4 w-4" />
              Codex advanced
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="grid gap-3 rounded-md border border-border p-3 md:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="provider-sandbox">Sandbox</Label>
              <Input
                id="provider-sandbox"
                value={stringValue(value.sandbox)}
                onChange={(event) => setOption('sandbox', event.target.value)}
                placeholder="workspace-write"
                disabled={disabled}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="provider-approval">Approval policy</Label>
              <Input
                id="provider-approval"
                value={stringValue(value.approval_policy)}
                onChange={(event) => setOption('approval_policy', event.target.value)}
                placeholder="on-request"
                disabled={disabled}
              />
            </div>
            {[
              ['search', 'Search'],
              ['no_alt_screen', 'No alt screen'],
              ['dangerously_bypass_approvals_and_sandbox', 'Bypass approvals and sandbox'],
            ].map(([key, label]) => (
              <label key={key} className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={boolValue(value[key])}
                  onCheckedChange={(checked) => setOption(key as keyof SlotLaunchOptions, checked === true)}
                  disabled={disabled}
                />
                {label}
              </label>
            ))}
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  )
}
