import { Terminal, AlertCircle, Server } from "lucide-react";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { useTheme } from "@/contexts/ThemeContext";
import { useSystemStatus } from "@/hooks/useSystemStatus";
import { useInstanceDocumentTitle } from "@/hooks/useInstanceDocumentTitle";
import { useProviderContext } from "@/contexts/ProviderContext";
import { getInstanceAccentClasses } from "@/lib/instanceAccent";
import { MODAL_SIZES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { Link } from "react-router-dom";
import { harnessSummary } from "./harnessSummary";

const CLI_WARNING_LABEL = "Container cannot see host agent CLIs";

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
        `Albiex Synth City instance: ${instance.name}`,
        `Hostname: ${instance.hostname}`,
        `Opened from: ${typeof window === "undefined" ? "unknown" : window.location.host}`,
      ].join("\n")
    : undefined;

  if (providerStatuses.length === 0 && selectedProvider) {
    providerStatuses.push(status?.providers?.[selectedProviderId] ?? selectedProvider);
  }

  return (
    <header className={cn("border-b border-t-4 bg-background", instance ? accentClasses.headerBorder : "border-t-transparent")}>
      <div className="flex min-h-16 items-center justify-between gap-2 px-3 py-2 md:px-6">
        <div className="flex shrink-0 items-center gap-3">
          <img
            src={theme === "light" ? "/albiex-logo-compact.svg" : "/albiex-logo-compact-dark.svg"}
            alt="Albiex Synth City"
            className="h-10 w-auto shrink-0"
          />
          <p className="hidden text-xs text-muted-foreground sm:block">Your local agent command centre</p>
        </div>
        <div className="flex min-w-0 items-center gap-1 sm:gap-2">
          {!status && (
            // Reserve the badge space so the header does not shift when the status loads.
            <span aria-hidden="true" className="inline-block h-5.5 w-32" />
          )}
          {status && (
            <>
              {instance && (
                <Badge
                  variant="outline"
                  className={cn("min-w-0 gap-1 text-xs max-w-48 truncate", accentClasses.badge)}
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
                <Dialog>
                  <DialogTrigger asChild>
                    <button
                      type="button"
                      title={status.environment.agent_cli_warning}
                      aria-label={`${CLI_WARNING_LABEL}. ${status.environment.agent_cli_warning}`}
                      className="inline-flex shrink-0 max-w-88 rounded-md focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring sm:min-w-0 sm:shrink"
                    >
                      <Badge
                        variant="outline"
                        className="min-w-0 gap-1 text-xs border-destructive/40 text-destructive"
                      >
                        <AlertCircle className="h-3 w-3 shrink-0" />
                        <span className="hidden truncate sm:inline">{CLI_WARNING_LABEL}</span>
                      </Badge>
                    </button>
                  </DialogTrigger>
                  <DialogContent className={MODAL_SIZES.SM}>
                    <DialogHeader>
                      <DialogTitle>{CLI_WARNING_LABEL}</DialogTitle>
                      <DialogDescription>{status.environment.agent_cli_warning}</DialogDescription>
                    </DialogHeader>
                  </DialogContent>
                </Dialog>
              )}
            </>
          )}
          <div className="shrink-0">
            <ThemeToggle />
          </div>
        </div>
      </div>
    </header>
  )
}
