import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { AgentMailPage } from '@/features/agent-mail/AgentMailPage'
import { ConversationsTab } from '@/features/agent-mail/ConversationsTab'
import { WaitingPanel } from '@/features/agent-mail/WaitingPanel'
import {
  buildConversations,
  buildWaiting,
  chipMatches,
  conversationRecipient,
  membersInTeam,
  scopeConversations,
  teamNames,
  waitingDetail,
} from '@/features/agent-mail/conversations'
import type { MailMemberResponse, MailMessageResponse } from '@/types/agentMail'

vi.mock('@/features/agent-mail/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/agent-mail/api')>()
  return {
    ...actual,
    fetchAgentMailTeam: vi.fn(),
    fetchAgentMailMessages: vi.fn(),
    fetchAgentMailInstallStatus: vi.fn(),
    fetchAgentMailThread: vi.fn(),
  }
})
import { fetchAgentMailInstallStatus, fetchAgentMailMessages, fetchAgentMailTeam, fetchAgentMailThread } from '@/features/agent-mail/api'

function member(id: number, name: string, overrides: Partial<MailMemberResponse> = {}): MailMemberResponse {
  return {
    id, display_name: name, participant_kind: 'team_slot', team_preset_name: 'alpha', status: 'connected',
    unread_count: 0, pending_count: 0, unseen_pending_count: 0, stale_pending_count: 0, can_nudge: false, sessions: [],
    ...overrides,
  } as MailMemberResponse
}

function message(id: number, overrides: Partial<MailMessageResponse> = {}): MailMessageResponse {
  return {
    id, kind: 'message', sender_type: 'member', sender_member_id: 1, sender_name: 'A1', recipient_member_id: 2,
    subject: `Subject ${id}`, body_markdown: `Body ${id}`, is_stale: false,
    created_at: `2026-10-13T08:${String(10 + id).padStart(2, '0')}:00Z`, ...overrides,
  } as MailMessageResponse
}

const MEMBERS = [
  member(1, 'A1 Reviewer'),
  member(2, 'B2 Backend', { status: 'offline', pending_count: 4, stale_pending_count: 4 }),
  member(3, 'repository', { participant_kind: 'repo', team_preset_name: null, status: 'offline', unread_count: 3 }),
  member(4, 'C1 Web', { team_preset_name: 'beta', pending_count: 1 }),
]

describe('buildConversations', () => {
  it('makes one row for each thread, newest first', () => {
    const rows = buildConversations([
      message(1),
      message(2, { thread_root_id: 1, kind: 'answer' }),
      message(3),
    ], MEMBERS)
    expect(rows.map((row) => row.subject)).toEqual(['Subject 3', 'Subject 1'])
    expect(rows[1].lastAt).toBe(message(2).created_at)
    expect(rows[1].count).toBe(2)
  })

  it('collapses Deck notices with the same subject and recipient and counts them', () => {
    const notice = (id: number, overrides: Partial<MailMessageResponse> = {}) =>
      message(id, { sender_type: 'system', sender_member_id: null, subject: 'Release needed: issue #5', ...overrides })
    const rows = buildConversations([
      notice(1), notice(2), notice(3, { is_stale: true }),
      notice(4, { recipient_member_id: 3 }),
      notice(5, { subject: 'Release needed: issue #6' }),
    ], MEMBERS)
    expect(rows).toHaveLength(3)
    const collapsed = rows.find((row) => row.subject === 'Release needed: issue #5' && row.recipientMemberId === 2)
    expect(collapsed).toMatchObject({ count: 3, notice: true, stale: true, lastAt: message(3).created_at })
    expect(collapsed?.message.id).toBe(3)
  })

  it('never collapses messages that agents or the Director wrote', () => {
    const rows = buildConversations([
      message(1, { subject: 'Same' }), message(2, { subject: 'Same' }),
      message(3, { subject: 'Same', sender_type: 'director', sender_member_id: null }),
    ], MEMBERS)
    expect(rows).toHaveLength(3)
    expect(rows.every((row) => !row.notice)).toBe(true)
  })

  it('names the Director as You when the Director is the recipient', () => {
    const toDirector = message(1, { recipient_member_id: null, audience_type: 'operator_global', audience_id: 'global' })
    expect(conversationRecipient(toDirector, MEMBERS)).toBe('You')
    expect(buildConversations([toDirector], MEMBERS)[0].toYou).toBe(true)
    expect(conversationRecipient(message(2, { kind: 'broadcast', recipient_member_id: null }), MEMBERS)).toBe('All members')
    expect(conversationRecipient(message(3), MEMBERS)).toBe('B2 Backend')
    expect(buildConversations([message(3)], MEMBERS)[0].toYou).toBe(false)
  })

  it('takes the team of the recipient, else of the sender, else none', () => {
    const rows = buildConversations([
      message(1, { recipient_member_id: 4 }),
      message(2, { recipient_member_id: 3, sender_member_id: 1 }),
      message(3, { recipient_member_id: null, audience_type: 'operator_global', sender_member_id: 4 }),
      message(4, { recipient_member_id: null, audience_type: 'operator_global', sender_member_id: 3 }),
    ], MEMBERS)
    expect(rows.map((row) => row.team)).toEqual([null, 'beta', 'alpha', 'beta'])
  })

  it('reads the state from the request status only', () => {
    const rows = buildConversations([
      message(1, { request_status: 'pending' }), message(2, { request_status: 'answered' }),
      message(3, { request_status: 'acknowledged' }), message(4),
    ], MEMBERS)
    expect(rows.map((row) => row.state)).toEqual([null, 'Acknowledged', 'Answered', 'Open'])
  })
})

