import { describe, expect, it } from 'vitest'

import backendWorkItem from '../../backend/tests/factory/fixtures/v1/work-item.json'
import backendWorkItems from '../../backend/tests/factory/fixtures/v1/work-items.json'
import frontendWorkItem from './fixtures/factory/v1/work-item.json'
import frontendWorkItems from './fixtures/factory/v1/work-items.json'

// Frozen contract parity: both lane copies must record explicit_assignment.
// A first_enabled_slot value here would restore positional Leader inference.
describe('frozen factory work-item fixture parity', () => {
  it('matches the backend work-item.json copy exactly', () => {
    expect(frontendWorkItem).toEqual(backendWorkItem)
  })

  it('matches the backend work-items.json copy exactly', () => {
    expect(frontendWorkItems).toEqual(backendWorkItems)
  })

  it('records explicit_assignment in both lane copies', () => {
    for (const source of [backendWorkItem, backendWorkItems, frontendWorkItem, frontendWorkItems]) {
      const text = JSON.stringify(source)
      expect(text).toContain('"source":"explicit_assignment"')
      expect(text).not.toContain('first_enabled_slot')
    }
  })
})
