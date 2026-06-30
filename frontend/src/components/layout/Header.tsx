import { Terminal, AlertCircle, Server } from "lucide-react";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Badge } from "@/components/ui/badge";
import { useTheme } from "@/contexts/ThemeContext";
import { useSystemStatus } from "@/hooks/useSystemStatus";
import { useInstanceDocumentTitle } from "@/hooks/useInstanceDocumentTitle";
import { useProviderContext } from "@/contexts/ProviderContext";
import { getInstanceAccentClasses } from "@/lib/instanceAccent";
import { cn } from "@/lib/utils";

export function Header() {
  const { theme } = useTheme();
  const status = useSystemStatus();
  const instance = status?.instance ?? null;
  const accentClasses = getInstanceAccentClasses(instance?.accent);
  const { providers, selectedProviderId, selectedProvider } = useProviderContext();
  const providerStatuses = providers
    .map((provider) => status?.providers?.[provider.id] ?? provider)
    .filter((provider) => provider.installed || provider.id === selectedProviderId);
  useInstanceDocumentTitle(instance);

  const instanceTitle = instance
    ? [
        `Claude Deck instance: ${instance.name}`,
        `Hostname: ${instance.hostname}`,
        `Opened from: ${typeof window === "undefined" ? "unknown" : window.location.host}`,
      ].join("\n")
    : undefined;

  if (providerStatuses.length === 0 && selectedProvider) {
    providerStatuses.push(status?.providers?.[selectedProviderId] ?? selectedProvider);
  }

  return (
    <header className={cn("border-b bg-background", instance && "border-t-4", instance && accentClasses.headerBorder)}>
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
              {instance && (
                <Badge
                  variant="outline"
                  className={cn("gap-1 text-xs max-w-[12rem] truncate", accentClasses.badge)}
                  title={instanceTitle}
                >
                  <Server className="h-3 w-3 shrink-0" />
                  <span className={cn("h-2 w-2 rounded-full shrink-0", accentClasses.dot)} />
                  <span className="truncate">{instance.name}</span>
                </Badge>
              )}
              {providerStatuses.map((provider) => (
                <Badge
                  key={provider.id}
                  variant="outline"
                  title={provider.unavailable_reason ?? undefined}
                  className={cn(
                    "gap-1 text-xs",
                    provider.installed ? "font-mono" : "border-destructive/40 text-destructive"
                  )}
                >
                  {provider.installed ? (
                    <Terminal className="h-3 w-3" />
                  ) : (
                    <AlertCircle className="h-3 w-3" />
                  )}
                  {provider.display_name}
                  {provider.version ? ` v${provider.version}` : provider.installed ? " ready" : " missing"}
                </Badge>
              ))}
              {status.environment?.agent_cli_warning && (
                <Badge
                  variant="outline"
                  className="gap-1 text-xs border-destructive/40 text-destructive max-w-[22rem]"
                  title={status.environment.agent_cli_warning}
                >
                  <AlertCircle className="h-3 w-3 shrink-0" />
                  <span className="truncate">Container cannot see host agent CLIs</span>
                </Badge>
              )}
            </>
          )}
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}
