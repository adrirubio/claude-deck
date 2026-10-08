import { useState } from 'react'
import { act, cleanup, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useLocation } from 'react-router-dom'
import { Sidebar } from '../src/components/layout/Sidebar'
import { SidebarContext } from '../src/contexts/SidebarContext'
import { ProviderProvider } from '../src/contexts/ProviderContext'
import { HarnessesPage } from '../src/features/harnesses/HarnessesPage'
import { OverviewPage, WorkPage, WorkDetailPage } from '../src/features/factory/FactoryPages'
import { resetFactoryReads } from '../src/features/factory/reads'
import { resetProviderOperations } from '../src/hooks/useProviders'
import { clearNativeCatalogs, updateNativeMetadata } from '../src/features/native-settings/surfaceRegistry'
import { fixtureFetch, jsonResponse, operationsFixtureResponse, renderRoute, settle } from './helpers/factory'
import work from './fixtures/factory/v1/work-items.json'
import detail from './fixtures/factory/v1/work-item.json'
import overview from './fixtures/factory/v1/overview.json'
import catalogs from './fixtures/provider-operations/v1/catalog.json'

vi.mock('../src/features/projects/ProjectSwitcher', () => ({ ProjectSwitcher: () => <span>Project chooser</span> }))
const providers = Object.entries(catalogs.providers).map(([id, catalog]) => ({
  id, display_name: id, installed: true, version: 'fixture', config_paths: {},
  capabilities: { config: true, plugins: true, usage: true },
  capability_matrix: { ...catalog.native_capabilities, config: { state: 'write_capable' }, plugins: { state: 'write_capable' }, usage: { state: 'supported' } },
}))
function Location() { const location = useLocation(); return <output aria-label="Current route">{location.pathname}{location.search}</output> }
function standard(path: string) { return operationsFixtureResponse(path) ?? jsonResponse(path === 'providers' ? { providers } : path === 'factory/overview' ? overview.normal.response : path === 'factory/work-items' ? work.first_page.response : {}) }
beforeEach(() => { resetFactoryReads(); resetProviderOperations(); updateNativeMetadata([]); localStorage.clear(); window.history.replaceState({}, '', '/') })
afterEach(() => { cleanup(); resetFactoryReads(); resetProviderOperations(); clearNativeCatalogs(); vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals() })

