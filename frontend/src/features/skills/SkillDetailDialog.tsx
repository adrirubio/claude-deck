import { useEffect, useState, useCallback } from "react";
import {
  Sparkles,
  MapPin,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Download,
  FileText,
  Terminal,
  Package,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { apiClient, buildEndpoint } from "@/lib/api";
import {
  type Skill,
  type SkillDependencyStatus,
  type SkillInstallResult,
} from "@/types/agents";
import { toast } from "sonner";

interface SkillDetailDialogProps {
  skill: Skill | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectPath?: string;
}

export function SkillDetailDialog({
  skill,
  open,
  onOpenChange,
  projectPath,
}: SkillDetailDialogProps) {
  const [fullSkill, setFullSkill] = useState<Skill | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [installing, setInstalling] = useState(false);
  const [installResult, setInstallResult] = useState<SkillInstallResult | null>(
    null
  );
  const [logsOpen, setLogsOpen] = useState(false);

  const fetchSkillDetails = useCallback(async () => {
    if (!skill) return;

    setLoading(true);
    setError(null);
    setInstallResult(null);
    try {
      const params = projectPath
        ? { project_path: projectPath, include_deps: true }
        : { include_deps: true };
      const response = await apiClient<Skill>(
        buildEndpoint(
          `agents/skills/${encodeURIComponent(skill.location)}/${encodeURIComponent(skill.name)}`,
          params
        )
      );
      setFullSkill(response);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load skill details"
      );
    } finally {
      setLoading(false);
    }
  }, [skill?.name, skill?.location, projectPath]);

  useEffect(() => {
    if (open && skill) {
      fetchSkillDetails();
    } else {
      setFullSkill(null);
      setError(null);
      setInstallResult(null);
      setLogsOpen(false);
    }
  }, [open, fetchSkillDetails]);

  const handleInstall = async () => {
    if (!skill) return;

    setInstalling(true);
    setInstallResult(null);
    try {
      const params = projectPath ? { project_path: projectPath } : {};
      const result = await apiClient<SkillInstallResult>(
        buildEndpoint(
          `agents/skills/${encodeURIComponent(skill.location)}/${encodeURIComponent(skill.name)}/install`,
          params
        ),
        { method: "POST" }
      );
      setInstallResult(result);

      if (result.success) {
        toast.success(result.message);
        // Refresh skill details to update dependency status
        await fetchSkillDetails();
      } else {
        toast.error(result.message);
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

  const getLocationBadge = (location: string) => {
    if (location === "user") {
      return (
        <Badge variant="outline" className="flex items-center gap-1">
          <MapPin className="h-3 w-3" />
          User
        </Badge>
      );
    }
    if (location === "project") {
      return (
        <Badge variant="outline" className="flex items-center gap-1">
          <MapPin className="h-3 w-3" />
          Project
        </Badge>
      );
    }
    const pluginName = location.replace("plugin:", "");
    return (
      <Badge variant="secondary" className="flex items-center gap-1">
        <Sparkles className="h-3 w-3" />
        {pluginName}
      </Badge>
    );
  };

  const depStatus = fullSkill?.dependency_status;
  const hasDeps =
    depStatus && depStatus.dependencies.length > 0;
  const hasMissing = hasDeps && !depStatus.all_satisfied;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <Sparkles className="h-6 w-6 text-amber-500 flex-shrink-0" />
            <DialogTitle className="text-xl">{skill?.name}</DialogTitle>
            {skill && getLocationBadge(skill.location)}
          </div>
          {skill?.description && (
            <DialogDescription className="text-base mt-2">
              {skill.description}
            </DialogDescription>
          )}
        </DialogHeader>

        <div className="flex-1 overflow-auto mt-4 space-y-4">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : error ? (
            <div className="text-center py-8 text-destructive">
              <p>{error}</p>
            </div>
          ) : (
            <>
              {/* Dependency Status Section */}
              {hasDeps && (
                <div className="rounded-lg border p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Package className="h-5 w-5 text-muted-foreground" />
                      <h3 className="font-semibold">Dependencies</h3>
                      {depStatus.all_satisfied ? (
                        <Badge
                          variant="outline"
                          className="text-green-600 border-green-200 bg-green-50"
                        >
                          <CheckCircle2 className="h-3 w-3 mr-1" />
                          All satisfied
                        </Badge>
                      ) : (
                        <Badge
                          variant="outline"
                          className="text-amber-600 border-amber-200 bg-amber-50"
                        >
                          <AlertTriangle className="h-3 w-3 mr-1" />
                          {
                            depStatus.dependencies.filter((d) => !d.installed)
                              .length
                          }{" "}
                          missing
                        </Badge>
                      )}
                    </div>

                    {hasMissing && (
                      <Button
                        size="sm"
                        onClick={handleInstall}
                        disabled={installing}
                      >
                        {installing ? (
                          <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                        ) : (
                          <Download className="h-4 w-4 mr-1" />
                        )}
                        {installing ? "Installing..." : "Install Dependencies"}
                      </Button>
                    )}
                  </div>

                  <div className="space-y-2">
                    {depStatus.dependencies.map((dep) => (
                      <div
                        key={`${dep.kind}-${dep.name}`}
                        className="flex items-center gap-3 text-sm"
                      >
                        {dep.installed ? (
                          <CheckCircle2 className="h-4 w-4 text-green-500 flex-shrink-0" />
                        ) : (
                          <XCircle className="h-4 w-4 text-red-500 flex-shrink-0" />
                        )}
                        <Badge variant="outline" className="text-xs font-mono">
                          {dep.kind}
                        </Badge>
                        <span className="font-medium">{dep.name}</span>
                        {dep.installed_version && (
                          <span className="text-muted-foreground text-xs">
                            {dep.installed_version}
                          </span>
                        )}
                        {!dep.installed && dep.kind === "bin" && (
                          <span className="text-muted-foreground text-xs italic">
                            manual install required
                          </span>
                        )}
                      </div>
                    ))}
                  </div>

                  {/* Install Result */}
                  {installResult && (
                    <Collapsible open={logsOpen} onOpenChange={setLogsOpen}>
                      <div className="mt-3 rounded border p-3 bg-muted/50">
                        <CollapsibleTrigger className="flex items-center gap-2 text-sm font-medium w-full">
                          <Terminal className="h-4 w-4" />
                          <span>
                            Installation{" "}
                            {installResult.success
                              ? "completed"
                              : "had errors"}
                          </span>
                          {installResult.installed.length > 0 && (
                            <Badge
                              variant="outline"
                              className="text-green-600 text-xs"
                            >
                              {installResult.installed.length} installed
                            </Badge>
                          )}
                          {installResult.failed.length > 0 && (
                            <Badge
                              variant="outline"
                              className="text-red-600 text-xs"
                            >
                              {installResult.failed.length} failed
                            </Badge>
                          )}
                          <span className="ml-auto">
                            {logsOpen ? (
                              <ChevronUp className="h-4 w-4" />
                            ) : (
                              <ChevronDown className="h-4 w-4" />
                            )}
                          </span>
                        </CollapsibleTrigger>
                        <CollapsibleContent>
                          {installResult.logs && (
                            <pre className="mt-2 text-xs font-mono whitespace-pre-wrap bg-background rounded p-2 border max-h-48 overflow-auto">
                              {installResult.logs}
                            </pre>
                          )}
                        </CollapsibleContent>
                      </div>
                    </Collapsible>
                  )}
                </div>
              )}

              {/* Supporting Files Section */}
              {fullSkill?.supporting_files &&
                fullSkill.supporting_files.length > 0 && (
                  <div className="rounded-lg border p-4 space-y-3">
                    <div className="flex items-center gap-2">
                      <FileText className="h-5 w-5 text-muted-foreground" />
                      <h3 className="font-semibold">Supporting Files</h3>
                      <Badge variant="outline" className="text-xs">
                        {fullSkill.supporting_files.length} files
                      </Badge>
                    </div>
                    <div className="space-y-1">
                      {fullSkill.supporting_files.map((file) => (
                        <div
                          key={file.name}
                          className="flex items-center gap-2 text-sm py-1"
                        >
                          {file.is_script ? (
                            <Terminal className="h-4 w-4 text-amber-500" />
                          ) : (
                            <FileText className="h-4 w-4 text-muted-foreground" />
                          )}
                          <span className="font-mono text-xs">{file.name}</span>
                          <span className="text-muted-foreground text-xs">
                            {file.size_bytes < 1024
                              ? `${file.size_bytes}B`
                              : `${(file.size_bytes / 1024).toFixed(1)}KB`}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

              {/* Skill Content */}
              {fullSkill?.content ? (
                <div className="rounded-lg border bg-muted/50 p-4">
                  <pre className="whitespace-pre-wrap font-mono text-sm leading-relaxed text-foreground">
                    {fullSkill.content}
                  </pre>
                </div>
              ) : (
                !loading && (
                  <div className="text-center py-8 text-muted-foreground">
                    <p>No content available for this skill.</p>
                  </div>
                )
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
