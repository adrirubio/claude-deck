import { useState } from 'react'
import { Copy, Save, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

/** The only place on the team page with editable team fields. Each action is the existing handler. */
export function EditTeamDialog({
  open,
  onOpenChange,
  name,
  onNameChange,
  description,
  onDescriptionChange,
  saving,
  onSave,
  onDuplicate,
  onDelete,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  name: string
  onNameChange: (value: string) => void
  description: string
  onDescriptionChange: (value: string) => void
  saving: boolean
  onSave: () => Promise<boolean>
  onDuplicate: () => Promise<boolean>
  onDelete: () => Promise<boolean>
}) {
  const [busy, setBusy] = useState(false)
  // A finished action closes the dialog. A failed one keeps it open with the person's text.
  const run = async (action: () => Promise<boolean>) => {
    setBusy(true)
    try {
      if (await action()) onOpenChange(false)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit team</DialogTitle>
          <DialogDescription>Change the name and description, or copy or delete this team.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="preset-name">Name</Label>
            <Input id="preset-name" value={name} onChange={(event) => onNameChange(event.target.value)} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="preset-description">Description</Label>
            <Textarea
              id="preset-description"
              value={description}
              onChange={(event) => onDescriptionChange(event.target.value)}
            />
          </div>
        </div>
        <DialogFooter className="gap-2 sm:justify-between">
          <div className="flex gap-2">
            <Button variant="outline" disabled={busy} onClick={() => void run(onDuplicate)}>
              <Copy className="mr-2 h-4 w-4" />
              Duplicate
            </Button>
            <Button
              variant="outline"
              disabled={busy}
              className="border-destructive/60 text-destructive hover:bg-destructive/10 hover:text-destructive"
              onClick={() => void run(onDelete)}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Delete
            </Button>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button disabled={busy || saving || !name.trim()} onClick={() => void run(onSave)}>
              <Save className="mr-2 h-4 w-4" />
              Save
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
