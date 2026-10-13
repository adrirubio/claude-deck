import { useState } from 'react'
import { Copy, Save, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

/**
 * The only place on the team page with editable team fields. It opens in the
 * page, under the header, when the person selects Edit team. Each action is
 * the existing handler.
 */
export function EditTeamPanel({
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
  if (!open) return null
  // A finished action closes the panel. A failed one keeps it open with the person's text.
  const run = async (action: () => Promise<boolean>) => {
    setBusy(true)
    try {
      if (await action()) onOpenChange(false)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section
      aria-label="Edit team"
      className="space-y-4 rounded-lg border bg-card p-4"
      onKeyDown={(event) => { if (event.key === 'Escape') onOpenChange(false) }}
    >
      <h3 className="text-lg font-semibold">Edit team</h3>
      <div className="grid gap-4">
        <div className="grid gap-2">
          <Label htmlFor="preset-name">Name</Label>
          <Input id="preset-name" autoFocus value={name} onChange={(event) => onNameChange(event.target.value)} />
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
      <div className="flex flex-wrap items-center justify-between gap-2">
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
      </div>
    </section>
  )
}
