import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Monitor, Maximize2, Minimize2, X } from 'lucide-react'
import { toast } from 'sonner'
import { useTerminal } from './useTerminal'
import { ImageAttachmentDialog } from './ImageAttachmentDialog'
import { pasteBridgeAttachment, uploadBridgeAttachment } from './api'
import { Button } from '@/components/ui/button'
import { getTeamSlotColorClasses, getTeamSlotTerminalTheme } from '@/lib/agentTeamColors'
import { getInstanceAccentClasses } from '@/lib/instanceAccent'
import { cn } from '@/lib/utils'
import type { BridgeAttachment, CCSession } from './types'
import type { InstanceIdentity } from '@/types/status'

interface TerminalViewProps {
  target: string | null
  fullscreen?: boolean
  inLanes?: boolean
  onToggleFullscreen?: () => void
  onClose?: () => void
  instance?: InstanceIdentity | null
  session?: CCSession | null
}

interface ImageAttachmentState {
  fileName: string
  fileSize: number
  previewUrl: string
  attachment: BridgeAttachment | null
  uploading: boolean
  pasting: boolean
  error: string | null
}

function firstImageFile(files: FileList | File[] | null | undefined): File | null {
  if (!files) return null
  return Array.from(files).find((file) => file.type.startsWith('image/')) ?? null
}

function hasDraggedImage(dataTransfer: DataTransfer): boolean {
  const items = Array.from(dataTransfer.items)
  if (items.length > 0) {
    return items.some((item) => item.kind === 'file' && item.type.startsWith('image/'))
  }
  return Boolean(firstImageFile(dataTransfer.files))
}

function imageFromClipboard(event: React.ClipboardEvent<HTMLDivElement>): File | null {
  const items = Array.from(event.clipboardData.items)
  for (const item of items) {
    if (item.kind === 'file' && item.type.startsWith('image/')) {
      return item.getAsFile()
    }
  }
  return null
}

