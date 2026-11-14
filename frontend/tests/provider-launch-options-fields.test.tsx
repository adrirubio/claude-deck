import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
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

const OPUS = 'claude-opus-5-5'
const SONNET = 'claude-sonnet-5-5'
const ARN = 'arn:aws:bedrock:us-east-1:123456789012:inference-profile/profile-1'
const EFFORT_LABELS = ['Low', 'Medium', 'High', 'Extra High', 'Max']

const CLAUDE: ProviderLaunchOptionsResponse = {
  provider: 'claude-code',
  supported_launch_modes: ['plain', 'worktree', 'resume'],
  supported_launch_options: ['skip_permissions', 'platform', 'aws_region', 'aws_profile', 'bedrock_model', 'model', 'reasoning_effort', 'prompt'],
  platform_options: ['anthropic', 'bedrock'],
  default_platform: 'anthropic',
  bedrock_supported: true,
  reasoning_effort_supported: true,
  reasoning_effort_options: ['low', 'medium', 'high', 'xhigh', 'max'].map((value, index) => ({ value, label: EFFORT_LABELS[index] })),
  context_tier_options: [],
  model_options: [
    { value: OPUS, label: 'Claude Opus 5.5' },
    { value: SONNET, label: 'Claude Sonnet 5.5' },
    { value: 'arn:aws:bedrock:REGION:ACCOUNT:inference-profile/PROFILE_ID', label: 'Amazon Bedrock inference profile ARN' },
  ],
  profile_options: [],
  model_examples: [],
  warnings: [],
}

const CODEX: ProviderLaunchOptionsResponse = {
  ...CLAUDE,
  provider: 'codex-cli',
  supported_launch_options: ['model', 'profile', 'platform', 'reasoning_effort'],
  reasoning_effort_options: [{ value: 'high', label: 'High' }],
  model_options: [{ value: 'gpt-5.5', label: 'GPT-5.5' }],
}

function selectWithOption(text: string) {
  const found = screen.getAllByRole('combobox').find(element => within(element).queryByText(text, { exact: false }))
  if (!found) throw new Error(`no select offers "${text}"`)
  return found
}

