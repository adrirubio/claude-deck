import { describe, expect, it } from 'vitest'
import { harnessSummary } from '../src/components/layout/harnessSummary'

const harness = (display_name: string, installed: boolean, version: string | null = null, unavailable_reason: string | null = null) =>
  ({ display_name, installed, version, unavailable_reason })

describe('header harness summary', () => {
  it('shows one count for any number of installed harnesses, with each version in its title', () => {
    const summary = harnessSummary([harness('Claude Code', true, '2.1.0'), harness('Codex', true, '0.50.0'), harness('Pi', true, '1.0.0'),
      harness('OpenCode CLI', true, '2.0.0'), harness('GitHub Copilot CLI', true, '1.0.0'), harness('Muse Code', true, '1.4.8')])
    expect(summary.label).toBe('6 harnesses')
    expect(summary.problem).toBe(false)
    expect(summary.title.split('\n')).toEqual(['Claude Code v2.1.0', 'Codex v0.50.0', 'Pi v1.0.0', 'OpenCode CLI v2.0.0', 'GitHub Copilot CLI v1.0.0', 'Muse Code v1.4.8'])
  })

  it('names a missing harness as a problem', () => {
    const summary = harnessSummary([harness('Claude Code', true, '2.1.0'), harness('Pi', false, null, 'pi not found on PATH')])
    expect(summary.label).toBe('1 of 2 harnesses missing')
    expect(summary.problem).toBe(true)
    expect(summary.title).toContain('Pi missing: pi not found on PATH')
  })

  it('uses the singular for one harness and says installed when there is no version', () => {
    const summary = harnessSummary([harness('Claude Code', true)])
    expect(summary.label).toBe('1 harness')
    expect(summary.title).toBe('Claude Code installed')
  })
})
