import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LegacyNativeRedirect } from '../src/features/native-settings/LegacyNativeRedirect'

const provider = vi.hoisted(() => ({
  value: {} as {
    loading: boolean
    selectedProviderId: string
    providers: Array<{ id: string; installed: boolean }>
  },
}))
vi.mock('../src/contexts/ProviderContext', () => ({ useProviderContext: () => provider.value }))

const PROVIDERS = [
  { id: 'claude-code', installed: false },
  { id: 'codex-cli', installed: true },
  { id: 'copilot-cli', installed: true },
]

function Where() {
  const { pathname, search, hash } = useLocation()
  return <output aria-label="location">{pathname + search + hash}</output>
}

function open(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/harnesses/*" element={<Where />} />
        <Route path="*" element={<LegacyNativeRedirect />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  provider.value = { loading: false, selectedProviderId: 'copilot-cli', providers: PROVIDERS }
})

describe('LegacyNativeRedirect', () => {
  it.each([
    ['/config', '/harnesses/copilot-cli/config'],
    ['/mcp', '/harnesses/copilot-cli/mcp'],
    ['/output-styles', '/harnesses/copilot-cli/output-styles'],
    ['/sessions/-home-demo/abc-123', '/harnesses/copilot-cli/sessions/-home-demo/abc-123'],
    ['/plans/my-plan.md', '/harnesses/copilot-cli/plans/my-plan.md'],
  ])('sends %s to %s', (from, to) => {
    open(from)

    expect(screen.getByLabelText('location')).toHaveTextContent(to)
  })

  it('keeps the project choice and the hash', () => {
    open('/mcp?project=%2Fwork%2Fdemo&x=1#servers')

    expect(screen.getByLabelText('location')).toHaveTextContent('/harnesses/copilot-cli/mcp?project=%2Fwork%2Fdemo&x=1#servers')
  })

  it('uses the first installed harness when the saved preference is not a known harness', () => {
    provider.value = { loading: false, selectedProviderId: '../evil', providers: PROVIDERS }
    open('/config')

    expect(screen.getByLabelText('location')).toHaveTextContent('/harnesses/codex-cli/config')
    expect(screen.getByLabelText('location').textContent).not.toContain('evil')
  })

  it('falls back to the first listed harness when none is installed', () => {
    provider.value = { loading: false, selectedProviderId: 'nope', providers: PROVIDERS.map(p => ({ ...p, installed: false })) }
    open('/hooks')

    expect(screen.getByLabelText('location')).toHaveTextContent('/harnesses/claude-code/hooks')
  })

  it('waits while the harness list loads', () => {
    provider.value = { loading: true, selectedProviderId: 'claude-code', providers: [] }
    open('/config')
    expect(screen.getByRole('status')).toHaveTextContent('Loading harness registry')
  })

  it('shows a message and does not redirect when there is no harness', () => {
    provider.value = { loading: false, selectedProviderId: 'claude-code', providers: [] }
    open('/config')

    expect(screen.getByText('No harness available')).toBeInTheDocument()
    expect(screen.queryByLabelText('location')).not.toBeInTheDocument()
  })
})
