import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ProviderProvider } from '../src/contexts/ProviderContext'
import { HarnessesPage } from '../src/features/harnesses/HarnessesPage'
import { SURFACE_GROUPS, surfaceInfo } from '../src/features/harnesses/surfaceCatalog'
import { surfaceRegistry, updateNativeMetadata } from '../src/features/native-settings/surfaceRegistry'
import { resetProviderOperations } from '../src/hooks/useProviders'
import type { AgentProviderId, ProviderOperations } from '../src/types/providers'
import fixture from './fixtures/provider-operations/v1/catalog.json'
import { fixtureFetch, jsonResponse, operationsFixtureResponse, renderRoute, settle } from './helpers/factory'

vi.mock('../src/contexts/DashboardContext', () => ({
  DashboardProvider: ({ children }: { children: React.ReactNode }) => children,
  useDashboard: () => ({ stats: { providerId: 'claude-code', warnings: [], unsupportedFeatures: [], sessionMetricKind: 'live', settingsKeys: 3, mcpServerCount: 1, commandCount: 0, hookCount: 3, sessionCount: 214, planCount: 31, contextActiveCount: null }, loading: false, error: null, lastFetched: null, refreshDashboard: () => undefined }),
}))
vi.mock('../src/contexts/ProjectContext', () => ({ useProjectContext: () => ({ projects: [], activeProject: null, knownFolders: [], setProjectPath: () => undefined, addProject: async () => undefined }) }))

const catalogs = fixture.providers as unknown as Record<AgentProviderId, ProviderOperations>
const ids = Object.keys(catalogs) as AgentProviderId[]
const statuses = ids.map(id => ({ id, display_name: id, installed: true, version: 'fixture', config_paths: {}, binary_path: null, capabilities: { config: true, plugins: true, usage: true }, capability_matrix: { ...catalogs[id].native_capabilities, config: { state: 'write_capable', reason: 'fixture' } } }))
const CODE_NAMES = /\b(config|mcp|plugins|commands|hooks|permissions|agents|skills|memory|backup|output-styles|output styles|statusline|sessions|plans|context|usage|summary)\b/
const ACCESS_CODES = /write capable|read only|write_capable|read_only/i

function answer(path: string) { return operationsFixtureResponse(path) ?? jsonResponse(path === 'providers' ? { providers: statuses } : {}) }

async function open(id: AgentProviderId) {
  window.history.replaceState({}, '', `/harnesses/${id}`)
  fixtureFetch(answer)
  renderRoute(<ProviderProvider><HarnessesPage /></ProviderProvider>, `/harnesses/${id}`, '/harnesses/:providerId')
  await settle()
}

/** The text of the page without "Technical details" and without the plain names and counts of the tiles. */
function plainText(root: HTMLElement) {
  const clone = root.cloneNode(true) as HTMLElement
  clone.querySelectorAll('details').forEach(details => { if (/technical details/i.test(details.querySelector('summary')?.textContent ?? '')) details.remove() })
  clone.querySelectorAll('[data-plain]').forEach(element => element.remove())
  return (clone.textContent ?? '').replace(/\s+/g, ' ')
}

beforeEach(() => { resetProviderOperations(); updateNativeMetadata([]); localStorage.clear() })
afterEach(() => { cleanup(); resetProviderOperations(); vi.restoreAllMocks() })

describe('surface catalog', () => {
  it('has a plain name, a group and a one-line purpose for every native page except the summary', () => {
    const claude = Object.keys(surfaceRegistry['claude-code']).filter(surface => surface !== 'summary')
    for (const surface of claude) {
      const info = surfaceInfo[surface as keyof typeof surfaceInfo]
      expect(info, surface).toBeDefined()
      expect(SURFACE_GROUPS).toContain(info!.group)
      expect(info!.name).toMatch(/^[A-Z]/)
      expect(info!.purpose.length).toBeGreaterThan(10)
      expect(info!.purpose, `${surface} purpose`).not.toMatch(CODE_NAMES)
    }
  })
})

describe('harness page', () => {
  it('groups the native pages with plain names, a one-line purpose and counts', async () => {
    await open('claude-code')

    for (const group of ['Settings', 'Extensions', 'History & usage', 'Safety']) expect(screen.getByRole('heading', { name: group })).toBeInTheDocument()
    const mcp = screen.getByRole('link', { name: 'MCP servers' })
    expect(mcp).toHaveAttribute('href', '/harnesses/claude-code/mcp')
    const tile = mcp.closest('li') as HTMLElement
    expect(within(tile).getByText('Tools that the harness can call')).toBeInTheDocument()
    expect(within(tile).getByText('1 server')).toBeInTheDocument()
    expect(within(screen.getByRole('link', { name: 'Slash commands' }).closest('li') as HTMLElement).getByText('None yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'All harnesses' })).toHaveAttribute('href', '/harnesses')
  })

  it('shows no code name and no access code outside Technical details', async () => {
    await open('claude-code')

    const text = plainText(screen.getByRole('heading', { name: 'Claude Code' }).closest('div')!.parentElement!.parentElement!)
    expect(text).not.toMatch(CODE_NAMES)
    expect(text).not.toMatch(ACCESS_CODES)
    expect(screen.getByText('Technical details')).toBeInTheDocument()
  })

  it('marks a read-only page with a lock and "View only", not with an access code', async () => {
    await open('claude-code')

    const sessions = screen.getByRole('link', { name: 'Sessions' }).closest('li') as HTMLElement
    expect(within(sessions).getByText('View only')).toBeInTheDocument()
    const mcp = screen.getByRole('link', { name: 'MCP servers' }).closest('li') as HTMLElement
    expect(within(mcp).queryByText('View only')).toBeNull()
  })

  it('says in one sentence that a harness has no settings pages and links to Teams and Live sessions', async () => {
    await open('pi-cli')

    expect(screen.getByText(/has no settings pages in Deck/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open Teams' })).toHaveAttribute('href', '/teams')
    expect(screen.getByRole('link', { name: 'Live sessions' })).toHaveAttribute('href', '/agent-bridge?provider=pi-cli')
  })
})
