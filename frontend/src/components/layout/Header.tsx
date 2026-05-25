import { Terminal, Radio } from "lucide-react";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Badge } from "@/components/ui/badge";
import { useTheme } from "@/contexts/ThemeContext";
import { useSystemStatus } from "@/hooks/useSystemStatus";
import { useProviderContext } from "@/contexts/ProviderContext";
import { cn } from "@/lib/utils";

export function Header() {
  const { theme } = useTheme();
  const status = useSystemStatus();
  const { selectedProviderId, selectedProvider } = useProviderContext();
  const selectedStatus = status?.providers?.[selectedProviderId] ?? selectedProvider;

  return (
    <header className="border-b bg-background">
      <div className="flex h-16 items-center justify-between px-6">
        <div className="flex items-center gap-3">
          <img
            src={theme === "light" ? "/logo-light.png" : "/logo-dark.png"}
            alt="Claude Deck"
            className="h-10 w-10"
          />
          <div>
            <h1 className="text-2xl font-bold text-primary leading-tight">Claude Deck</h1>
            <p className="text-xs text-muted-foreground">Your local agent command centre</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {status && (
            <>
              {selectedStatus?.version && (
                <Badge variant="outline" className="gap-1 font-mono text-xs">
                  <Terminal className="h-3 w-3" />
                  {selectedStatus.display_name} v{selectedStatus.version}
                </Badge>
              )}
              <Badge
                variant="secondary"
                className={cn(
                  "gap-1 text-xs",
                  status.activeSessions > 0 && "bg-green-500/15 text-green-600 dark:text-green-400"
                )}
              >
                <Radio className="h-3 w-3" />
                {status.activeSessions} active
              </Badge>
            </>
          )}
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}
