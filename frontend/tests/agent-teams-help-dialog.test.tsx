import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AgentTeamsHelpDialog } from '@/features/agent-teams/AgentTeamsHelpDialog'

describe('AgentTeamsHelpDialog', () => {
  it('links to the promoted autonomy guide', () => {
    render(<AgentTeamsHelpDialog open onOpenChange={() => undefined} />)

    expect(screen.getByRole('link', { name: 'Read the autonomy operator guide' })).toHaveAttribute(
      'href',
      'https://github.com/adrirubio/claude-deck/blob/master/docs/autonomy.md',
    )
  })
})
