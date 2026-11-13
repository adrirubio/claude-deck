import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProviderLaunchOptionsFields } from '../src/features/providers/ProviderLaunchOptionsFields'
import type { ProviderLaunchOptionsResponse } from '../src/types/providers'

vi.mock('../src/components/ui/select', () => ({
  Select: ({ value, onValueChange, children }: { value: string; onValueChange: (value: string) => void; children: React.ReactNode }) => (
    <select value={value} onChange={event => onValueChange(event.target.value)}><option value="" hidden />{children}</select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: React.ReactNode }) => <option value={value}>{children}</option>,
}))

const OPENCODE: ProviderLaunchOptionsResponse = {
  provider: 'opencode-cli',
  supported_launch_modes: ['plain', 'resume'],
  supported_launch_options: ['model', 'agent', 'skip_permissions', 'session_id', 'platform', 'aws_region', 'aws_profile', 'reasoning_effort', 'prompt'],
  platform_options: ['anthropic', 'bedrock'],
  default_platform: 'anthropic',
  bedrock_supported: true,
  reasoning_effort_supported: false,
  reasoning_effort_options: [],
  context_tier_options: [],
  model_options: [],
  profile_options: [],
  model_examples: [],
  warnings: [],
}

afterEach(cleanup)

describe('OpenCode 2 launch options', () => {
  it('asks for a provider/model with an optional variant and a default agent', () => {
    const onChange = vi.fn()
    render(<ProviderLaunchOptionsFields provider="opencode-cli" value={{}} onChange={onChange} descriptor={OPENCODE} />)

    expect(screen.getByLabelText('Model')).toHaveAttribute('placeholder', 'provider/model or provider/model#variant')
    fireEvent.change(screen.getByLabelText('Default agent'), { target: { value: 'plan' } })
    expect(onChange).toHaveBeenLastCalledWith({ agent: 'plan' })
    expect(screen.queryByLabelText('Custom agent')).not.toBeInTheDocument()
  })

  it('maps "Auto-approve permissions" to skip_permissions, off by default', () => {
    const onChange = vi.fn()
    render(<ProviderLaunchOptionsFields provider="opencode-cli" value={{}} onChange={onChange} descriptor={OPENCODE} />)

    const auto = screen.getByRole('checkbox', { name: 'Auto-approve permissions (--auto)' })
    expect(auto).not.toBeChecked()
    expect(screen.getByText('Deny rules still apply.')).toBeInTheDocument()
    fireEvent.click(auto)
    expect(onChange).toHaveBeenLastCalledWith({ skip_permissions: true })
  })

  it('names the amazon-bedrock/ model a Bedrock member needs', () => {
    render(<ProviderLaunchOptionsFields provider="opencode-cli" value={{ platform: 'bedrock' }} onChange={vi.fn()} descriptor={OPENCODE} />)

    expect(screen.getByText('On Bedrock, use an amazon-bedrock/ model.')).toBeInTheDocument()
  })

  it('keeps the Copilot agent field as a custom agent', () => {
    render(<ProviderLaunchOptionsFields provider="copilot-cli" value={{}} onChange={vi.fn()} descriptor={{ ...OPENCODE, provider: 'copilot-cli' }} />)

    expect(screen.getByLabelText('Custom agent')).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: 'Auto-approve permissions (--auto)' })).not.toBeInTheDocument()
  })
})