describe('chips and filters', () => {
  const rows = buildConversations([
    message(1, { kind: 'context_request', request_status: 'pending' }),
    message(2, { kind: 'handoff', request_status: 'pending' }),
    message(3, { sender_type: 'system', sender_member_id: null }),
    message(4, { recipient_member_id: null, audience_type: 'operator_global' }),
    message(5, { recipient_member_id: 4 }),
  ], MEMBERS)

  it('matches each chip', () => {
    const subjects = (chip: Parameters<typeof chipMatches>[1]) => rows.filter((row) => chipMatches(row, chip)).map((row) => row.subject)
    expect(subjects('all')).toHaveLength(5)
    expect(subjects('to_you')).toEqual(['Subject 4'])
    expect(subjects('requests')).toEqual(['Subject 1'])
    expect(subjects('handoffs')).toEqual(['Subject 2'])
    expect(subjects('notices')).toEqual(['Subject 3'])
  })

  it('narrows by team, recipient and search', () => {
    const scope = (filter: Partial<Parameters<typeof scopeConversations>[1]>) =>
      scopeConversations(rows, { search: '', team: '', recipientMemberId: null, ...filter }, MEMBERS).map((row) => row.subject)
    expect(scope({ team: 'beta' })).toEqual(['Subject 5'])
    expect(scope({ recipientMemberId: 2 })).toEqual(['Subject 3', 'Subject 2', 'Subject 1'])
    expect(scope({ search: 'body 4' })).toEqual(['Subject 4'])
    expect(scope({ search: 'deck' })).toEqual(['Subject 3'])
  })

  it('lists the teams and keeps the members of one team', () => {
    expect(teamNames(MEMBERS)).toEqual(['alpha', 'beta'])
    expect(membersInTeam(MEMBERS, 'beta').map((entry) => entry.id)).toEqual([4])
    expect(membersInTeam(MEMBERS, '')).toHaveLength(4)
  })
})

describe('buildWaiting', () => {
  it('words each item by what waits and puts warnings first', () => {
    const items = buildWaiting(MEMBERS)
    expect(items.map((item) => item.text)).toEqual([
      '4 messages to B2 Backend are not acknowledged',
      '1 request to C1 Web is waiting for an answer',
      '3 unread messages for repository',
    ])
    expect(items.map((item) => item.warn)).toEqual([true, false, false])
  })

  it('warns for open requests to an offline member and names the online state and team', () => {
    const [item] = buildWaiting([member(9, 'D1', { status: 'offline', pending_count: 1 })])
    expect(item.warn).toBe(true)
    expect(waitingDetail(item)).toBe('D1 is offline · alpha')
    const [other] = buildWaiting([MEMBERS[2]])
    expect(waitingDetail(other)).toBe('repository is offline · not in a team')
    expect(waitingDetail(buildWaiting([MEMBERS[3]])[0])).toBe('C1 Web is connected · beta')
  })

  it('uses the singular for one message and skips members with nothing waiting', () => {
    expect(buildWaiting([MEMBERS[0]])).toEqual([])
    expect(buildWaiting([member(5, 'E1', { stale_pending_count: 1, pending_count: 1 })])[0].text)
      .toBe('1 message to E1 is not acknowledged')
  })
})

