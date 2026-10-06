import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import backendLegacyWorkItem from '../../backend/tests/factory/fixtures/v1/work-item.json'
import backendLegacyWorkItems from '../../backend/tests/factory/fixtures/v1/work-items.json'
import backendP04WorkItem from '../../backend/tests/factory/fixtures/v1-p04/work-item.json'
import backendP04WorkItems from '../../backend/tests/factory/fixtures/v1-p04/work-items.json'
import backendP04Manifest from '../../backend/tests/factory/fixtures/v1-p04/manifest.json'
import frontendLegacyWorkItem from './fixtures/factory/v1/work-item.json'
import frontendLegacyWorkItems from './fixtures/factory/v1/work-items.json'
import frontendP04WorkItem from './fixtures/factory/v1-p04/work-item.json'
import frontendP04WorkItems from './fixtures/factory/v1-p04/work-items.json'
import frontendP04Manifest from './fixtures/factory/v1-p04/manifest.json'

// Frozen contract parity across lanes and versions. The P01 v1 copies stay
// immutable history; the P04 v1-p04 copies carry the explicit Leader contract.
describe('frozen factory fixture parity and provenance', () => {
  it('keeps the P01 v1 copies identical across lanes', () => {
    expect(frontendLegacyWorkItem).toEqual(backendLegacyWorkItem)
    expect(frontendLegacyWorkItems).toEqual(backendLegacyWorkItems)
    const legacyText = JSON.stringify(frontendLegacyWorkItem)
    expect(legacyText).toContain('first_enabled_slot')
    expect(legacyText).not.toContain('explicit_assignment')
  })

  it('keeps the P04 copies identical across lanes', () => {
    expect(frontendP04WorkItem).toEqual(backendP04WorkItem)
    expect(frontendP04WorkItems).toEqual(backendP04WorkItems)
    const p04Text = JSON.stringify(frontendP04WorkItem)
    expect(p04Text).toContain('explicit_assignment')
    expect(p04Text).not.toContain('first_enabled_slot')
  })

  it('verifies every P04 manifest artifact hash in both lanes', () => {
    for (const [directory, manifest] of [
      [resolve(__dirname, '../../backend/tests/factory/fixtures/v1-p04'), backendP04Manifest],
      [resolve(__dirname, './fixtures/factory/v1-p04'), frontendP04Manifest],
    ] as Array<[string, typeof backendP04Manifest]>) {
      expect(manifest.contract_version).toBe('p04')
      expect(manifest.p01_source_sha).toBe('eb31749bcae8f456d6df6709273afd5921d094ad')
      for (const [name, digest] of Object.entries(manifest.artifact_sha256)) {
        const actual = createHash('sha256').update(readFileSync(resolve(directory, name))).digest('hex')
        expect(actual).toBe(digest)
      }
    }
  })
})
