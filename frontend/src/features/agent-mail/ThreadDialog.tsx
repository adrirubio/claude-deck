import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, MessageSquareReply, RefreshCw, Send } from 'lucide-react'
import { toast } from 'sonner'
import { MarkdownRenderer } from '@/components/shared/MarkdownRenderer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { MODAL_SIZES } from '@/lib/constants'
import type {
  MailMemberResponse,
  MailMessageCreate,
  MailMessageResponse,
  MailThreadResponse,
} from '@/types/agentMail'
import { ackAgentMailMessage, fetchAgentMailThread, sendAgentMailMessage } from './api'
import {
  KIND_LABEL,
  formatDateTime,
  memberName,
  recipientName,
  requestBadgeClass,
  senderName,
  senderTypeLabel,
} from './utils'

interface ThreadDialogProps {
  message: MailMessageResponse | null
  members: MailMemberResponse[]
  open: boolean
  onOpenChange: (open: boolean) => void
  onChanged: () => Promise<void>
}

function MessageBlock({ message, members }: {
  message: MailMessageResponse
  members: MailMemberResponse[]
}) {
  return (
    <div className="rounded-lg border p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Badge variant="outline">{KIND_LABEL[message.kind]}</Badge>
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
      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <span>
          From {senderName(message, members)} to {recipientName(message, members)}
        </span>
        {senderTypeLabel(message) && (
          <Badge variant="outline" className="text-xs">
            {senderTypeLabel(message)}
          </Badge>
        )}
      </div>
      {message.subject && <h4 className="mb-2 text-sm font-semibold">{message.subject}</h4>}
      <MarkdownRenderer content={message.body_markdown} />
    </div>
  )
}

export function ThreadDialog({
  message,
  members,
  open,
  onOpenChange,
  onChanged,
}: ThreadDialogProps) {
  const [thread, setThread] = useState<MailThreadResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [sender, setSender] = useState('')
  const [replyBody, setReplyBody] = useState('')
  const [saving, setSaving] = useState(false)

  const loadThread = useMemo(() => async () => {
    if (!message) return
    setLoading(true)
    try {
      setThread(await fetchAgentMailThread(message.id))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to load thread')
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    queueMicrotask(() => {
      if (cancelled) return
      setReplyBody('')
      setSender('')
      void loadThread()
    })
    return () => {
      cancelled = true
    }
  }, [loadThread, open])

  const root = thread?.root
  const handoffAckMember = root?.kind === 'handoff' && root.request_status === 'pending'
    ? root.recipient_member_id
    : null
  const answerToAck = root?.kind === 'context_request' && root.request_status === 'answered'
    ? thread?.replies.find((reply) => reply.kind === 'answer')
    : null
  const answerAckMember = answerToAck && root?.sender_member_id ? root.sender_member_id : null

  const handleAck = async (messageId: number, memberId: number) => {
    setSaving(true)
    try {
      await ackAgentMailMessage(messageId, memberId)
      await loadThread()
      await onChanged()
      toast.success('Acknowledged')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to acknowledge')
    } finally {
      setSaving(false)
    }
  }

  const handleReply = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!root || !replyBody.trim() || !sender) return
    const senderId = Number(sender)
    const kind = root.kind === 'context_request'
      && root.request_status === 'pending'
      && root.recipient_member_id === senderId
      ? 'answer'
      : 'message'
    const payload: MailMessageCreate = {
      kind,
      sender_member_id: senderId,
      thread_root_id: root.id,
      body_markdown: replyBody,
    }
    setSaving(true)
    try {
      await sendAgentMailMessage(payload)
      setReplyBody('')
      await loadThread()
      await onChanged()
      toast.success(kind === 'answer' ? 'Answer sent' : 'Reply sent')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to send reply')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={MODAL_SIZES.LG}>
        <DialogHeader>
          <DialogTitle>Agent Mail thread</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">
                {root?.subject || message?.subject || `Thread ${message?.id ?? ''}`}
              </p>
              <p className="text-xs text-muted-foreground">
                {thread ? `${thread.replies.length} repl${thread.replies.length === 1 ? 'y' : 'ies'}` : 'Loading'}
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={loadThread} disabled={loading}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Refresh
            </Button>
          </div>

          <ScrollArea className="h-[48vh] pr-4">
            <div className="space-y-3">
              {root && <MessageBlock message={root} members={members} />}
              {thread?.replies.map((reply) => (
                <MessageBlock key={reply.id} message={reply} members={members} />
              ))}
              {!thread && !loading && (
                <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
                  Thread unavailable
                </div>
              )}
            </div>
          </ScrollArea>

          {(handoffAckMember || answerAckMember) && (
            <div className="flex flex-wrap gap-2 rounded-lg border bg-muted/40 p-3">
              {handoffAckMember && root && (
                <Button size="sm" onClick={() => handleAck(root.id, handoffAckMember)} disabled={saving}>
                  <CheckCircle2 className="mr-2 h-4 w-4" />
                  Accept as {memberName(members, handoffAckMember)}
                </Button>
              )}
              {answerAckMember && answerToAck && (
                <Button size="sm" onClick={() => handleAck(answerToAck.id, answerAckMember)} disabled={saving}>
                  <CheckCircle2 className="mr-2 h-4 w-4" />
                  Ack answer as {memberName(members, answerAckMember)}
                </Button>
              )}
            </div>
          )}

          <form className="space-y-3" onSubmit={handleReply}>
            <div className="grid gap-3 md:grid-cols-[220px_1fr]">
              <div className="space-y-2">
                <Label>Reply as</Label>
                <Select value={sender} onValueChange={setSender}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select participant" />
                  </SelectTrigger>
                  <SelectContent>
                    {members.map((member) => (
                      <SelectItem key={member.id} value={String(member.id)}>
                        {member.display_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="agent-mail-thread-reply">Reply</Label>
                <Textarea
                  id="agent-mail-thread-reply"
                  value={replyBody}
                  onChange={(event) => setReplyBody(event.target.value)}
                  rows={3}
                  placeholder="Add a completion note, clarification, or answer."
                />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Close
              </Button>
              <Button type="submit" disabled={!sender || !replyBody.trim() || saving}>
                {root?.kind === 'context_request' && root.request_status === 'pending' ? (
                  <MessageSquareReply className="mr-2 h-4 w-4" />
                ) : (
                  <Send className="mr-2 h-4 w-4" />
                )}
                Send reply
              </Button>
            </DialogFooter>
          </form>
        </div>
      </DialogContent>
    </Dialog>
  )
}
