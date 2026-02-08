export function Footer() {
  return (
    <footer className="border-t border-border/40 bg-background/50 px-4 py-2">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>Claude Deck v{APP_VERSION}</span>
        <a
          href="https://github.com/adrirubio/claude-deck"
          target="_blank"
          rel="noopener noreferrer"
          className="hover:text-foreground transition-colors"
        >
          GitHub
        </a>
      </div>
    </footer>
  )
}
