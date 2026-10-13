import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NewSessionDialog } from '../src/features/cc-bridge/NewSessionDialog'
import { clearOperatorToken, getOperatorToken, setOperatorToken } from '../src/features/agent-teams/operatorAuth'
import { ApiHttpError } from '../src/lib/api'
import { spawnSession } from '../src/features/cc-bridge/api'

// The Radix select needs pointer events that jsdom lacks. A native select keeps the same values and options.
vi.mock('../src/components/ui/select', () => ({
  Select: ({ value, onValueChange, children }: { value: string; onValueChange: (value: string) => void; children: React.ReactNode }) => (
    <select value={value} onChange={event => onValueChange(event.target.value)}><option value="" hidden />{children}</select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: React.ReactNode }) => <option value={value}>{children}</option>,
}))
vi.mock('../src/features/cc-bridge/api', () => ({ spawnSession: vi.fn() }))
vi.mock('../src/hooks/useSessionsApi', () => ({ useSessionsApi: () => ({ listSessions: vi.fn().mockResolvedValue({ sessions: [] }) }) }))
vi.mock('../src/hooks/useProviders', () => ({
  fetchProviderLaunchOptions: vi.fn().mockResolvedValue({ provider: 'claude-code', bedrock_supported: false, fields: [] }),
}))
vi.mock('../src/contexts/ProviderContext', () => ({
  useProviderContext: () => ({
    selectedProviderId: 'claude-code',
    providers: [{ id: 'claude-code', display_name: 'Claude Code', installed: true }, { id: 'codex-cli', display_name: 'Codex CLI', installed: true }],
  }),
}))
const folders = vi.hoisted(() => ({ value: [] as Array<{ path: string; name: string; source: 'team' | 'tracked'; detail?: string }> }))
vi.mock('../src/contexts/ProjectContext', () => ({ useProjectContext: () => ({ knownFolders: folders.value, projects: [], activeProject: null }) }))

const TEAM = '/work/demo/team-checkout'
const TRACKED = '/work/demo/other-app'

function open(onSpawned = vi.fn(), onOpenChange = vi.fn()) {
  render(<MemoryRouter><NewSessionDialog open onOpenChange={onOpenChange} onSpawned={onSpawned} /></MemoryRouter>)
  return { onSpawned, onOpenChange }
}
// Order of the selects: Harness, Start, Folder.
const selects = () => screen.getAllByRole('combobox') as HTMLSelectElement[]

beforeEach(() => {
  vi.clearAllMocks()
  clearOperatorToken()
  folders.value = [{ path: TEAM, name: 'team-checkout', source: 'team', detail: 'F3' }, { path: TRACKED, name: 'other-app', source: 'tracked' }]
  vi.mocked(spawnSession).mockResolvedValue({ tmux_target: 'deck:1.0' } as never)
})
afterEach(() => { cleanup(); clearOperatorToken() })

describe('NewSessionDialog', () => {
  it('has no token field and says that the session is not part of a team', () => {
    open()

    expect(screen.queryByLabelText(/token/i)).toBeNull()
    expect(screen.queryByLabelText(/Director key/i)).toBeNull()
    expect(screen.getByText(/Starts a one-off session that is not part of a team/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Teams' })).toHaveAttribute('href', '/teams')
    expect(screen.getByRole('heading', { name: 'New session' })).toBeInTheDocument()
  })

  it('uses plain names for the start choices', () => {
    open()

    expect(within(selects()[1]).getByRole('option', { name: 'New session' })).toBeInTheDocument()
    expect(within(selects()[1]).getByRole('option', { name: 'New session in a separate copy (worktree)' })).toBeInTheDocument()
    expect(within(selects()[1]).getByRole('option', { name: 'Resume a previous session' })).toBeInTheDocument()
    expect(screen.queryByText('Plain')).toBeNull()
  })

  it('lists team checkouts first and launches without typing a path', async () => {
    setOperatorToken('stored-key')
    const { onSpawned, onOpenChange } = open()

    const folder = selects()[2]
    const options = within(folder).getAllByRole('option').map(option => option.textContent)
    expect(options).toEqual([`${TEAM} (team checkout)`, TRACKED, 'Other folder…'])
    fireEvent.change(folder, { target: { value: TEAM } })
    expect(screen.queryByLabelText('Folder path')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Start session' }))

    await waitFor(() => expect(spawnSession).toHaveBeenCalledTimes(1))
    expect(vi.mocked(spawnSession).mock.calls[0][0]).toMatchObject({ provider: 'claude-code', directory: TEAM, mode: 'plain' })
    expect(vi.mocked(spawnSession).mock.calls[0][1]).toBe('stored-key')
    await waitFor(() => expect(onSpawned).toHaveBeenCalledWith('deck:1.0'))
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('shows the path field only for "Other folder…" or when no folder is known', () => {
    open()
    fireEvent.change(selects()[2], { target: { value: '__other_folder__' } })
    expect(screen.getByLabelText('Folder path')).toBeInTheDocument()
    cleanup()

    folders.value = []
    open()
    expect(screen.getByLabelText('Folder path')).toBeInTheDocument()
  })

  it('asks for the Director key in the shared dialog only when Start needs it, then launches with it', async () => {
    const user = userEvent.setup()
    open()
    fireEvent.change(selects()[2], { target: { value: TEAM } })

    await user.click(screen.getByRole('button', { name: 'Start session' }))
    const dialog = await screen.findByRole('dialog', { name: 'Director key' })
    expect(within(dialog).getByText(/Deck needs the key to start a session\./)).toBeInTheDocument()
    expect(spawnSession).not.toHaveBeenCalled()

    await user.type(within(dialog).getByLabelText(/Director key/), 'new-key{Enter}')

    await waitFor(() => expect(spawnSession).toHaveBeenCalledTimes(1))
    expect(vi.mocked(spawnSession).mock.calls[0][1]).toBe('new-key')
    expect(getOperatorToken()).toBe('new-key')
  })

  it('asks again once after a rejected key and shows no key in an error', async () => {
    const user = userEvent.setup()
    setOperatorToken('old-key')
    vi.mocked(spawnSession).mockRejectedValueOnce(new ApiHttpError('operator_token_invalid', 401))
    open()
    fireEvent.change(selects()[2], { target: { value: TEAM } })

    await user.click(screen.getByRole('button', { name: 'Start session' }))
    const dialog = await screen.findByRole('dialog', { name: 'Director key' })
    expect(within(dialog).getByRole('alert')).toHaveTextContent('The Director key was rejected')
    await user.type(within(dialog).getByLabelText(/Director key/), 'good-key{Enter}')

    await waitFor(() => expect(spawnSession).toHaveBeenCalledTimes(2))
    expect(vi.mocked(spawnSession).mock.calls[1][1]).toBe('good-key')
    expect(document.body.textContent).not.toContain('old-key')
  })

  it('keeps "Skip permission prompts" off by default with its warning', () => {
    open()

    expect(screen.getByRole('checkbox', { name: 'Skip permission prompts' })).not.toBeChecked()
    expect(screen.getByText('Runs tools without asking')).toBeInTheDocument()
  })
})