describe('WaitingPanel', () => {
  it('lists the items and filters to a recipient', () => {
    const onShow = vi.fn()
    render(<WaitingPanel members={MEMBERS} loading={false} recipientMemberId={null} onShowRecipient={onShow} />)
    expect(screen.getByRole('heading', { name: 'Waiting on someone (3)' })).toBeInTheDocument()
    expect(screen.getByText('4 messages to B2 Backend are not acknowledged')).toBeInTheDocument()
    expect(screen.getByText('B2 Backend is offline · alpha')).toBeInTheDocument()
    expect(screen.getAllByRole('img', { name: 'Needs attention' })).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Show conversations for B2 Backend' }))
    expect(onShow).toHaveBeenCalledWith(2)
  })

  it('says nobody waits when nothing waits', () => {
    render(<WaitingPanel members={[MEMBERS[0]]} loading={false} recipientMemberId={null} onShowRecipient={vi.fn()} />)
    expect(screen.getByRole('heading', { name: 'Waiting on someone (0)' })).toBeInTheDocument()
    expect(screen.getByText('Nobody is waiting on anyone.')).toBeInTheDocument()
  })

  it('shows three items and the rest on request', () => {
    const many = Array.from({ length: 6 }, (_, index) => member(10 + index, `M${index}`, { unread_count: 1 }))
    render(<WaitingPanel members={many} loading={false} recipientMemberId={null} onShowRecipient={vi.fn()} />)
    expect(screen.getAllByRole('listitem')).toHaveLength(3)
    fireEvent.click(screen.getByRole('button', { name: 'Show all 6' }))
    expect(screen.getAllByRole('listitem')).toHaveLength(6)
  })
})

describe('ConversationsTab', () => {
  const messages = [
    message(1, { kind: 'context_request', request_status: 'pending', is_stale: true }),
    message(2, { sender_type: 'system', sender_member_id: null, subject: 'Deck reminder' }),
    message(3, { sender_type: 'system', sender_member_id: null, subject: 'Deck reminder' }),
    message(4, { recipient_member_id: null, audience_type: 'operator_global', request_status: 'answered' }),
  ]

  function renderTab(overrides: Partial<React.ComponentProps<typeof ConversationsTab>> = {}) {
    const props = {
      conversations: buildConversations(messages, MEMBERS), members: MEMBERS, loading: false, search: '', chip: 'all' as const,
      team: '', recipientMemberId: null, messageCount: messages.length,
      onSearchChange: vi.fn(), onChipChange: vi.fn(), onClearRecipient: vi.fn(), onOpenThread: vi.fn(),
      ...overrides,
    }
    return { props, ...render(<ConversationsTab {...props} />) }
  }

  it('shows one compact row for each thread with sender, recipient, state and count', () => {
    renderTab()
    const rows = screen.getAllByTestId('conversation-row')
    expect(rows).toHaveLength(3)
    const notice = within(rows[1])
    expect(notice.getByText('Deck reminder')).toBeInTheDocument()
    expect(notice.getByLabelText('2 notices')).toHaveTextContent('×2')
    expect(rows[1].textContent).toContain('Deck→B2 Backend')
    expect(rows[0].textContent).toContain('A1 Reviewer→You')
    expect(within(rows[0]).getByText('Answered')).toBeInTheDocument()
    expect(within(rows[2]).getByText('Open')).toBeInTheDocument()
    expect(within(rows[2]).getByText('stale')).toBeInTheDocument()
  })

  it('counts each chip within the team and search scope and reports a chip click', () => {
    const { props } = renderTab()
    expect(screen.getByRole('button', { name: 'All (3)' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'To you (1)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Requests (1)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Handoffs (0)' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Deck notices (1)' }))
    expect(props.onChipChange).toHaveBeenCalledWith('notices')
  })

  it('applies the chip and opens the thread of the newest message on a click', () => {
    const { props } = renderTab({ chip: 'notices' })
    const rows = screen.getAllByTestId('conversation-row')
    expect(rows).toHaveLength(1)
    fireEvent.click(rows[0])
    expect(props.onOpenThread).toHaveBeenCalledWith(expect.objectContaining({ id: 3 }))
  })

  it('opens the thread from the keyboard through the subject button', () => {
    const { props } = renderTab({ chip: 'requests' })
    const button = screen.getByRole('button', { name: 'Subject 1' })
    button.focus()
    fireEvent.click(button)
    expect(props.onOpenThread).toHaveBeenCalledTimes(1)
  })

  it('names the recipient filter and clears it', () => {
    const { props } = renderTab({ recipientMemberId: 2 })
    expect(screen.getByText(/Showing conversations for/)).toHaveTextContent('Showing conversations for B2 Backend')
    expect(screen.getAllByTestId('conversation-row')).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: 'Show all' }))
    expect(props.onClearRecipient).toHaveBeenCalled()
  })

  it('says so when nothing matches, and when the list is full', () => {
    renderTab({ search: 'zzz' })
    expect(screen.getByText('No conversations match the current filters.')).toBeInTheDocument()
    renderTab({ messageCount: 100 })
    expect(screen.getByText(/Deck loads the newest 100 threads/)).toBeInTheDocument()
  })

  it('has no compose buttons and no status select in the list', () => {
    renderTab()
    expect(screen.queryByRole('button', { name: /Request context|Create handoff|Broadcast/ })).not.toBeInTheDocument()
    expect(screen.queryByText('All statuses')).not.toBeInTheDocument()
  })
})

