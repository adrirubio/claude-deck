import { LEADER_PREFIX_LABEL, LEADER_SHORTCUTS } from './leaderShortcuts'

export function LeaderHintOverlay() {
  return (
    <div className="pointer-events-none fixed right-4 top-4 z-[60] rounded-md border bg-background/95 px-3 py-2 text-xs text-foreground shadow-lg backdrop-blur">
      <span className="font-medium">Leader {LEADER_PREFIX_LABEL}:</span>{' '}
      <span className="text-muted-foreground">
        {LEADER_SHORTCUTS.map((shortcut) => `${shortcut.keys} ${shortcut.label}`).join(' · ')}
      </span>
    </div>
  )
}
