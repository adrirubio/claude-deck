import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useLocation } from 'react-router-dom'
import { ProviderProvider } from '../src/contexts/ProviderContext'
import { HarnessesPage } from '../src/features/harnesses/HarnessesPage'
import { updateNativeMetadata } from '../src/features/native-settings/surfaceRegistry'
import { resetProviderOperations } from '../src/hooks/useProviders'
import { fetchAgentTeamPresets } from '../src/features/agent-teams/api'
import type { AgentProviderId, ProviderOperations } from '../src/types/providers'
import fixture from './fixtures/provider-operations/v1/catalog.json'
import { fixtureFetch, jsonResponse, operationsFixtureResponse, renderRoute, settle } from './helpers/factory'

vi.mock('../src/features/agent-teams/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/features/agent-teams/api')>()),
  fetchAgentTeamPresets: vi.fn(),
}))
vi.mock('../src/contexts/DashboardContext', () => ({
  DashboardProvider: ({ children }: { children: React.ReactNode }) => children,
  useDashboard: () => ({ stats: null, loading: false, error: null, lastFetched: null, refreshDashboard: () => undefined }),
}))
vi.mock('../src/contexts/ProjectContext', () => ({ useProjectContext: () => ({ projects: [], activeProject: null, knownFolders: [], setProjectPath: () => undefined, addProject: async () => undefined }) }))

const catalogs = fixture.providers as unknown as Record<AgentProviderId, ProviderOperations>
const ids = Object.keys(catalogs) as AgentProviderId[]
const TECHNICAL = /\bunknown\b|\badapter\b|\bbinding\b|\b[a-z]+(?:_[a-z]+)+\b|write capable|read only/i

function statusesWith(overrides: Partial<Record<AgentProviderId, { installed: boolean }>> = {}) {
  return ids.map(id => ({ id, display_name: id, installed: overrides[id]?.installed ?? true, version: '1.2.3', config_paths: {}, binary_path: null, capabilities: { config: true, plugins: true, usage: true }, capability_matrix: { ...catalogs[id].native_capabilities, config: { state: 'write_capable', reason: 'fixture' } } }))
}

function open(overrides: Partial<Record<AgentProviderId, { installed: boolean }>> = {}, catalogFor?: (id: string) => ProviderOperations) {
  const statuses = statusesWith(overrides)
  fixtureFetch(path => {
    const match = /^providers\/([^/]+)\/operations$/.exec(path)
    if (match && catalogFor) return jsonResponse(catalogFor(match[1]))
    return operationsFixtureResponse(path) ?? jsonResponse(path === 'providers' ? { providers: statuses } : {})
  })
  function Where() { return <output aria-label="route">{useLocation().pathname}</output> }
  renderRoute(<ProviderProvider><Where /><HarnessesPage /></ProviderProvider>, '/harnesses', '*')
}

const card = (name: string) => screen.getByRole('heading', { name: new RegExp(name) }).closest('article') as HTMLElement

beforeEach(() => {
  resetProviderOperations(); updateNativeMetadata([]); localStorage.clear(); window.history.replaceState({}, '', '/harnesses')
  vi.mocked(fetchAgentTeamPresets).mockResolvedValue({ presets: [
    { id: 1, slots: [{ provider: 'claude-code' }, { provider: 'claude-code' }, { provider: 'codex-cli' }] },
    { id: 2, slots: [{ provider: 'claude-code' }] },
  ] } as never)
})
afterEach(() => { cleanup(); resetProviderOperations(); vi.restoreAllMocks() })

describe('compact harness list', () => {
  it('shows status, version, page count and the number of teams on one card per harness', async () => {
    open(); await settle()

    expect(screen.getAllByRole('article')).toHaveLength(5)
    const claude = card('Claude Code')
    expect(within(claude).getByText('Ready')).toBeInTheDocument()
    expect(within(claude).getByText('v1.2.3')).toBeInTheDocument()
    expect(within(claude).getByText(/settings pages · used by 2 teams/)).toBeInTheDocument()
    expect(within(card('Codex CLI')).getByText(/used by 1 team$/)).toBeInTheDocument()
    expect(within(card('Pi')).getByText(/No settings pages in Deck/)).toBeInTheDocument()
  })

  it('shows the page count only when the teams cannot be read', async () => {
    vi.mocked(fetchAgentTeamPresets).mockRejectedValue(new Error('no'))
    open(); await settle()

    expect(within(card('Claude Code')).getByText(/settings pages$/)).toBeInTheDocument()
    expect(screen.queryByText(/used by/)).toBeNull()
  })

  it('shows Not installed in neutral grey with an install link, not an error colour', async () => {
    open({ 'copilot-cli': { installed: false } }); await settle()

    const copilot = card('Copilot CLI')
    const badge = within(copilot).getByText('Not installed')
    expect(badge.className).toContain('text-muted-foreground')
    expect(badge.className).not.toMatch(/red|destructive|amber/)
    expect(within(copilot).getByText('Install it to use it in a team.')).toBeInTheDocument()
    expect(within(copilot).getByRole('link', { name: /How to install/ })).toHaveAttribute('href', '/harnesses/copilot-cli')
  })

  it('shows Needs setup in amber with the reason in one line', async () => {
    const scenarios = fixture.scenarios as unknown as Record<string, ProviderOperations>
    open({}, id => (id === 'codex-cli' ? scenarios.mail_not_positively_configured : catalogs[id as AgentProviderId])); await settle()

    const codex = card('Codex CLI')
    const badge = within(codex).getByText('Needs setup')
    expect(badge.className).toContain('text-amber-700')
    expect(badge.className).toContain('dark:text-amber-400')
    expect(within(codex).getByText(/Codex Agent Mail MCP is not installed/)).toBeInTheDocument()
  })

  it('opens the harness page when the whole card is clicked or when Enter or Space is pressed on it', async () => {
    open(); await settle()

    fireEvent.click(within(card('Codex CLI')).getByText(/settings pages/))
    expect(screen.getByLabelText('route')).toHaveTextContent('/harnesses/codex-cli')
  })

  it('opens the harness page with Enter and Space on the focused card, and once for the inner link', async () => {
    open(); await settle()

    fireEvent.keyDown(card('Claude Code'), { key: 'Enter' })
    expect(screen.getByLabelText('route')).toHaveTextContent('/harnesses/claude-code')
    fireEvent.keyDown(card('Codex CLI'), { key: ' ' })
    expect(screen.getByLabelText('route')).toHaveTextContent('/harnesses/codex-cli')
    fireEvent.keyDown(within(card('Pi')).getByRole('link'), { key: 'Enter' })
    expect(screen.getByLabelText('route')).toHaveTextContent('/harnesses/codex-cli')
  })

  it('shows no technical word, no Technical details and no Refresh button on a card', async () => {
    open(); await settle()

    for (const article of screen.getAllByRole('article')) expect(article.textContent).not.toMatch(TECHNICAL)
    expect(screen.queryByText('Technical details')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Refresh observations' })).toBeNull()
  })

  it('uses the clickable card style and is reachable by keyboard', async () => {
    open(); await settle()

    for (const article of screen.getAllByRole('article')) {
      expect(article).toHaveAttribute('tabindex', '0')
      expect(article.className).toContain('border-2')
      expect(article.className).toContain('cursor-pointer')
    }
  })
})
