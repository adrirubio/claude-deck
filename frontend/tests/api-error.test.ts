import { expect, it, vi } from 'vitest'
import { apiClient, ApiHttpError } from '../src/lib/api'

it('preserves a structured 409 message and block code', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({
    detail: { message: 'Retry is blocked while a PR is preserved.', block_code: 'retry_blocked_preserved_pr' },
  }), { status: 409, headers: { 'Content-Type': 'application/json' } }))

  await expect(apiClient('/test')).rejects.toMatchObject({
    message: 'Retry is blocked while a PR is preserved.',
    status: 409,
    blockCode: 'retry_blocked_preserved_pr',
  } satisfies Partial<ApiHttpError>)
  fetchMock.mockRestore()
})

it('explains why an active repo identity cannot change', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({
    detail: 'scope_identity_in_use',
  }), { status: 409, headers: { 'Content-Type': 'application/json' } }))

  await expect(apiClient('/test')).rejects.toThrow('This repo has active work.')
  fetchMock.mockRestore()
})
