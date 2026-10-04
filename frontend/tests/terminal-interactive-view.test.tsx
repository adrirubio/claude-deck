import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TerminalView } from '@/features/cc-bridge/TerminalView'
import { getOperatorToken, setOperatorToken } from '@/features/agent-teams/operatorAuth'
import { ApiHttpError } from '@/lib/api'

const terminal = vi.hoisted(() => ({
  attach: vi.fn(),
  detach: vi.fn(),
  focusTerminal: vi.fn(),
  setReadOnly: vi.fn(),
}))

vi.mock('@/features/cc-bridge/useTerminal', () => ({
  useTerminal: () => ({
    connected: false,
    readOnly: true,
    ...terminal,
  }),
}))

beforeEach(() => {
  terminal.attach.mockReset().mockResolvedValue(undefined)
  terminal.detach.mockReset()
  terminal.focusTerminal.mockReset()
  terminal.setReadOnly.mockReset().mockResolvedValue(undefined)
})

describe('interactive terminal entry', () => {
  it('keeps delivery context locked read-only even with a stored operator credential', async () => {
    const user = userEvent.setup()
    setOperatorToken('test-stored')
    render(<TerminalView target="fixture:0.0" forceReadOnly />)
    const interactive = screen.getByRole('button', { name: 'Interactive' })
    expect(interactive).toBeDisabled()
    await user.click(interactive)
    expect(terminal.setReadOnly).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('keeps read-only access while asking for a masked operator token', async () => {
    const user = userEvent.setup()
    render(<TerminalView target="deck:0.0" />)

    await user.click(screen.getByRole('button', { name: 'Interactive' }))
    expect(screen.getByLabelText('Operator token')).toHaveAttribute('type', 'password')
    expect(terminal.setReadOnly).not.toHaveBeenCalled()

    await user.type(screen.getByLabelText('Operator token'), 'operator-secret')
    await user.click(screen.getByRole('button', { name: 'Enable interactive' }))
    await waitFor(() => expect(terminal.setReadOnly).toHaveBeenCalledWith(false, 'operator-secret'))
    expect(getOperatorToken()).toBe('operator-secret')
  })

  it('clears a rejected stored token and prompts for a replacement', async () => {
    const user = userEvent.setup()
    setOperatorToken('stale-secret')
    terminal.setReadOnly.mockRejectedValueOnce(new ApiHttpError('operator_token_invalid', 401))
    render(<TerminalView target="deck:0.0" />)

    await user.click(screen.getByRole('button', { name: 'Interactive' }))
    await waitFor(() => expect(getOperatorToken()).toBeNull())
    expect(screen.getByText(/operator token was rejected/i)).toBeInTheDocument()
    expect(screen.getByLabelText('Operator token')).toHaveValue('')
  })
})
