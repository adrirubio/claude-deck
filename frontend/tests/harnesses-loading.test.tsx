import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { HarnessesPage } from '../src/features/harnesses/HarnessesPage'

const mocks = vi.hoisted(() => ({
  registry: { providers: [] as unknown[], loading: true, error: null as string | null },
  catalog: { state: 'loading' as 'idle' | 'loading' | 'ready' | 'error', catalog: null as unknown, refreshing: false },
}))
vi.mock('../src/contexts/ProviderContext', () => ({ useProviderContext: () => mocks.registry }))
vi.mock('../src/hooks/useProviders', () => ({
  useProviderOperations: () => ({ ...mocks.catalog, refresh: vi.fn() }),
}))

const NOT_LOADED = /\b(unknown|unavailable)\b/i

function renderPage() {
  return render(<MemoryRouter><HarnessesPage /></MemoryRouter>)
}

beforeEach(() => {
  mocks.registry = { providers: [], loading: true, error: null }
  mocks.catalog = { state: 'loading', catalog: null, refreshing: false }
})

describe('Harnesses page while it loads', () => {
  it('shows a skeleton card for every harness and no unknown or unavailable text while the registry loads', () => {
    renderPage()

    expect(screen.getAllByRole('article')).toHaveLength(6)
    for (const card of screen.getAllByRole('article')) expect(card).toHaveAttribute('aria-busy', 'true')
    expect(document.body.textContent).not.toMatch(NOT_LOADED)
    expect(screen.queryByRole('button', { name: 'Refresh observations' })).not.toBeInTheDocument()
  })

  it('keeps a card in the skeleton state until its own operating catalog loads', () => {
    mocks.registry = { providers: [], loading: false, error: null }
    mocks.catalog = { state: 'loading', catalog: null, refreshing: false }
    renderPage()

    for (const card of screen.getAllByRole('article')) expect(card).toHaveAttribute('aria-busy', 'true')
    expect(document.body.textContent).not.toMatch(NOT_LOADED)
  })

  it('shows a registry error once at page level and no cards', () => {
    mocks.registry = { providers: [], loading: false, error: 'Harness registry could not be loaded.' }
    renderPage()

    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.queryAllByRole('article')).toHaveLength(0)
    expect(document.body.textContent).not.toMatch(/\bunavailable\b/i)
  })

  it('shows one error line on a card whose catalog failed, and no unavailable surface list', () => {
    mocks.registry = { providers: [], loading: false, error: null }
    mocks.catalog = { state: 'error', catalog: null, refreshing: false }
    renderPage()

    const first = screen.getAllByRole('article')[0]
    expect(within(first).getAllByRole('alert')).toHaveLength(1)
    expect(within(first).queryByRole('navigation')).not.toBeInTheDocument()
    expect(first.textContent).not.toMatch(/: unavailable/)
  })
})
