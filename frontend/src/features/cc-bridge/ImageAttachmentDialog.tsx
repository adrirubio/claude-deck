import { AlertTriangle, Image as ImageIcon, Loader2 } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import type { BridgeAttachment } from './types'

interface ImageAttachmentDialogProps {
  open: boolean
  fileName: string
  fileSize: number
  previewUrl: string
  targetLabel: string
  uploading: boolean
  pasting: boolean
  readOnly: boolean
  error: string | null
  attachment: BridgeAttachment | null
  onOpenChange: (open: boolean) => void
  onPaste: (submit: boolean) => void
  onSwitchInteractive: () => void
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

export function ImageAttachmentDialog({
  open,
  fileName,
  fileSize,
  previewUrl,
  targetLabel,
  uploading,
  pasting,
  readOnly,
  error,
  attachment,
  onOpenChange,
  onPaste,
  onSwitchInteractive,
}: ImageAttachmentDialogProps) {
  const canPaste = Boolean(attachment) && !uploading && !pasting && !readOnly

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ImageIcon className="h-5 w-5" />
            Attach image to session
          </DialogTitle>
          <DialogDescription>
            Uploads the image to this Claude Deck host and pastes a file-path prompt into {targetLabel}.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 md:grid-cols-[180px_1fr]">
          <div className="overflow-hidden rounded-md border bg-muted">
            <img src={previewUrl} alt="" className="h-40 w-full object-contain" />
          </div>
          <div className="min-w-0 space-y-3 text-sm">
            <div>
              <p className="font-medium truncate" title={fileName}>{fileName}</p>
              <p className="text-muted-foreground">{formatBytes(fileSize)}</p>
            </div>

            {uploading && (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Uploading image...
              </div>
            )}

            {error && (
              <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-destructive">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <p>{error}</p>
              </div>
            )}

            {attachment && (
              <div>
                <p className="mb-1 text-xs uppercase text-muted-foreground">Prompt to paste</p>
                <p className="max-h-28 overflow-y-auto rounded-md border bg-muted/40 p-2 font-mono text-xs">
                  {attachment.prompt_text}
                </p>
              </div>
            )}

            {readOnly && !error && (
              <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-amber-300">
                This terminal is read-only. Switch to interactive mode before pasting into tmux.
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={pasting}>
            Cancel
          </Button>
          {readOnly && (
            <Button variant="outline" onClick={onSwitchInteractive} disabled={uploading || pasting}>
              Switch to interactive
            </Button>
          )}
          <Button variant="outline" onClick={() => onPaste(false)} disabled={!canPaste}>
            {pasting ? 'Pasting...' : 'Paste reference'}
          </Button>
          <Button onClick={() => onPaste(true)} disabled={!canPaste}>
            {pasting ? 'Pasting...' : 'Paste and submit'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
