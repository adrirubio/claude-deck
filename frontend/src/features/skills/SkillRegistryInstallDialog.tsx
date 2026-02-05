import { useState } from "react";
import {
  Download,
  Loader2,
  CheckCircle2,
  XCircle,
  ExternalLink,
  Github,
  Terminal,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { apiClient, buildEndpoint } from "@/lib/api";
import {
  type RegistrySkill,
  type RegistryInstallResponse,
} from "@/types/agents";
import { toast } from "sonner";

interface SkillRegistryInstallDialogProps {
  skill: RegistrySkill | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onComplete?: () => void;
  projectPath?: string;
}

export function SkillRegistryInstallDialog({
  skill,
  open,
  onOpenChange,
  onComplete,
  projectPath,
}: SkillRegistryInstallDialogProps) {
  const [installing, setInstalling] = useState(false);
  const [result, setResult] = useState<RegistryInstallResponse | null>(null);
  const [globalInstall, setGlobalInstall] = useState(true);
  const [logsOpen, setLogsOpen] = useState(false);

  const handleInstall = async () => {
    if (!skill) return;

    setInstalling(true);
    setResult(null);
    try {
      const params = projectPath ? { project_path: projectPath } : {};
      const response = await apiClient<RegistryInstallResponse>(
        buildEndpoint("agents/skills/registry/install", params),
        {
          method: "POST",
          body: JSON.stringify({
            source: skill.source,
            skill_names: [skill.name],
            global_install: globalInstall,
          }),
        }
      );

      setResult(response);
      if (response.success) {
        toast.success(`Installed ${skill.name} from ${skill.source}`);
        onComplete?.();
      } else {
        toast.error(response.message);
        setLogsOpen(true);
      }
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Installation failed"
      );
    } finally {
      setInstalling(false);
    }
  };

  const handleClose = (open: boolean) => {
    if (!installing) {
      setResult(null);
      setLogsOpen(false);
      setGlobalInstall(true);
      onOpenChange(open);
    }
  };

  const formatInstalls = (count: number): string => {
    if (count >= 1000) {
      return `${(count / 1000).toFixed(count >= 10000 ? 0 : 1)}K`;
    }
    return count.toString();
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Download className="h-5 w-5" />
            Install Skill
          </DialogTitle>
          {skill && (
            <DialogDescription>
              Install <strong>{skill.name}</strong> from{" "}
              <span className="font-mono">{skill.source}</span>
            </DialogDescription>
          )}
        </DialogHeader>

        {skill && (
          <div className="space-y-4">
            {/* Skill info */}
            <div className="rounded-lg border p-4 space-y-3">
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="font-semibold text-lg">{skill.name}</h3>
                  <p className="text-sm text-muted-foreground font-mono">
                    {skill.source}
                  </p>
                </div>
                <Badge variant="secondary" className="flex items-center gap-1">
                  <Download className="h-3 w-3" />
                  {formatInstalls(skill.installs)}
                </Badge>
              </div>

              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 text-xs"
                  onClick={() =>
                    window.open(skill.url, "_blank", "noopener")
                  }
                >
                  <ExternalLink className="h-3 w-3 mr-1" />
                  skills.sh
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 text-xs"
                  onClick={() =>
                    window.open(skill.github_url, "_blank", "noopener")
                  }
                >
                  <Github className="h-3 w-3 mr-1" />
                  GitHub
                </Button>
              </div>
            </div>

            {/* Install options */}
            {!result && (
              <div className="flex items-center justify-between rounded-lg border p-4">
                <div className="space-y-0.5">
                  <Label htmlFor="global-install" className="font-medium">
                    Global install
                  </Label>
                  <p className="text-xs text-muted-foreground">
                    {globalInstall
                      ? "Install to ~/.claude/skills/ (available everywhere)"
                      : "Install to project .claude/skills/ (project-only)"}
                  </p>
                </div>
                <Switch
                  id="global-install"
                  checked={globalInstall}
                  onCheckedChange={setGlobalInstall}
                  disabled={installing}
                />
              </div>
            )}

            {/* Install result */}
            {result && (
              <div
                className={`rounded-lg border p-4 ${
                  result.success
                    ? "border-green-200 bg-green-50 dark:bg-green-950/20"
                    : "border-red-200 bg-red-50 dark:bg-red-950/20"
                }`}
              >
                <div className="flex items-center gap-2">
                  {result.success ? (
                    <CheckCircle2 className="h-5 w-5 text-green-600" />
                  ) : (
                    <XCircle className="h-5 w-5 text-red-600" />
                  )}
                  <span
                    className={`font-medium ${
                      result.success ? "text-green-700" : "text-red-700"
                    }`}
                  >
                    {result.message}
                  </span>
                </div>

                {result.logs && (
                  <Collapsible open={logsOpen} onOpenChange={setLogsOpen}>
                    <CollapsibleTrigger className="flex items-center gap-2 text-sm mt-3 text-muted-foreground hover:text-foreground">
                      <Terminal className="h-4 w-4" />
                      <span>Installation logs</span>
                      {logsOpen ? (
                        <ChevronUp className="h-4 w-4" />
                      ) : (
                        <ChevronDown className="h-4 w-4" />
                      )}
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <pre className="mt-2 text-xs font-mono whitespace-pre-wrap bg-background rounded p-3 border max-h-48 overflow-auto">
                        {result.logs}
                      </pre>
                    </CollapsibleContent>
                  </Collapsible>
                )}
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          {!result ? (
            <>
              <Button
                variant="outline"
                onClick={() => handleClose(false)}
                disabled={installing}
              >
                Cancel
              </Button>
              <Button onClick={handleInstall} disabled={installing}>
                {installing ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Installing...
                  </>
                ) : (
                  <>
                    <Download className="h-4 w-4 mr-2" />
                    Install
                  </>
                )}
              </Button>
            </>
          ) : (
            <Button onClick={() => handleClose(false)}>
              {result.success ? "Done" : "Close"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
