export function LeaderHintOverlay() {
  return (
    <div className="pointer-events-none fixed right-4 top-4 z-[60] rounded-md border bg-background/95 px-3 py-2 text-xs text-foreground shadow-lg backdrop-blur">
      <span className="font-medium">Leader:</span>{' '}
      <span className="text-muted-foreground">← prev · → next · 1-4 jump · r toggle mode · Esc cancel</span>
    </div>
  )
}