describe('navigation hierarchy preserves destinations and actions', () => {
  it('keeps harness destinations as links, unavailable adapters absent, refresh as a button and navigation GET-only', async () => {
    localStorage.setItem('claude-deck:selected-provider', 'pi-cli')
    const { requests } = fixtureFetch(standard)
    renderRoute(<ProviderProvider><Location/><HarnessesPage/></ProviderProvider>, '/harnesses', '*'); await settle()
    const surfaces = screen.getByRole('navigation', { name: 'Claude Code native surfaces' })
    expect(within(surfaces).getByRole('link', { name: /config \(write capable\)/ })).toHaveAttribute('href', '/harnesses/claude-code/config')
    expect(within(screen.getByRole('navigation', { name: 'OpenCode native surfaces' })).queryByRole('link')).toBeNull()
    expect(screen.getAllByRole('button', { name: 'Refresh observations' })).toHaveLength(5)
    expect(screen.queryByRole('button', { name: 'Teams and launch planning' })).toBeNull()
    const before = requests.length
    fireEvent.click(screen.getAllByRole('link', { name: 'Teams and launch planning' })[0]); await settle()
    expect(screen.getByLabelText('Current route')).toHaveTextContent('/teams')
    expect(localStorage.getItem('claude-deck:selected-provider')).toBe('pi-cli')
    expect(requests).toHaveLength(before); expect(requests.every(r => r.method === 'GET')).toBe(true)
  })
  it('does not intercept modified or middle clicks on Open details and still permits ordinary router navigation', async () => {
    vi.useFakeTimers(); const { requests } = fixtureFetch(standard)
    renderRoute(<><Location/><WorkPage/></>, '/work', '*'); await settle()
    const link = screen.getAllByRole('link', { name: 'Open details' })[0]
    const href = link.getAttribute('href')
    for (const options of [{ ctrlKey: true }, { metaKey: true }, { button: 1 }]) {
      const event = new MouseEvent('click', { bubbles: true, cancelable: true, ...options })
      act(() => link.dispatchEvent(event)); expect(event.defaultPrevented).toBe(false)
      expect(screen.getByLabelText('Current route')).toHaveTextContent(/^\/work$/)
    }
    fireEvent.click(link); await settle()
    expect(screen.getByLabelText('Current route')).toHaveTextContent(href!)
    expect(requests.every(r => r.method === 'GET')).toBe(true)
  })
  it('retains verified read-only and selected launch destinations while supporting references stay semantic anchors', async () => {
    const { requests } = fixtureFetch(() => jsonResponse(detail.completed.response))
    renderRoute(<WorkDetailPage/>, '/work/9', '/work/:workItemId'); await settle()
    const context = screen.getByRole('navigation', { name: 'Work context' })
    const session = within(context).getByRole('link', { name: 'Read-only verified session' })
    const url = new URL(session.getAttribute('href')!, 'http://fixture.test')
    expect(url.pathname).toBe('/agent-bridge'); expect(Object.fromEntries(url.searchParams)).toEqual({ team_id: '1', slot_id: '2', member_id: '2', session_id: '2', context: 'readonly' })
    expect(within(context).getByRole('link', { name: 'Review launch for Leader' })).toHaveAttribute('href', '/teams/1?slot_id=1&review_launch=1')
    expect(within(context).getByRole('link', { name: 'Team' })).toHaveAttribute('href', '/teams/1')
    expect(within(context).getByRole('link', { name: 'Repository scope' })).toHaveAttribute('href', '/repositories/1')
    expect(within(context).getByRole('link', { name: 'Mail context' })).toHaveAttribute('href', '/agent-mail?team_id=1&slot_id=2&member_id=2')
    expect(screen.getByRole('link', { name: 'Open issue' })).toHaveAttribute('target', '_blank')
    expect(screen.getByRole('link', { name: 'Open issue' })).toHaveAttribute('rel', 'noreferrer')
    expect(screen.getByRole('button', { name: 'Retry issue' })).toBeDisabled()
    expect(requests.every(r => r.method === 'GET')).toBe(true)
  })
  it('keeps offline session inspection unbound and launch review on the verified owner slot', async () => {
    fixtureFetch(() => jsonResponse(detail.verified_offline_owner.response))
    renderRoute(<WorkDetailPage/>, '/work/2', '/work/:workItemId'); await settle()
    const context = screen.getByRole('navigation', { name: 'Work context' })
    expect(within(context).queryByRole('link', { name: 'Read-only verified session' })).toBeNull()
    expect(within(context).getByRole('link', { name: 'Inspect team/slot sessions' })).toHaveAttribute('href', '/agent-bridge?team_id=2&slot_id=4&context=readonly')
    expect(within(context).getByRole('link', { name: /Review launch for/ })).toHaveAttribute('href', '/teams/2?slot_id=4&review_launch=1')
    expect(screen.queryByRole('button', { name: /Review launch/ })).toBeNull()
  })
  it('preserves descendant active state, collapsed accessible names and the saved native preference', async () => {
    function Shell() { const [collapsed, setCollapsed] = useState(false); return <SidebarContext.Provider value={{ collapsed, setCollapsed }}><Sidebar/><Location/></SidebarContext.Provider> }
    localStorage.setItem('claude-deck:selected-provider', 'pi-cli'); fixtureFetch(standard)
    renderRoute(<ProviderProvider><Shell/></ProviderProvider>, '/work/9', '*'); await settle()
    const nav = screen.getByRole('navigation', { name: 'Main navigation' })
    expect(within(nav).getByRole('link', { name: 'Work' })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('link', { name: 'Overview' })).not.toHaveAttribute('aria-current')
    fireEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument()
    expect(within(nav).getAllByRole('link')).toHaveLength(9)
    for (const link of within(nav).getAllByRole('link')) expect(link).toHaveAttribute('title', link.getAttribute('aria-label'))
    fireEvent.click(within(nav).getByRole('link', { name: 'Harnesses' })); await settle()
    expect(within(nav).getByRole('link', { name: 'Harnesses' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByLabelText('Current route')).toHaveTextContent('/harnesses')
    expect(localStorage.getItem('claude-deck:selected-provider')).toBe('pi-cli')
  })
  it('keeps the empty-factory Open Harnesses destination as a link without launching or requesting native data', async () => {
    const empty = { ...overview.normal.response, counts: Object.fromEntries(Object.keys(overview.normal.response.counts).map(k => [k, 0])), automation: { ...overview.normal.response.automation, configured_scopes: 0 } }
    const { requests } = fixtureFetch(path => jsonResponse(path === 'factory/overview' ? empty : path === 'factory/repositories' ? { schema_version: 1, generated_at: empty.generated_at, repositories: [], has_more: false, next_cursor: null, filtered_total: 0 } : { ...work.first_page.response, work_items: [] }))
    renderRoute(<OverviewPage/>, '/', '/'); await settle()
    expect(screen.getByRole('link', { name: 'Open Harnesses and configuration' })).toHaveAttribute('href', '/harnesses')
    expect(screen.queryByRole('button', { name: /Open Harnesses/ })).toBeNull()
    expect(requests.every(r => r.method === 'GET' && !/operations|launch|inbox|claim/.test(r.path))).toBe(true)
  })
})