describe('Agent Mail page', () => {
  function load(members: MailMemberResponse[], messages: MailMessageResponse[]) {
    vi.mocked(fetchAgentMailTeam).mockResolvedValue({ members })
    vi.mocked(fetchAgentMailMessages).mockResolvedValue(messages)
    vi.mocked(fetchAgentMailInstallStatus).mockResolvedValue({
      claude_code_hooks: [], claude_code_hooks_missing: [], claude_code_mcp_installed: true,
      codex_hooks: [], codex_hooks_missing: [], copilot_hooks: [], copilot_hooks_missing: [],
      opencode_plugin_events: [], opencode_plugin_events_missing: [],
    } as never)
    return render(<MemoryRouter><AgentMailPage /></MemoryRouter>)
  }

  it('leads with the waiting panel and the plain subtitle, and has one Write a message button', async () => {
    load(MEMBERS, [message(1)])
    expect(await screen.findByRole('heading', { name: 'Waiting on someone (3)' })).toBeInTheDocument()
    expect(screen.getByText('Messages between your agents, and between you and them.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Write a message/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /New request/ })).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Conversations' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Requests' })).not.toBeInTheDocument()
  })

  it('opens the compose dialog with the message types inside it', async () => {
    load(MEMBERS, [])
    fireEvent.click(await screen.findByRole('button', { name: /Write a message/ }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Compose Agent Mail')).toBeInTheDocument()
    expect(within(dialog).getAllByRole('combobox')[0]).toHaveTextContent('Message')
  })

  it('shows the conversations of a recipient when the panel button is used', async () => {
    load(MEMBERS, [message(1, { recipient_member_id: 2 }), message(2, { recipient_member_id: 4 })])
    fireEvent.click(await screen.findByRole('button', { name: 'Show conversations for C1 Web' }))
    expect(await screen.findByRole('tab', { name: 'Conversations', selected: true })).toBeInTheDocument()
    const rows = await screen.findAllByTestId('conversation-row')
    expect(rows).toHaveLength(1)
    expect(rows[0].textContent).toContain('Subject 2')
    expect(screen.getByText(/Showing conversations for/)).toBeInTheDocument()
  })

  it('moves focus to the panel when a count in the totals line is used', async () => {
    load(MEMBERS, [])
    const button = await screen.findByRole('button', { name: /4 pending|5 pending|pending\. Go to/ })
    fireEvent.click(button)
    expect(screen.getByRole('region', { name: /Waiting on someone/ })).toHaveFocus()
  })

  it('opens the thread dialog from a row', async () => {
    vi.mocked(fetchAgentMailThread).mockResolvedValue({ root: message(1), replies: [] } as never)
    load(MEMBERS, [message(1)])
    fireEvent.click(await screen.findByRole('tab', { name: 'Conversations' }))
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'Conversations' }))
    const row = await screen.findByTestId('conversation-row')
    fireEvent.click(row)
    await waitFor(() => expect(fetchAgentMailThread).toHaveBeenCalled())
  })
})
