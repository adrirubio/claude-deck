import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Send } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { MODAL_SIZES } from '@/lib/constants'
import type { MailMemberResponse, MailMessageCreate, MailMessageKind } from '@/types/agentMail'
import { splitLines } from './utils'

export interface ComposePreset {
  kind?: Exclude<MailMessageKind, 'answer'>
  recipient_member_id?: number | null
  subject?: string
}

interface ComposeDialogProps {
  open: boolean
  members: MailMemberResponse[]
  preset: ComposePreset | null
  onOpenChange: (open: boolean) => void
  onSend: (message: MailMessageCreate) => Promise<void>
}

const composeKinds: Array<Exclude<MailMessageKind, 'answer'>> = [
  'message',
  'broadcast',
  'context_request',
  'handoff',
]

function recipientLabel(member: MailMemberResponse): string {
  const role = member.role ? `, ${member.role}` : ''
  const team = member.team_preset_name ? `, ${member.team_preset_name}` : ''
  return `${member.display_name} (${member.repo_name}${role}${team}) - ${deliveryLabel(member)}`
}

function deliveryLabel(member: MailMemberResponse): string {
  if (member.status === 'offline' || member.wake_state === 'offline') return 'offline, stored only'
  if (member.wake_state === 'wakeable') {
    const methodText = member.wake_methods?.length ? ` via ${member.wake_methods.join(', ')}` : ''
    return `wakeable${methodText}`
  }
  if (member.wake_state === 'delivered_waiting') return 'not wakeable'
  if (member.status === 'observed') return 'observed only'
  return member.status
}

function deliveryRank(member: MailMemberResponse): number {
  if (member.status === 'offline' || member.wake_state === 'offline') return 4
  if (member.wake_state === 'wakeable') return 0
  if (member.status === 'connected') return 1
  if (member.status === 'observed') return 2
  return 3
}

function deliveryWarning(member: MailMemberResponse, kind: Exclude<MailMessageKind, 'answer'>): string | null {
  const expectsAction = kind === 'context_request' || kind === 'handoff'
  if (member.status === 'offline' || member.wake_state === 'offline') {
    return expectsAction
      ? `${member.display_name} is offline. This ${kind === 'handoff' ? 'handoff' : 'request'} will be stored, but no live agent can be woken to respond until that participant checks in again.`
      : `${member.display_name} is offline. This message will be stored for later; Claude Deck cannot wake a live session.`
  }
  if (member.wake_state === 'delivered_waiting') {
    return expectsAction
      ? `${member.display_name} is not wakeable. The ${kind === 'handoff' ? 'handoff' : 'request'} will be stored, but the agent may not see it until it checks Agent Mail or reaches a hook boundary.`
      : `${member.display_name} is not wakeable. The message will be stored, but Claude Deck cannot nudge this session.`
  }
  return null
}

