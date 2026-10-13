import { execFileSync } from 'node:child_process'
import { expect, test } from '../support/guard'
import { enterDirectorKey, DIRECTOR_KEY } from '../support/director-key'

const OWNER = { 'X-Deck-Session-Token': 'e2e-seed-idle-agent' }
const LEADER = { 'X-Deck-Session-Token': 'e2e-mail-leader' }
const ITEM = 3
const NONCE = 'seed000000000003'

test('@active authenticated Mail plans, decisions, acknowledgements and reports use current sessions', async ({ request }) => {
  const proposed = await request.post('/api/v1/agent-mail/approval-requests', {
    headers: OWNER,
    data: { work_item_id: ITEM, dispatch_nonce: NONCE, summary: 'Check the isolated Mail flow.',
      plan_metadata: { paths: ['docs/import.md'] } },
  })
  expect(proposed.status()).toBe(200)
  const approval = await proposed.json()
  expect(approval.status).toBe('pending')
  expect(approval.owner_member_id).toBe(5)
  expect(approval.leader_member_id).toBe(1)
  const inbox = await request.get('/api/v1/agent-mail/agent/inbox?unread_only=false', { headers: LEADER })
  expect(inbox.status()).toBe(200)
  expect((await inbox.json()).messages.some((message: { id: number }) => message.id === approval.request_message_id)).toBe(true)
  const decision = await request.post('/api/v1/agent-mail/decisions', {
    headers: LEADER,
    data: { work_item_id: ITEM, dispatch_nonce: NONCE, approval_request_id: approval.id,
      decision: 'approved', reason: 'Approved for the isolated instance.' },
  })
  expect(decision.status()).toBe(200)
  const answer = await decision.json()
  expect(answer.sender_member_id).toBe(1)
  expect(answer.decision).toBe('approved')
  const thread = await request.get(`/api/v1/agent-mail/messages/${approval.request_message_id}/thread`, { headers: OWNER })
  expect(thread.status()).toBe(200)
  expect((await thread.json()).replies.some((message: { id: number }) => message.id === answer.id)).toBe(true)
  const acknowledged = await request.post(`/api/v1/agent-mail/messages/${answer.id}/ack`, { headers: OWNER })
  expect(acknowledged.status()).toBe(200)
  for (const status of ['ack_received', 'in_progress']) {
    const report = await request.post('/api/v1/agent-teams/dispatch-status', {
      headers: OWNER, data: { work_item_id: ITEM, status },
    })
    expect(report.status(), status).toBe(200)
    expect((await report.json()).dispatch_status).toBe('dispatched')
  }
})

test('@active Mail reads and actor creation require the correct credential', async ({ request }) => {
  const invalidCredentials: Record<string, string>[] = [{}, { 'X-Deck-Operator-Token': 'wrong-key' },
    { 'X-Deck-Session-Token': 'wrong-session' }]
  for (const headers of invalidCredentials) {
    const read = await request.get('/api/v1/agent-mail/messages', { headers })
    expect(read.status()).toBe(401)
  }
  const read = await request.get('/api/v1/agent-mail/messages', { headers: { 'X-Deck-Operator-Token': DIRECTOR_KEY } })
  expect(read.status()).toBe(200)
  const actor = await request.post('/api/v1/external/agent-mail/actors', {
    headers: { 'X-Deck-Operator-Token': DIRECTOR_KEY },
    data: { actor_key: 'e2e-mail-auth-flow', display_name: 'Mail flow actor' },
  })
  expect(actor.status()).toBe(200)
  const credential = await actor.json()
  const me = await request.get('/api/v1/external/agent-mail/actors/me', {
    headers: { Authorization: `Bearer ${credential.token}` },
  })
  expect(me.status()).toBe(200)
  expect((await me.json()).actor_key).toBe('e2e-mail-auth-flow')
})

test('@active Agent Mail asks for the shared Director key before reading', async ({ page }) => {
  const reads: string[] = []
  page.on('request', request => {
    if (/\/api\/v1\/agent-mail\/(team|messages)/.test(request.url())) reads.push(request.url())
  })
  await page.goto('/agent-mail')
  await expect(page.getByRole('dialog', { name: /Director key/i })).toBeVisible()
  expect(reads).toEqual([])
  await enterDirectorKey(page)
  await expect(page.getByRole('tab', { name: 'Team', exact: true })).toBeVisible()
  await expect.poll(() => reads.length).toBeGreaterThan(0)
})


test('@active native content hooks keep a fixed reminder without Mail credentials', async ({ request, baseURL }) => {
  for (const [path, event] of [['session-start', 'SessionStart'], ['user-prompt-submit', 'UserPromptSubmit']]) {
    const output = execFileSync('/usr/bin/curl', ['-s', '-f', '--connect-timeout', '0.25', '-m', '1',
      '-X', 'POST', `${baseURL}/api/v1/agent-mail/hooks/${path}`,
      '-H', 'Content-Type: application/json', '--data-binary', '@-'], {
      input: JSON.stringify({ session_id: 'e2e-native-hook', cwd: '/synthetic' }), encoding: 'utf8',
    })
    expect(JSON.parse(output)).toEqual({ hookSpecificOutput: {
      hookEventName: event, additionalContext: 'Check your Deck inbox.',
    } })
  }
  const context = await request.post('/api/v1/agent-mail/hooks/session-start', {
    headers: OWNER, data: { session_id: 'e2e-native-hook', cwd: '/synthetic', team_slot_id: 1 },
  })
  expect(context.status()).toBe(200)
  expect((await context.json()).hookSpecificOutput.additionalContext).toContain('F2 Frontend')
  for (const path of ['session-end', 'post-tool-use']) {
    const response = await request.post(`/api/v1/agent-mail/hooks/${path}`, { data: {} })
    expect(response.status()).toBe(200)
    expect(await response.json()).toEqual({})
  }
})
