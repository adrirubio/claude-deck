import { useEffect, useState } from 'react'
import { Save } from 'lucide-react'
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
import { Textarea } from '@/components/ui/textarea'
import { MODAL_SIZES } from '@/lib/constants'
import type { MailMemberResponse, MailMemberUpdate } from '@/types/agentMail'

interface MemberEditDialogProps {
  member: MailMemberResponse | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSave: (memberId: number, update: MailMemberUpdate) => Promise<void>
}

export function MemberEditDialog({ member, open, onOpenChange, onSave }: MemberEditDialogProps) {
  const [displayName, setDisplayName] = useState('')
  const [role, setRole] = useState('')
  const [charter, setCharter] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!member || !open) return
    let cancelled = false
    queueMicrotask(() => {
      if (cancelled) return
      setDisplayName(member.display_name)
      setRole(member.role ?? '')
      setCharter(member.charter ?? '')
    })
    return () => {
      cancelled = true
    }
  }, [member, open])

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!member) return
    setSaving(true)
    try {
      await onSave(member.id, {
        display_name: displayName,
        role: role || null,
        charter: charter || null,
      })
      onOpenChange(false)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={MODAL_SIZES.SM}>
        <DialogHeader>
          <DialogTitle>Edit team member</DialogTitle>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="agent-mail-display-name">Display name</Label>
            <Input
              id="agent-mail-display-name"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="agent-mail-role">Role</Label>
            <Input
              id="agent-mail-role"
              value={role}
              onChange={(event) => setRole(event.target.value)}
              placeholder="backend expert, UI agent, release coordinator"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="agent-mail-charter">Charter</Label>
            <Textarea
              id="agent-mail-charter"
              value={charter}
              onChange={(event) => setCharter(event.target.value)}
              placeholder="What this agent should own or be asked about."
              rows={4}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              <Save className="mr-2 h-4 w-4" />
              {saving ? 'Saving...' : 'Save'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
