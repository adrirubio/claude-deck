import { ChevronDown, ChevronRight, Search } from 'lucide-react'
import { useState } from 'react'
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
import type { MailMemberResponse, MailMemberStatus, MailMessageKind } from '@/types/agentMail'
import { RosterRow } from './RosterRow'
import { groupRoster } from './roster'

export type TeamStatusFilter = 'all' | MailMemberStatus

interface TeamTabProps {
  members: MailMemberResponse[]
  loading: boolean
  repoSearch: string
  statusFilter: TeamStatusFilter
  onRepoSearchChange: (value: string) => void
  onStatusFilterChange: (value: TeamStatusFilter) => void
  onEdit: (member: MailMemberResponse) => void
  onCompose: (kind: Exclude<MailMessageKind, 'answer' | 'broadcast'>, member: MailMemberResponse) => void
  onQueueInboxCheck: (member: MailMemberResponse) => void
  nudgingMemberId?: number | null
}

export function TeamTab({
  members,
  loading,
  repoSearch,
  statusFilter,
  onRepoSearchChange,
  onStatusFilterChange,
  onEdit,
  onCompose,
  onQueueInboxCheck,
  nudgingMemberId,
}: TeamTabProps) {
  const [otherOpen, setOtherOpen] = useState(false)
  const normalizedSearch = repoSearch.trim().toLowerCase()
  const filtered = members.filter((member) => {
    const matchesStatus = statusFilter === 'all' || member.status === statusFilter
    const haystack = [
      member.display_name,
      member.role ?? '',
      member.charter ?? '',
      member.repo_name,
      member.repo_path,
      member.team_preset_name ?? '',
      member.team_slot_name ?? '',
      member.participant_kind,
    ].join(' ').toLowerCase()
    return matchesStatus && (!normalizedSearch || haystack.includes(normalizedSearch))
  })

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            value={repoSearch}
            onChange={(event) => onRepoSearchChange(event.target.value)}
            placeholder="Search repos, roles, charters"
            className="pl-9"
          />
        </div>
        <Select value={statusFilter} onValueChange={(value) => onStatusFilterChange(value as TeamStatusFilter)}>
          <SelectTrigger className="w-full md:w-[180px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="connected">Connected</SelectItem>
            <SelectItem value="observed">Observed only</SelectItem>
            <SelectItem value="offline">Offline</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {filtered.length > 0 ? (
        <div className="space-y-4">
          {groupRoster(filtered).map((group) => {
            const collapsed = group.isOther && !otherOpen
            return (
              <section key={group.key} aria-label={group.label} className="overflow-hidden rounded-lg border">
                <div className="flex items-center justify-between gap-3 bg-muted/50 px-3 py-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {group.label}{group.isOther ? ` · ${group.members.length}` : ''}
                  </h3>
                  {group.isOther && (
                    <Button size="sm" variant="ghost" aria-expanded={!collapsed} onClick={() => setOtherOpen((value) => !value)}>
                      {collapsed ? <ChevronRight aria-hidden="true" className="mr-1 h-4 w-4" /> : <ChevronDown aria-hidden="true" className="mr-1 h-4 w-4" />}
                      {collapsed ? 'Show' : 'Hide'}
                    </Button>
                  )}
                </div>
                {!collapsed && (
                  <ul>
                    {group.members.map((member) => (
                      <RosterRow
                        key={member.id}
                        member={member}
                        onEdit={onEdit}
                        onCompose={onCompose}
                        onQueueInboxCheck={onQueueInboxCheck}
                        nudging={nudgingMemberId === member.id}
                      />
                    ))}
                  </ul>
                )}
              </section>
            )
          })}
        </div>
      ) : (
        <Card className="rounded-lg border-dashed">
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            {loading ? 'Loading participants...' : 'No participants match the current filters.'}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
