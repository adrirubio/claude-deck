import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ProjectProvider, useProjectContext } from '../src/contexts/ProjectContext'
import { ProjectSelector } from '../src/features/projects/ProjectSelector'
import { apiClient } from '../src/lib/api'
import { fetchAgentTeamPresets } from '../src/features/agent-teams/api'

vi.mock('../src/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/lib/api')>()),
  apiClient: vi.fn(),
}))
vi.mock('../src/features/agent-teams/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/features/agent-teams/api')>()),
  fetchAgentTeamPresets: vi.fn(),
}))

const TEAM_FOLDER = '/work/release/harness-live'
const TRACKED_FOLDER = '/work/other/tracked-app'

function trackedProject(isActive: boolean) {
  return { id: 7, name: 'tracked-app', path: TRACKED_FOLDER, is_active: isActive, last_accessed: '', created_at: '' }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(apiClient).mockResolvedValue({ projects: [trackedProject(true)] })
  vi.mocked(fetchAgentTeamPresets).mockResolvedValue({
    presets: [{ id: 1, slots: [{ id: 2, display_name: 'F3 implementer', repo_path: TEAM_FOLDER }] }],
  } as never)
})

function Probe() {
  const { activeProject, error } = useProjectContext()
  const { search } = useLocation()
  return (
    <>
      <output aria-label="active project">{activeProject?.path ?? 'none'}</output>
      <output aria-label="project error">{error ?? 'no error'}</output>
      <output aria-label="search">{search}</output>
    </>
  )
}

function renderAt(path: string, extra?: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ProjectProvider><Probe />{extra}</ProjectProvider>
    </MemoryRouter>,
  )
}

describe('per-page project choice', () => {
  it('reads the project from the page URL, not from the server-wide active flag', async () => {
    renderAt(`/harnesses/claude-code/mcp?project=${encodeURIComponent(TEAM_FOLDER)}`)

    await waitFor(() => expect(screen.getByLabelText('active project')).toHaveTextContent(TEAM_FOLDER))
  })

  it('shows no project and no error for a missing value, even if the server marks one active', async () => {
    renderAt('/harnesses/claude-code/mcp')

    await waitFor(() => expect(apiClient).toHaveBeenCalled())
    expect(screen.getByLabelText('active project')).toHaveTextContent('none')
    expect(screen.getByLabelText('project error')).toHaveTextContent('no error')
  })

  it('shows no project and no error for an unknown value', async () => {
    renderAt(`/harnesses/claude-code/mcp?project=${encodeURIComponent('/not/a/known/folder')}`)

    await waitFor(() => expect(apiClient).toHaveBeenCalled())
    expect(screen.getByLabelText('active project')).toHaveTextContent('none')
    expect(screen.getByLabelText('project error')).toHaveTextContent('no error')
  })

  it('ignores ?project= on pages that are not project-scoped', async () => {
    renderAt(`/sessions?project=${encodeURIComponent(TEAM_FOLDER)}`)

    await waitFor(() => expect(apiClient).toHaveBeenCalled())
    expect(screen.getByLabelText('active project')).toHaveTextContent('none')
  })
})

describe('ProjectSelector', () => {
  it('lists team members\' folders without typing a path and writes the choice to the URL only', async () => {
    const user = userEvent.setup()
    renderAt('/harnesses/claude-code/mcp', <ProjectSelector />)

    const select = await screen.findByLabelText('Project')
    await waitFor(() => expect(screen.getByRole('option', { name: /harness-live · F3 implementer/ })).toBeInTheDocument())
    expect(screen.getByRole('option', { name: /tracked-app/ })).toBeInTheDocument()

    await user.selectOptions(select, TEAM_FOLDER)

    await waitFor(() => expect(screen.getByLabelText('active project')).toHaveTextContent(TEAM_FOLDER))
    expect(screen.getByLabelText('search')).toHaveTextContent(`project=${encodeURIComponent(TEAM_FOLDER)}`)
    const calls = vi.mocked(apiClient).mock.calls.map(([endpoint, options]) => `${(options as { method?: string } | undefined)?.method ?? 'GET'} ${endpoint}`)
    expect(calls.filter(call => call !== 'GET projects')).toEqual([])
  })

  it('keeps the choice of one page out of another page', async () => {
    const first = renderAt(`/harnesses/claude-code/mcp?project=${encodeURIComponent(TEAM_FOLDER)}`)
    await waitFor(() => expect(screen.getByLabelText('active project')).toHaveTextContent(TEAM_FOLDER))
    first.unmount()

    renderAt('/harnesses/claude-code/commands')
    await waitFor(() => expect(apiClient).toHaveBeenCalled())
    expect(screen.getByLabelText('active project')).toHaveTextContent('none')
  })

  it('offers "Add a folder…" as the fallback', async () => {
    const user = userEvent.setup()
    renderAt('/harnesses/claude-code/mcp', <ProjectSelector />)

    await user.selectOptions(await screen.findByLabelText('Project'), 'Add a folder…')

    expect(screen.getByLabelText('Folder path')).toBeInTheDocument()
  })
})