describe('Claude Code model and effort (#869)', () => {
  it('offers a model select with the default, the concrete examples and a custom entry on the default platform', () => {
    render(<ProviderLaunchOptionsFields provider="claude-code" value={{}} onChange={vi.fn()} descriptor={CLAUDE} />)

    const model = selectWithOption('Claude Opus 5.5')
    expect(within(model).getByText('Default')).toBeInTheDocument()
    expect(within(model).getByText('Claude Sonnet 5.5')).toBeInTheDocument()
    expect(within(model).getByText('Custom model')).toBeInTheDocument()
    expect(model).toHaveValue('__default__')
  })

  it('does not offer the Bedrock inference profile example as a model on the default platform', () => {
    render(<ProviderLaunchOptionsFields provider="claude-code" value={{}} onChange={vi.fn()} descriptor={CLAUDE} />)

    expect(screen.queryByText('Amazon Bedrock inference profile ARN', { exact: false })).not.toBeInTheDocument()
  })

  it('stores the chosen example as model and clears it again with Default', () => {
    const onChange = vi.fn()
    const { rerender } = render(<ProviderLaunchOptionsFields provider="claude-code" value={{ reasoning_effort: 'low' }} onChange={onChange} descriptor={CLAUDE} />)

    fireEvent.change(selectWithOption('Claude Opus 5.5'), { target: { value: OPUS } })
    expect(onChange).toHaveBeenLastCalledWith({ reasoning_effort: 'low', model: OPUS })

    rerender(<ProviderLaunchOptionsFields provider="claude-code" value={{ model: OPUS, reasoning_effort: 'low' }} onChange={onChange} descriptor={CLAUDE} />)
    expect(selectWithOption('Claude Opus 5.5')).toHaveValue(OPUS)
    fireEvent.change(selectWithOption('Claude Opus 5.5'), { target: { value: '__default__' } })
    expect(onChange).toHaveBeenLastCalledWith({ reasoning_effort: 'low' })
  })

  it('takes a custom concrete model id and shows an unlisted stored model as custom', () => {
    const onChange = vi.fn()
    const { rerender } = render(<ProviderLaunchOptionsFields provider="claude-code" value={{}} onChange={onChange} descriptor={CLAUDE} />)
    expect(screen.queryByPlaceholderText('model name')).not.toBeInTheDocument()

    rerender(<ProviderLaunchOptionsFields provider="claude-code" value={{ model: 'claude-haiku-4-5-20251001' }} onChange={onChange} descriptor={CLAUDE} />)
    expect(selectWithOption('Claude Opus 5.5')).toHaveValue('__custom__')
    const custom = screen.getByPlaceholderText('model name')
    expect(custom).toHaveValue('claude-haiku-4-5-20251001')
    fireEvent.change(custom, { target: { value: 'claude-fable-5-1' } })
    expect(onChange).toHaveBeenLastCalledWith({ model: 'claude-fable-5-1' })
  })

  it('stores the reasoning effort and clears it with Default', () => {
    const onChange = vi.fn()
    const { rerender } = render(<ProviderLaunchOptionsFields provider="claude-code" value={{ model: OPUS }} onChange={onChange} descriptor={CLAUDE} />)

    const effort = selectWithOption('Extra High')
    expect(within(effort).getAllByRole('option').map(option => option.textContent)).toEqual(['Default', ...EFFORT_LABELS])
    fireEvent.change(effort, { target: { value: 'xhigh' } })
    expect(onChange).toHaveBeenLastCalledWith({ model: OPUS, reasoning_effort: 'xhigh' })

    rerender(<ProviderLaunchOptionsFields provider="claude-code" value={{ model: OPUS, reasoning_effort: 'xhigh' }} onChange={onChange} descriptor={CLAUDE} />)
    fireEvent.change(selectWithOption('Extra High'), { target: { value: '__default__' } })
    expect(onChange).toHaveBeenLastCalledWith({ model: OPUS })
  })

  it('keeps the Bedrock model id as bedrock_model and shows no model select on Bedrock', () => {
    const onChange = vi.fn()
    render(<ProviderLaunchOptionsFields provider="claude-code" value={{ platform: 'bedrock' }} onChange={onChange} descriptor={CLAUDE} />)

    expect(screen.queryByText('Custom model')).not.toBeInTheDocument()
    const input = screen.getByLabelText('Bedrock model ID')
    expect(input).toHaveAttribute('placeholder', 'arn:aws:bedrock:...')
    fireEvent.change(input, { target: { value: ARN } })
    expect(onChange).toHaveBeenLastCalledWith({ platform: 'bedrock', bedrock_model: ARN })
  })

  it('drops the model when the platform changes to Bedrock, so no conflict is stored', () => {
    const onChange = vi.fn()
    render(<ProviderLaunchOptionsFields provider="claude-code" value={{ model: OPUS, reasoning_effort: 'high' }} onChange={onChange} descriptor={CLAUDE} />)

    fireEvent.change(selectWithOption('Amazon Bedrock'), { target: { value: 'bedrock' } })
    expect(onChange).toHaveBeenLastCalledWith({ reasoning_effort: 'high', platform: 'bedrock' })
  })

  it('drops the Bedrock model id when the platform changes back, and keeps the other Bedrock fields', () => {
    const onChange = vi.fn()
    render(
      <ProviderLaunchOptionsFields
        provider="claude-code"
        value={{ platform: 'bedrock', bedrock_model: ARN, aws_region: 'us-east-1', aws_profile: 'prod', reasoning_effort: 'low' }}
        onChange={onChange}
        descriptor={CLAUDE}
      />,
    )

    fireEvent.change(selectWithOption('Amazon Bedrock'), { target: { value: 'anthropic' } })
    expect(onChange).toHaveBeenLastCalledWith({ aws_region: 'us-east-1', aws_profile: 'prod', reasoning_effort: 'low' })
  })

  it('says so when a stored Bedrock slot sets both model and the Bedrock model id', () => {
    render(<ProviderLaunchOptionsFields provider="claude-code" value={{ platform: 'bedrock', model: OPUS, bedrock_model: ARN }} onChange={vi.fn()} descriptor={CLAUDE} />)

    expect(screen.getByRole('alert')).toHaveTextContent('Model and Bedrock model ID cannot both be set on Bedrock')
    expect(screen.getByLabelText('Bedrock model ID')).toHaveValue(ARN)
  })

  it('lets the user clear the stale model from the conflict message', () => {
    const onChange = vi.fn()
    render(<ProviderLaunchOptionsFields provider="claude-code" value={{ platform: 'bedrock', model: OPUS, bedrock_model: ARN }} onChange={onChange} descriptor={CLAUDE} />)

    fireEvent.click(screen.getByRole('button', { name: 'Clear model' }))
    expect(onChange).toHaveBeenLastCalledWith({ platform: 'bedrock', bedrock_model: ARN })
  })

  it('shows no conflict message for a Bedrock slot with only the Bedrock model id', () => {
    render(<ProviderLaunchOptionsFields provider="claude-code" value={{ platform: 'bedrock', bedrock_model: ARN }} onChange={vi.fn()} descriptor={CLAUDE} />)

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('leaves Codex unchanged: its model select stays and a platform change keeps the model', () => {
    const onChange = vi.fn()
    render(<ProviderLaunchOptionsFields provider="codex-cli" value={{ model: 'gpt-5.5' }} onChange={onChange} descriptor={CODEX} />)

    expect(selectWithOption('GPT-5.5')).toHaveValue('gpt-5.5')
    expect(screen.getByText('Custom profile')).toBeInTheDocument()
    fireEvent.change(selectWithOption('Amazon Bedrock'), { target: { value: 'bedrock' } })
    expect(onChange).toHaveBeenLastCalledWith({ model: 'gpt-5.5', platform: 'bedrock' })
  })
})

// V1 finding on #889: Custom model must open an editable state. These tests drive a real stateful parent.
function Stateful({ provider = 'claude-code', initial = {}, descriptor = CLAUDE }: { provider?: string; initial?: Record<string, unknown>; descriptor?: ProviderLaunchOptionsResponse }) {
  const [value, setValue] = useState<Record<string, unknown>>(initial)
  return (
    <>
      <ProviderLaunchOptionsFields provider={provider} value={value} onChange={next => setValue(next)} descriptor={descriptor} />
      <output data-testid="options">{JSON.stringify(value)}</output>
    </>
  )
}
const stored = () => JSON.parse(screen.getByTestId('options').textContent ?? '{}')
const customInput = () => screen.queryByPlaceholderText('model name')
const modelSelect = () => selectWithOption('Custom model')

describe('Claude custom model entry', () => {
  it('opens an empty editable input when Custom model is chosen from Default, and stores what is typed', () => {
    render(<Stateful />)
    expect(customInput()).not.toBeInTheDocument()

    fireEvent.change(modelSelect(), { target: { value: '__custom__' } })
    expect(modelSelect()).toHaveValue('__custom__')
    expect(customInput()).toHaveValue('')
    expect(stored()).toEqual({})

    fireEvent.change(customInput()!, { target: { value: 'claude-haiku-4-5-20251001' } })
    expect(stored()).toEqual({ model: 'claude-haiku-4-5-20251001' })
    expect(modelSelect()).toHaveValue('__custom__')
  })

  it('opens the input from a listed model, keeping that value to edit, and stores the replacement', () => {
    render(<Stateful initial={{ model: OPUS }} />)
    expect(modelSelect()).toHaveValue(OPUS)

    fireEvent.change(modelSelect(), { target: { value: '__custom__' } })
    expect(modelSelect()).toHaveValue('__custom__')
    expect(customInput()).toHaveValue(OPUS)

    fireEvent.change(customInput()!, { target: { value: 'claude-fable-5-1' } })
    expect(stored()).toEqual({ model: 'claude-fable-5-1' })
  })

  it('keeps the input while it is cleared and typed again', () => {
    render(<Stateful />)
    fireEvent.change(modelSelect(), { target: { value: '__custom__' } })
    fireEvent.change(customInput()!, { target: { value: 'claude-fable-5-1' } })

    fireEvent.change(customInput()!, { target: { value: '' } })
    expect(customInput()).toBeInTheDocument()
    expect(modelSelect()).toHaveValue('__custom__')
    expect(stored()).toEqual({})

    fireEvent.change(customInput()!, { target: { value: 'claude-sonnet-5-5' } })
    expect(stored()).toEqual({ model: 'claude-sonnet-5-5' })
  })

  it('keeps the input open while a stored custom model is cleared, then retyped', () => {
    render(<Stateful initial={{ model: 'claude-haiku-4-5-20251001' }} />)
    expect(modelSelect()).toHaveValue('__custom__')

    fireEvent.change(customInput()!, { target: { value: '' } })
    expect(customInput()).toBeInTheDocument()
    expect(stored()).toEqual({})
    fireEvent.change(customInput()!, { target: { value: 'claude-opus-5-5' } })
    expect(stored()).toEqual({ model: OPUS })
  })

  it('closes the input and clears the model when Default is chosen again', () => {
    render(<Stateful />)
    fireEvent.change(modelSelect(), { target: { value: '__custom__' } })
    fireEvent.change(customInput()!, { target: { value: 'claude-fable-5-1' } })

    fireEvent.change(modelSelect(), { target: { value: '__default__' } })
    expect(customInput()).not.toBeInTheDocument()
    expect(modelSelect()).toHaveValue('__default__')
    expect(stored()).toEqual({})
  })

  it('closes the input and stores the listed model when one is chosen after Custom', () => {
    render(<Stateful />)
    fireEvent.change(modelSelect(), { target: { value: '__custom__' } })
    fireEvent.change(customInput()!, { target: { value: 'claude-fable-5-1' } })

    fireEvent.change(modelSelect(), { target: { value: SONNET } })
    expect(customInput()).not.toBeInTheDocument()
    expect(modelSelect()).toHaveValue(SONNET)
    expect(stored()).toEqual({ model: SONNET })
  })

  it('does not reopen the custom input when a typed id equals a listed model and Default is chosen', () => {
    render(<Stateful />)
    fireEvent.change(modelSelect(), { target: { value: '__custom__' } })
    fireEvent.change(customInput()!, { target: { value: OPUS } })
    expect(customInput()).toBeInTheDocument()

    fireEvent.change(modelSelect(), { target: { value: '__default__' } })
    expect(customInput()).not.toBeInTheDocument()
    expect(stored()).toEqual({})
  })

  it('resets the custom entry across platform switches and keeps the Bedrock rules', () => {
    render(<Stateful initial={{ reasoning_effort: 'high' }} />)
    fireEvent.change(modelSelect(), { target: { value: '__custom__' } })
    fireEvent.change(customInput()!, { target: { value: 'claude-fable-5-1' } })

    fireEvent.change(selectWithOption('Amazon Bedrock'), { target: { value: 'bedrock' } })
    expect(stored()).toEqual({ reasoning_effort: 'high', platform: 'bedrock' })
    expect(screen.getByLabelText('Bedrock model ID')).toHaveValue('')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    fireEvent.change(selectWithOption('Amazon Bedrock'), { target: { value: 'anthropic' } })
    expect(customInput()).not.toBeInTheDocument()
    expect(modelSelect()).toHaveValue('__default__')
    expect(stored()).toEqual({ reasoning_effort: 'high' })
  })

  // Characterization, not a wish: Codex is not changed by this PR. Its Custom model choice from Default does not open the
  // input (a defect that predates #869, to be handled on its own), and the Claude correction must not leak into it.
  it('leaves the Codex Custom model choice as it was before this change', () => {
    render(<Stateful provider="codex-cli" descriptor={CODEX} />)

    fireEvent.change(selectWithOption('Custom model'), { target: { value: '__custom__' } })
    expect(customInput()).not.toBeInTheDocument()
    expect(selectWithOption('Custom model')).toHaveValue('__default__')
    expect(stored()).toEqual({})
  })

  it('leaves a Codex stored custom model unchanged', () => {
    render(<Stateful provider="codex-cli" initial={{ model: 'gpt-6-preview' }} descriptor={CODEX} />)
    expect(selectWithOption('Custom model')).toHaveValue('__custom__')
    expect(customInput()).toHaveValue('gpt-6-preview')
    fireEvent.change(customInput()!, { target: { value: 'gpt-6' } })
    expect(stored()).toEqual({ model: 'gpt-6' })
  })
})
