import { Eye, Handshake, HelpCircle, Megaphone, MessageSquare, Search } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type {
  MailMemberResponse,
  MailMessageKind,
  MailMessageResponse,
  MailRequestStatus,
} from '@/types/agentMail'
import {
  KIND_LABEL,
  formatDateTime,
  messageSummary,
  recipientName,
  requestBadgeClass,
  senderName,
  senderTypeLabel,
} from './utils'

export type RequestKindFilter = 'all' | Exclude<MailMessageKind, 'answer'>
export type RequestStatusFilter = 'all' | MailRequestStatus | 'none'

interface RequestsTabProps {
  messages: MailMessageResponse[]
  members: MailMemberResponse[]
  loading: boolean
  search: string
  kindFilter: RequestKindFilter
  statusFilter: RequestStatusFilter
  onSearchChange: (value: string) => void
  onKindFilterChange: (value: RequestKindFilter) => void
  onStatusFilterChange: (value: RequestStatusFilter) => void
  onOpenThread: (message: MailMessageResponse) => void
  onCompose: (kind: Exclude<MailMessageKind, 'answer'>) => void
}

function KindIcon({ kind }: { kind: MailMessageKind }) {
  if (kind === 'context_request') return <HelpCircle className="h-4 w-4" />
  if (kind === 'handoff') return <Handshake className="h-4 w-4" />
  if (kind === 'broadcast') return <Megaphone className="h-4 w-4" />
  return <MessageSquare className="h-4 w-4" />
}

export function RequestsTab({
  messages,
  members,
  loading,
  search,
  kindFilter,
  statusFilter,
  onSearchChange,
  onKindFilterChange,
  onStatusFilterChange,
  onOpenThread,
  onCompose,
}: RequestsTabProps) {
  const normalizedSearch = search.trim().toLowerCase()
  const filtered = messages.filter((message) => {
    const matchesKind = kindFilter === 'all' || message.kind === kindFilter
    const matchesStatus = statusFilter === 'all'
      || (statusFilter === 'none' ? !message.request_status : message.request_status === statusFilter)
    const haystack = [
      KIND_LABEL[message.kind],
      message.subject ?? '',
      message.body_markdown,
      senderName(message, members),
      recipientName(message, members),
    ].join(' ').toLowerCase()
    return matchesKind && matchesStatus && (!normalizedSearch || haystack.includes(normalizedSearch))
  })

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search subjects, senders, recipients, body"
            className="pl-9"
          />
        </div>
        <Select value={kindFilter} onValueChange={(value) => onKindFilterChange(value as RequestKindFilter)}>
          <SelectTrigger className="w-full lg:w-[190px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All kinds</SelectItem>
            <SelectItem value="context_request">Context requests</SelectItem>
            <SelectItem value="handoff">Handoffs</SelectItem>
            <SelectItem value="message">Messages</SelectItem>
            <SelectItem value="broadcast">Broadcasts</SelectItem>
          </SelectContent>
        </Select>
        <Select value={statusFilter} onValueChange={(value) => onStatusFilterChange(value as RequestStatusFilter)}>
          <SelectTrigger className="w-full lg:w-[170px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
            <SelectItem value="answered">Answered</SelectItem>
            <SelectItem value="acknowledged">Acknowledged</SelectItem>
            <SelectItem value="none">No status</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => onCompose('context_request')}>
          <HelpCircle className="mr-2 h-4 w-4" />
          Request context
        </Button>
        <Button size="sm" variant="outline" onClick={() => onCompose('handoff')}>
          <Handshake className="mr-2 h-4 w-4" />
          Create handoff
        </Button>
        <Button size="sm" variant="outline" onClick={() => onCompose('broadcast')}>
          <Megaphone className="mr-2 h-4 w-4" />
          Broadcast
        </Button>
      </div>

      <div className="space-y-3">
        {filtered.map((message) => (
          <Card key={message.id} className="rounded-lg">
            <CardContent className="p-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline" className="gap-1">
                      <KindIcon kind={message.kind} />
                      {KIND_LABEL[message.kind]}
                    </Badge>
                    {message.request_status && (
                      <Badge variant="outline" className={requestBadgeClass(message.request_status)}>
                        {message.request_status}
                      </Badge>
                    )}
                    {message.is_stale && (
                      <Badge variant="outline" className="border-amber-300 text-amber-700">
                        stale
                      </Badge>
                    )}
                    <span className="text-xs text-muted-foreground">{formatDateTime(message.created_at)}</span>
                  </div>
                  <div>
                    <h3 className="truncate text-base font-semibold">
                      {message.subject || `${KIND_LABEL[message.kind]} ${message.id}`}
                    </h3>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                      <span>
                        {senderName(message, members)} to {recipientName(message, members)}
                      </span>
                      {senderTypeLabel(message) && (
                        <Badge variant="outline" className="text-xs">
                          {senderTypeLabel(message)}
                        </Badge>
                      )}
                    </div>
                  </div>
                  <p className="text-sm leading-6 text-muted-foreground">{messageSummary(message)}</p>
                </div>
                <Button size="sm" variant="outline" onClick={() => onOpenThread(message)}>
                  <Eye className="mr-2 h-4 w-4" />
                  Thread
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}

        {filtered.length === 0 && (
          <Card className="rounded-lg border-dashed">
            <CardContent className="py-12 text-center text-sm text-muted-foreground">
              {loading ? 'Loading messages...' : 'No messages match the current filters.'}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
