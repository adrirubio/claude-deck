import { useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { MODAL_SIZES } from '@/lib/constants'
import { SwitchSetting, TextSetting, NumberSetting, SelectSetting, ListEditor, KeyValueEditor } from '../field-components'
import { HANDLER_TYPE_OPTIONS, SHELL_OPTIONS, HOOK_MODEL_OPTIONS, HOOK_EVENT_GROUPS } from '../constants'
import type { HookEvent, HookType } from '@/types/hooks'

export interface HookHandlerData {
  type: HookType
  matcher?: string
  if?: string
  timeout?: number
  statusMessage?: string
  once?: boolean
  command?: string
  async?: boolean
  shell?: string
  url?: string
  headers?: Record<string, string>
  allowedEnvVars?: string[]
  prompt?: string
  model?: string
}

interface HookEntryFormInnerProps {
  initialEvent: HookEvent | null
  initialHandler: HookHandlerData | null
  onOpenChange: (open: boolean) => void
  onSave: (event: HookEvent, handler: HookHandlerData) => void
}

interface HookEntryFormProps extends HookEntryFormInnerProps {
  open: boolean
}

const EMPTY_HANDLER: HookHandlerData = {
  type: 'command',
  command: '',
}

/**
 * Inner form component — remounted via key when the dialog opens
 * so initial state is always fresh (avoids setState-in-effect warning).
 */
function HookEntryFormInner({ initialEvent, initialHandler, onOpenChange, onSave }: HookEntryFormInnerProps) {
  const [event, setEvent] = useState<HookEvent | ''>(initialEvent ?? '')
  const [handler, setHandler] = useState<HookHandlerData>(initialHandler ?? { ...EMPTY_HANDLER })

  const update = <K extends keyof HookHandlerData>(key: K, value: HookHandlerData[K]) => {
    setHandler((prev) => ({ ...prev, [key]: value }))
  }

  const handleSave = () => {
    if (!event) return
    onSave(event as HookEvent, handler)
    onOpenChange(false)
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{initialHandler ? 'Edit Hook Handler' : 'Add Hook Handler'}</DialogTitle>
      </DialogHeader>

        <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-1">
          {/* Event Selector */}
          <div className="grid gap-2">
            <Label>Event</Label>
            <Select value={event} onValueChange={(v) => setEvent(v as HookEvent)}>
              <SelectTrigger>
                <SelectValue placeholder="Select a hook event" />
              </SelectTrigger>
              <SelectContent>
                {HOOK_EVENT_GROUPS.map((group) => (
                  <SelectGroup key={group.label}>
                    <SelectLabel>{group.label}</SelectLabel>
                    {group.events.map((e) => (
                      <SelectItem key={e} value={e}>{e}</SelectItem>
                    ))}
                  </SelectGroup>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Handler Type */}
          <SelectSetting
            id="hookType"
            label="Handler Type"
            value={handler.type}
            onValueChange={(v) => update('type', v as HookType)}
            options={HANDLER_TYPE_OPTIONS}
          />

          {/* Common Fields */}
          <TextSetting
            id="hookMatcher"
            label="Matcher"
            description="Regex or exact match filter for the event (e.g., Write(*.py) for PreToolUse)"
            value={handler.matcher ?? ''}
            onChange={(v) => update('matcher', v || undefined)}
            placeholder="e.g., Write(*.py)"
          />

          <TextSetting
            id="hookIf"
            label="If (Permission Rule)"
            description="Permission rule filter — handler only runs if this rule matches"
            value={handler.if ?? ''}
            onChange={(v) => update('if', v || undefined)}
            placeholder="e.g., Bash(git *)"
          />

          <NumberSetting
            id="hookTimeout"
            label="Timeout (seconds)"
            value={handler.timeout ?? ''}
            onChange={(v) => update('timeout', v ?? undefined)}
            placeholder="30"
          />

          <TextSetting
            id="hookStatusMessage"
            label="Status Message"
            description="Custom spinner text while the hook runs"
            value={handler.statusMessage ?? ''}
            onChange={(v) => update('statusMessage', v || undefined)}
            placeholder="e.g., Running linter..."
          />

          <SwitchSetting
            label="Once"
            description="Fire only once per session"
            checked={handler.once ?? false}
            onCheckedChange={(v) => update('once', v || undefined)}
          />

          {/* Type-specific fields */}
          {handler.type === 'command' && (
            <>
              <div className="grid gap-2">
                <Label htmlFor="hookCommand">Command</Label>
                <Textarea
                  id="hookCommand"
                  className="font-mono text-sm"
                  rows={3}
                  value={handler.command ?? ''}
                  onChange={(e) => update('command', e.target.value)}
                  placeholder="e.g., eslint $CLAUDE_FILE_PATHS"
                />
              </div>

              <SwitchSetting
                label="Async"
                description="Run in background without blocking"
                checked={handler.async ?? false}
                onCheckedChange={(v) => update('async', v || undefined)}
              />

              <SelectSetting
                id="hookShell"
                label="Shell"
                value={handler.shell ?? ''}
                onValueChange={(v) => update('shell', v || undefined)}
                placeholder="Default (bash)"
                options={SHELL_OPTIONS}
              />
            </>
          )}

          {handler.type === 'http' && (
            <>
              <TextSetting
                id="hookUrl"
                label="URL"
                description="POST endpoint to call"
                value={handler.url ?? ''}
                onChange={(v) => update('url', v)}
                placeholder="https://hooks.example.com/webhook"
              />

              <div className="grid gap-2">
                <Label>Headers</Label>
                <KeyValueEditor
                  value={handler.headers ?? {}}
                  onChange={(v) => update('headers', Object.keys(v).length > 0 ? v : undefined)}
                />
              </div>

              <div className="grid gap-2">
                <Label>Allowed Environment Variables</Label>
                <p className="text-sm text-muted-foreground">
                  Environment variables included in the webhook payload
                </p>
                <ListEditor
                  value={handler.allowedEnvVars ?? []}
                  onChange={(v) => update('allowedEnvVars', v.length > 0 ? v : undefined)}
                  placeholder="e.g., MY_TOKEN"
                />
              </div>
            </>
          )}

          {(handler.type === 'prompt' || handler.type === 'agent') && (
            <>
              <div className="grid gap-2">
                <Label htmlFor="hookPrompt">Prompt</Label>
                <Textarea
                  id="hookPrompt"
                  rows={4}
                  value={handler.prompt ?? ''}
                  onChange={(e) => update('prompt', e.target.value)}
                  placeholder={handler.type === 'agent'
                    ? 'Describe what the agent should do...'
                    : 'Decision prompt for Claude to evaluate...'}
                />
              </div>

              <SelectSetting
                id="hookModel"
                label="Model"
                value={handler.model ?? ''}
                onValueChange={(v) => update('model', v || undefined)}
                placeholder="Default (fast-model)"
                options={HOOK_MODEL_OPTIONS}
              />
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSave} disabled={!event}>Save</Button>
        </DialogFooter>
    </>
  )
}

/** Wrapper that remounts inner form when dialog opens for fresh state. */
export function HookEntryForm({ open, onOpenChange, initialEvent: event, initialHandler: handler, onSave }: HookEntryFormProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={MODAL_SIZES.LG}>
        {open && (
          <HookEntryFormInner
            initialEvent={event}
            initialHandler={handler}
            onOpenChange={onOpenChange}
            onSave={onSave}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