export function ComposeDialog({ open, members, preset, onOpenChange, onSend }: ComposeDialogProps) {
  const [kind, setKind] = useState<Exclude<MailMessageKind, 'answer'>>('message')
  const [recipient, setRecipient] = useState('')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [whyNeeded, setWhyNeeded] = useState('')
  const [files, setFiles] = useState('')
  const [nextSteps, setNextSteps] = useState('')
  const [sending, setSending] = useState(false)
  const sortedMembers = useMemo(
    () => [...members].sort((left, right) => {
      const rankDelta = deliveryRank(left) - deliveryRank(right)
      if (rankDelta !== 0) return rankDelta
      return left.display_name.localeCompare(right.display_name)
    }),
    [members],
  )

  useEffect(() => {
    if (!open) return
    let cancelled = false
    queueMicrotask(() => {
      if (cancelled) return
      setKind(preset?.kind ?? 'message')
      setRecipient(preset?.recipient_member_id ? String(preset.recipient_member_id) : '')
      setSubject(preset?.subject ?? '')
      setBody('')
      setWhyNeeded('')
      setFiles('')
      setNextSteps('')
    })
    return () => {
      cancelled = true
    }
  }, [open, preset])

  const needsRecipient = kind !== 'broadcast'
  const selectedMember = recipient
    ? members.find((member) => member.id === Number(recipient)) ?? null
    : null
  const selectedDeliveryWarning = selectedMember ? deliveryWarning(selectedMember, kind) : null
  const canSend = useMemo(() => {
    if (!body.trim()) return false
    if (needsRecipient && !recipient) return false
    return true
  }, [body, needsRecipient, recipient])

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!canSend) return

    const payload: Record<string, unknown> = {}
    if (kind === 'context_request') {
      payload.why_needed = whyNeeded
      payload.files_or_symbols = splitLines(files)
    }
    if (kind === 'handoff') {
      payload.files = splitLines(files)
      payload.next_steps = splitLines(nextSteps)
    }

    setSending(true)
    try {
      await onSend({
        kind,
        recipient_member_id: needsRecipient ? Number(recipient) : null,
        subject: subject || null,
        body_markdown: body,
        payload: Object.keys(payload).length ? payload : null,
      })
      onOpenChange(false)
    } finally {
      setSending(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={MODAL_SIZES.MD}>
        <DialogHeader>
          <DialogTitle>Compose Agent Mail</DialogTitle>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label>Type</Label>
              <Select value={kind} onValueChange={(value) => setKind(value as Exclude<MailMessageKind, 'answer'>)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {composeKinds.map((option) => (
                    <SelectItem key={option} value={option}>
                      {option === 'context_request' ? 'Context request' : option === 'handoff' ? 'Handoff' : option === 'broadcast' ? 'Broadcast' : 'Message'}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {needsRecipient && (
              <div className="space-y-2">
                <Label>Recipient</Label>
                <Select value={recipient} onValueChange={setRecipient}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select a participant" />
                  </SelectTrigger>
                  <SelectContent>
                    {sortedMembers.map((member) => (
                      <SelectItem key={member.id} value={String(member.id)}>
                        {recipientLabel(member)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>

          {needsRecipient && selectedDeliveryWarning && (
            <Alert className="border-amber-300 bg-amber-50/60 dark:bg-amber-950/20">
              <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-300" />
              <AlertDescription>{selectedDeliveryWarning}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-2">
            <Label htmlFor="agent-mail-subject">Subject</Label>
            <Input
              id="agent-mail-subject"
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              placeholder={kind === 'handoff' ? 'Handoff: auth retry work' : 'Short routing context'}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="agent-mail-body">Body</Label>
            <Textarea
              id="agent-mail-body"
              value={body}
              onChange={(event) => setBody(event.target.value)}
              placeholder="Use concrete context, expected output, and any relevant files."
              rows={7}
              required
            />
          </div>

          {kind === 'context_request' && (
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="agent-mail-why">Why needed</Label>
                <Textarea
                  id="agent-mail-why"
                  value={whyNeeded}
                  onChange={(event) => setWhyNeeded(event.target.value)}
                  rows={3}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="agent-mail-symbols">Files or symbols</Label>
                <Textarea
                  id="agent-mail-symbols"
                  value={files}
                  onChange={(event) => setFiles(event.target.value)}
                  placeholder="One per line"
                  rows={3}
                />
              </div>
            </div>
          )}

          {kind === 'handoff' && (
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="agent-mail-files">Files touched</Label>
                <Textarea
                  id="agent-mail-files"
                  value={files}
                  onChange={(event) => setFiles(event.target.value)}
                  placeholder="One per line"
                  rows={3}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="agent-mail-next">Next steps</Label>
                <Textarea
                  id="agent-mail-next"
                  value={nextSteps}
                  onChange={(event) => setNextSteps(event.target.value)}
                  placeholder="One per line"
                  rows={3}
                />
              </div>
            </div>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!canSend || sending}>
              <Send className="mr-2 h-4 w-4" />
              {sending ? 'Sending...' : 'Send'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
