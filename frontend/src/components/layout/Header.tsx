import { Terminal, AlertCircle, Server } from "lucide-react";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Badge } from "@/components/ui/badge";
import { useTheme } from "@/contexts/ThemeContext";
import { useSystemStatus } from "@/hooks/useSystemStatus";
import { useInstanceDocumentTitle } from "@/hooks/useInstanceDocumentTitle";
import { useProviderContext } from "@/contexts/ProviderContext";
import { getInstanceAccentClasses } from "@/lib/instanceAccent";
import { cn } from "@/lib/utils";
import { Link } from "react-router-dom";
import { harnessSummary } from "./harnessSummary";

export function Header() {
  const { theme } = useTheme();
  const status = useSystemStatus();
  const instance = status?.instance ?? null;
  const accentClasses = getInstanceAccentClasses(instance?.accent);
  const { providers, selectedProviderId, selectedProvider } = useProviderContext();
  const providerStatuses = providers
    .map((provider) => status?.providers?.[provider.id] ?? provider)
    .filter((provider) => provider.installed || provider.id === selectedProviderId);
  const summary = harnessSummary(providerStatuses);
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
    <header className={cn("border-b border-t-4 bg-background", instance ? accentClasses.headerBorder : "border-t-transparent")}>
      <div className="flex min-h-16 flex-wrap items-center justify-between gap-2 px-3 py-2 md:px-6">
        <div className="flex items-center gap-3">
          <img
            src={theme === "light" ? "/logo-light.png" : "/logo-dark.png"}
            alt="Claude Deck"
            className="h-10 w-10"
          />
          <div>
            <h1 className="text-xl md:text-2xl font-bold text-primary leading-tight">Claude Deck</h1>
            <p className="text-xs text-muted-foreground">Your local agent command centre</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!status && (
            // Reserve the badge space so the header does not shift when the status loads.
            <span aria-hidden="true" className="inline-block h-5.5 w-32" />
          )}
          {status && (
            <>
              {instance && (
                <Badge
                  variant="outline"
                  className={cn("gap-1 text-xs max-w-48 truncate", accentClasses.badge)}
                  title={instanceTitle}
                >
                  <Server className="h-3 w-3 shrink-0" />
                  <span className={cn("h-2 w-2 rounded-full shrink-0", accentClasses.dot)} />
                  <span className="truncate">{instance.name}</span>
                </Badge>
              )}
              {providerStatuses.length > 0 && (
                <Link
                  to="/harnesses"
                  title={summary.title}
                  aria-label={`${summary.label}. Open Harnesses`}
                  className="hidden md:inline-flex rounded-md focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <Badge
                    variant="outline"
                    className={cn("gap-1 text-xs hover:border-primary/50", summary.problem && "border-destructive/40 text-destructive")}
                  >
                    {summary.problem ? <AlertCircle className="h-3 w-3" /> : <Terminal className="h-3 w-3" />}
                    {summary.label}
                  </Badge>
                </Link>
              )}
              {status.environment?.agent_cli_warning && (
                <Badge
                  variant="outline"
                  className="gap-1 text-xs border-destructive/40 text-destructive max-w-88"
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
