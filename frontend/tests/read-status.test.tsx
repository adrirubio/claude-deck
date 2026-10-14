import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { ReadStatus } from '../src/features/factory/components/ReadStatus'
import { ApiHttpError } from '../src/lib/api'
import type { ReadState } from '../src/features/factory/reads'

// #698: a routine background refresh with data on screen shows nothing.
function state(changes: Partial<ReadState<{ ok: boolean }>> = {}): ReadState<{ ok: boolean }> {
  return { data: null, error: null, refreshing: false, retrying: false, stopped: false, ...changes }
}
function view(value: ReadState<{ ok: boolean }>) {
  return render(<MemoryRouter><ReadStatus state={value} /></MemoryRouter>)
}

describe('ReadStatus', () => {
  it('renders nothing visible while it refreshes data that is already shown', () => {
    const { container } = view(state({ data: { ok: true }, refreshing: true }))
    expect(container.textContent).toBe('')
    expect(container.querySelector('p')).toBeNull()
  })

  it('renders Loading… while it reads the first data', () => {
    const { container } = view(state({ refreshing: true }))
    expect(container.textContent).toBe('Loading…')
  })

  it('renders nothing when it is not refreshing', () => {
    const { container } = view(state({ data: { ok: true } }))
    expect(container.textContent).toBe('')
  })

  it('announces an error and keeps the last good data message', () => {
    const { getByRole } = view(state({
      data: { ok: true }, refreshing: true, retrying: true, error: new Error('Server error'),
    }))
    expect(getByRole('alert').textContent).toContain('Data may be out of date. The refresh failed. The last good data stays visible.')
    expect(getByRole('alert').textContent).toContain('Server error')
  })

  it('announces an error that comes before any data', () => {
    const { getByRole, queryByText } = view(state({ error: new Error('Server error') }))
    expect(getByRole('alert').textContent).toBe('Server error')
    expect(queryByText(/out of date/)).toBeNull()
  })

  it('names a missing thing and keeps the way back', () => {
    const error = new ApiHttpError('Not found', 404)
    const { getByRole } = render(
      <MemoryRouter>
        <ReadStatus state={state({ error, stopped: true })} missing="work item" back={{ to: '/work', label: 'Back to Work' }} />
      </MemoryRouter>,
    )
    expect(getByRole('alert').textContent).toBe('This work item does not exist.')
    expect(getByRole('link', { name: /Back to Work/ }).getAttribute('href')).toBe('/work')
  })
})
