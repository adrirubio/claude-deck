import { useState } from 'react'
import { Plus, Pencil, Trash2, ChevronDown, ChevronRight } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { HookEntryForm, type HookHandlerData } from './HookEntryForm'
import { HOOK_EVENT_GROUPS } from '../constants'
import { HOOK_EVENTS, type HookEvent } from '@/types/hooks'
import type { ConfigValue } from '@/types/config'
import type { SettingsCardProps } from '../types'

type HooksConfig = Record<string, HookHandlerData[]>

function getEventMeta(event: string) {
  return HOOK_EVENTS.find((e) => e.name === event)
}

function summarizeHandler(h: HookHandlerData): string {
  if (h.type === 'command') return h.command?.slice(0, 60) || 'command'
  if (h.type === 'http') return h.url?.slice(0, 60) || 'http'
  if (h.type === 'prompt') return h.prompt?.slice(0, 60) || 'prompt'
  if (h.type === 'agent') return h.prompt?.slice(0, 60) || 'agent'
  return h.type
}

export function HookEventEditorCard({ getSetting, updateSetting }: SettingsCardProps) {
  const [expandedEvent, setExpandedEvent] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [editingEvent, setEditingEvent] = useState<HookEvent | null>(null)
  const [editingHandler, setEditingHandler] = useState<HookHandlerData | null>(null)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)

  const hooks = (getSetting<ConfigValue>('hooks', {}) ?? {}) as unknown as HooksConfig

  const setHooks = (updated: HooksConfig) => {
    updateSetting('hooks', updated as unknown as ConfigValue)
  }

  const handleAdd = () => {
    setEditingEvent(null)
    setEditingHandler(null)
    setEditingIndex(null)
    setFormOpen(true)
  }

  const handleEdit = (event: HookEvent, handler: HookHandlerData, index: number) => {
    setEditingEvent(event)
    setEditingHandler(handler)
    setEditingIndex(index)
    setFormOpen(true)
  }

  const handleDelete = (event: string, index: number) => {
    const eventHandlers = [...(hooks[event] || [])]
    eventHandlers.splice(index, 1)
    const updated = { ...hooks }
    if (eventHandlers.length === 0) {
      delete updated[event]
    } else {
      updated[event] = eventHandlers
    }
    setHooks(updated)
  }

  const handleSave = (event: HookEvent, handler: HookHandlerData) => {
    const updated = { ...hooks }

    if (editingEvent && editingIndex !== null) {
      // Editing existing handler
      if (editingEvent !== event) {
        // Event changed — remove from old, add to new
        const oldHandlers = [...(updated[editingEvent] || [])]
        oldHandlers.splice(editingIndex, 1)
        if (oldHandlers.length === 0) {
          delete updated[editingEvent]
        } else {
          updated[editingEvent] = oldHandlers
        }
        updated[event] = [...(updated[event] || []), handler]
      } else {
        // Same event — update in place
        const handlers = [...(updated[event] || [])]
        handlers[editingIndex] = handler
        updated[event] = handlers
      }
    } else {
      // Adding new handler
      updated[event] = [...(updated[event] || []), handler]
    }

    setHooks(updated)
    setExpandedEvent(event)
  }

  const totalHandlers = Object.values(hooks).reduce((sum, arr) => sum + (Array.isArray(arr) ? arr.length : 0), 0)

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Hook Events</CardTitle>
            <CardDescription>
              Configure event handlers in settings.json
              {totalHandlers > 0 && ` — ${totalHandlers} handler${totalHandlers !== 1 ? 's' : ''}`}
            </CardDescription>
          </div>
          <Button size="sm" variant="outline" onClick={handleAdd}>
            <Plus className="h-4 w-4 mr-1" />
            Add Hook
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {HOOK_EVENT_GROUPS.map((group) => {
          const groupEvents = group.events.filter((e) => hooks[e]?.length > 0)
          if (groupEvents.length === 0) return null

          return (
            <div key={group.label}>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">
                {group.label}
              </p>
              {groupEvents.map((eventName) => {
                const handlers = hooks[eventName] || []
                const meta = getEventMeta(eventName)
                const isExpanded = expandedEvent === eventName

                return (
                  <div key={eventName} className="border rounded mb-1">
                    <button
                      type="button"
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-muted/50 transition-colors text-left"
                      onClick={() => setExpandedEvent(isExpanded ? null : eventName)}
                    >
                      {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                      <span>{meta?.icon}</span>
                      <span className="font-medium">{meta?.label || eventName}</span>
                      <Badge variant="secondary" className="ml-auto text-xs">
                        {handlers.length}
                      </Badge>
                    </button>

                    {isExpanded && (
                      <div className="border-t px-3 py-2 space-y-2">
                        {handlers.map((handler, idx) => (
                          <div key={idx} className="flex items-center gap-2 text-sm bg-muted/50 rounded px-2 py-1.5">
                            <Badge variant="outline" className="text-xs shrink-0">{handler.type}</Badge>
                            <span className="truncate flex-1 text-muted-foreground font-mono text-xs">
                              {summarizeHandler(handler)}
                            </span>
                            <Button
                              size="icon"
                              variant="ghost"
                              className="h-6 w-6"
                              onClick={() => handleEdit(eventName as HookEvent, handler, idx)}
                            >
                              <Pencil className="h-3 w-3" />
                            </Button>
                            <Button
                              size="icon"
                              variant="ghost"
                              className="h-6 w-6 text-destructive"
                              onClick={() => handleDelete(eventName, idx)}
                            >
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )
        })}

        {totalHandlers === 0 && (
          <p className="text-sm text-muted-foreground text-center py-4">
            No hook events configured. Click "Add Hook" to create one.
          </p>
        )}
      </CardContent>

      <HookEntryForm
        open={formOpen}
        onOpenChange={setFormOpen}
        initialEvent={editingEvent}
        initialHandler={editingHandler}
        onSave={handleSave}
      />
    </Card>
  )
}
