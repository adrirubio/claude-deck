import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AgentActivityBadge } from '@/features/agent-teams/AgentActivityBadge'

describe('AgentActivityBadge', () => {
  it('explains that a session needs a restart before Deck can observe it', () => {
    render(<AgentActivityBadge activity={{ slot_id: 2, state: 'unknown', reason: 'restart_needed_for_observation', observed_at: null }} />)

    const badge = screen.getByLabelText(/Agent activity: Activity unknown\./)
    expect(badge).toHaveAttribute('aria-label', expect.stringContaining('Restart it in resume mode'))
    expect(badge).toHaveAttribute('aria-label', expect.stringContaining('grants no authority'))
    expect(badge).not.toHaveAttribute('aria-label', expect.stringContaining('could not be confirmed'))
  })

  it('keeps the generic text for an unknown reason', () => {
    render(<AgentActivityBadge activity={{ slot_id: 2, state: 'unknown', reason: 'something_new', observed_at: null }} />)

    expect(screen.getByLabelText(/Activity could not be confirmed\./)).toBeInTheDocument()
  })
})
