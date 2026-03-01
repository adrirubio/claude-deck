import { useRef, useEffect } from 'react'
import { Monitor } from 'lucide-react'
import { useTerminal } from './useTerminal'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface TerminalViewProps {
  target: string | null
}

export function TerminalView({ target }: TerminalViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const { connected, readOnly, setReadOnly, attach, detach } = useTerminal(containerRef)
  const prevTargetRef = useRef<string | null>(null)

  useEffect(() => {
    if (target !== prevTargetRef.current) {
      prevTargetRef.current = target
      if (target) {
        attach(target)
      } else {
        detach()
      }
    }
  }, [target, attach, detach])

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 relative">
        {!target && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground bg-background">
            <Monitor className="h-12 w-12 mb-3" />
            <p className="text-sm">Select a session to attach</p>
          </div>
        )}
        <div
          ref={containerRef}
          className={cn(
            'h-full w-full',
            !target && 'invisible'
          )}
        />
      </div>

      {target && (
        <div className="flex items-center justify-between px-3 py-2 border-t bg-background">
          <div className="flex items-center gap-3">
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
              'text-xs',
              connected ? 'text-green-500' : 'text-muted-foreground'
            )}>
              {connected ? 'Connected' : 'Disconnected'}
            </span>
          </div>
          <Button variant="outline" size="sm" onClick={detach}>
            Detach
          </Button>
        </div>
      )}
    </div>
  )
}
