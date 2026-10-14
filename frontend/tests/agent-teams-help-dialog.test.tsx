import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AgentTeamsHelpDialog } from '@/features/agent-teams/AgentTeamsHelpDialog'

describe('AgentTeamsHelpDialog', () => {
  it('distinguishes Director protections from the GitHub polling credential', () => {
    render(<AgentTeamsHelpDialog open onOpenChange={() => undefined} />)
    expect(screen.getByText(/The Director key protects roster and watched-repo settings, team launch, autonomy, recovery policy, and Director remedies/)).toHaveTextContent('separate from the GitHub polling token')
    expect(screen.getByText(/The Director key protects/)).toHaveTextContent('stays in this browser tab')
    expect(screen.queryByText(/needed only for protected recovery/)).not.toBeInTheDocument()
  })
  it('links to the promoted autonomy guide', () => {
    render(<AgentTeamsHelpDialog open onOpenChange={() => undefined} />)

    expect(screen.getByRole('link', { name: 'Read the autonomy guide' })).toHaveAttribute(
      'href',
      'https://github.com/adrirubio/claude-deck/blob/master/docs/autonomy.md',
    )
  })
})