export function TerminalView({ target, fullscreen, inLanes, onToggleFullscreen, onClose, instance, session }: TerminalViewProps) {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [draggingImage, setDraggingImage] = useState(false)
  const [imageAttachment, setImageAttachment] = useState<ImageAttachmentState | null>(null)
  const slotColor = session?.team_slot_color
  const terminalTheme = useMemo(() => getTeamSlotTerminalTheme(slotColor), [slotColor])
  const { connected, readOnly, setReadOnly, attach, detach } = useTerminal(containerRef, wrapperRef, terminalTheme)
  const accentClasses = getInstanceAccentClasses(instance?.accent)
  const colorClasses = getTeamSlotColorClasses(slotColor)
  const modeLabel = readOnly ? 'Read-only' : 'Interactive'
  const sessionLabel = session?.team_slot_name || session?.session_name || target

  useEffect(() => {
    if (target) {
      attach(target)
    } else {
      detach()
    }
  }, [target, attach, detach])

  useEffect(() => {
    const previewUrl = imageAttachment?.previewUrl
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }
  }, [imageAttachment?.previewUrl])

  const closeImageAttachment = useCallback(() => {
    setImageAttachment(null)
  }, [])

  const attachImageFile = useCallback(async (file: File) => {
    if (!target) return
    const previewUrl = URL.createObjectURL(file)
    setImageAttachment({
      fileName: file.name || 'clipboard-image.png',
      fileSize: file.size,
      previewUrl,
      attachment: null,
      uploading: true,
      pasting: false,
      error: null,
    })

    try {
      const attachment = await uploadBridgeAttachment(target, file)
      setImageAttachment((current) => current?.previewUrl === previewUrl
        ? { ...current, attachment, uploading: false }
        : current)
    } catch (error) {
      setImageAttachment((current) => current?.previewUrl === previewUrl
        ? {
          ...current,
          uploading: false,
          error: error instanceof Error ? error.message : 'Failed to upload image',
        }
        : current)
    }
  }, [target])

  const handlePaste = useCallback((event: React.ClipboardEvent<HTMLDivElement>) => {
    if (!target) return
    const file = imageFromClipboard(event)
    if (!file) return
    event.preventDefault()
    void attachImageFile(file)
  }, [attachImageFile, target])

  const handleDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    if (!target || !hasDraggedImage(event.dataTransfer)) return
    event.preventDefault()
    setDraggingImage(true)
  }, [target])

  const handleDragLeave = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    const related = event.relatedTarget
    if (related instanceof Node && event.currentTarget.contains(related)) return
    setDraggingImage(false)
  }, [])

  const handleDrop = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    if (!target) return
    const file = firstImageFile(event.dataTransfer.files)
    if (!file) return
    event.preventDefault()
    setDraggingImage(false)
    void attachImageFile(file)
  }, [attachImageFile, target])

  const handleAttachmentPaste = useCallback(async (submit: boolean) => {
    if (!target || !imageAttachment?.attachment || readOnly) return
    const attachment = imageAttachment.attachment
    setImageAttachment((current) => current ? { ...current, pasting: true, error: null } : current)
    try {
      await pasteBridgeAttachment(target, attachment.id, { submit, require_interactive_relay: true })
      toast.success(submit ? 'Image prompt pasted and submitted' : 'Image prompt pasted')
      closeImageAttachment()
    } catch (error) {
      setImageAttachment((current) => current
        ? {
          ...current,
          pasting: false,
          error: error instanceof Error ? error.message : 'Failed to paste image prompt',
        }
        : current)
    }
  }, [closeImageAttachment, imageAttachment?.attachment, readOnly, target])

  return (
    <div className="flex flex-col h-full">
      <div
        ref={wrapperRef}
        className={cn('relative flex-1 overflow-hidden', colorClasses.terminalWrapper)}
        onPaste={handlePaste}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {!target && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground bg-background">
            <Monitor className="h-12 w-12 mb-3" />
            <p className="text-sm">Select a session to attach</p>
          </div>
        )}
        <div
          ref={containerRef}
          className={cn(
            'absolute inset-0',
            !target && 'invisible'
          )}
        />
        {draggingImage && (
          <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center border-2 border-dashed border-primary bg-background/80 text-sm font-medium text-foreground">
            Drop image to attach to this session
          </div>
        )}
      </div>

      {target && (
        <div className={cn("flex items-center justify-between gap-3 px-3 py-2 border-t bg-background", accentClasses.terminal, colorClasses.terminalBar)}>
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex items-center gap-2 text-sm">
              <button
                className={cn(
                  'px-2 py-0.5 rounded text-xs font-medium transition-colors',
                  readOnly
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                )}
                onClick={() => setReadOnly(true)}
              >
                Read-only
              </button>
              <button
                className={cn(
                  'px-2 py-0.5 rounded text-xs font-medium transition-colors',
                  !readOnly
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                )}
                onClick={() => setReadOnly(false)}
              >
                Interactive
              </button>
            </div>
            <span className={cn(
              'text-xs shrink-0',
              connected ? 'text-green-500' : 'text-muted-foreground'
            )}>
              {connected ? 'Connected' : 'Disconnected'}
            </span>
            <span
              className="text-xs text-muted-foreground truncate"
              title={instance ? `${modeLabel} on ${instance.name} (${instance.hostname}) · ${target}` : target}
            >
              {instance ? `${modeLabel} on ${instance.name}` : sessionLabel}
            </span>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {onToggleFullscreen && !inLanes && (
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onToggleFullscreen} title={fullscreen ? 'Exit fullscreen' : 'Fullscreen'}>
                {fullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
              </Button>
            )}
            {onClose && (
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose} title="Close pane">
                <X className="h-3.5 w-3.5" />
              </Button>
            )}
            {connected ? (
              <Button variant="outline" size="sm" onClick={detach}>
                Detach
              </Button>
            ) : (
              <Button variant="outline" size="sm" onClick={() => attach(target)}>
                Attach
              </Button>
            )}
          </div>
        </div>
      )}
      {imageAttachment && (
        <ImageAttachmentDialog
          open
          fileName={imageAttachment.fileName}
          fileSize={imageAttachment.fileSize}
          previewUrl={imageAttachment.previewUrl}
          targetLabel={sessionLabel || target || 'this session'}
          uploading={imageAttachment.uploading}
          pasting={imageAttachment.pasting}
          readOnly={readOnly}
          error={imageAttachment.error}
          attachment={imageAttachment.attachment}
          onOpenChange={(open) => {
            if (!open) closeImageAttachment()
          }}
          onPaste={(submit) => {
            void handleAttachmentPaste(submit)
          }}
          onSwitchInteractive={() => setReadOnly(false)}
        />
      )}
    </div>
  )
}
