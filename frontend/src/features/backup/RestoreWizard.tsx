import { useState, useEffect, useMemo, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  Package,
  Puzzle,
  Server,
  Loader2,
  AlertCircle,
  Monitor,
  FileCode,
  Bot,
  Terminal,
  Download,
  X,
  CheckCircle2,
  XCircle,
} from "lucide-react";
import { apiClient } from "@/lib/api";
import {
  type Backup,
  type RestorePlan,
  type RestoreOptions,
  type RestoreResult,
  type DependencyInstallRequest,
  type DependencyInstallResult,
  formatBytes,
  formatDate,
  PLATFORM_NAMES,
  DEPENDENCY_KINDS,
} from "@/types/backup";

interface RestoreWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  backup: Backup | null;
  onRestoreComplete?: () => void;
  projectPath?: string;
}

const STEPS = [
  { title: "Select", description: "Review backup details" },
  { title: "Contents", description: "What's in the backup" },
  { title: "Components", description: "Choose what to restore" },
  { title: "Dependencies", description: "Required installations" },
  { title: "Confirm", description: "Review and restore" },
  { title: "Complete", description: "Restore results" },
];

export function RestoreWizard({
  open,
  onOpenChange,
  backup,
  onRestoreComplete,
  projectPath,
}: RestoreWizardProps) {
  const [step, setStep] = useState(0);
  const [plan, setPlan] = useState<RestorePlan | null>(null);
  const [loadingPlan, setLoadingPlan] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [installingDeps, setInstallingDeps] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [restoreResult, setRestoreResult] = useState<RestoreResult | null>(null);
  const [depResult, setDepResult] = useState<DependencyInstallResult | null>(null);

  // Restore options
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [selectAll, setSelectAll] = useState(true);
  const [installDependencies, setInstallDependencies] = useState(true);
  const [skipPlugins, setSkipPlugins] = useState(false);
  const [skipSkills, setSkipSkills] = useState(false);
  const [dryRun, setDryRun] = useState(false);

  const fetchRestorePlan = useCallback(async () => {
    if (!backup) return;

    setLoadingPlan(true);
    setError(null);
    try {
      const url = projectPath
        ? `/api/v1/backup/${backup.id}/plan?project_path=${encodeURIComponent(projectPath)}`
        : `/api/v1/backup/${backup.id}/plan`;
      const response = await apiClient<RestorePlan>(url);
      setPlan(response);
    } catch {
      setError("Failed to load restore plan");
    } finally {
      setLoadingPlan(false);
    }
  }, [backup, projectPath]);

  useEffect(() => {
    if (open && backup) {
      fetchRestorePlan();
    }
  }, [open, backup, fetchRestorePlan]);

  useEffect(() => {
    // Initialize selected files when plan loads
    if (plan) {
      setSelectedFiles(new Set(plan.files_to_restore));
      setSelectAll(true);
    }
  }, [plan]);

  const resetForm = () => {
    setStep(0);
    setPlan(null);
    setError(null);
    setRestoreResult(null);
    setDepResult(null);
    setSelectedFiles(new Set());
    setSelectAll(true);
    setInstallDependencies(true);
    setSkipPlugins(false);
    setSkipSkills(false);
    setDryRun(false);
  };

  const handleOpenChange = (newOpen: boolean) => {
    if (!newOpen) {
      resetForm();
    }
    onOpenChange(newOpen);
  };

  const handleNext = () => {
    if (step < STEPS.length - 1) {
      setStep(step + 1);
    }
  };

  const handleBack = () => {
    if (step > 0) {
      setStep(step - 1);
    }
  };

  const handleSelectAllFiles = (checked: boolean) => {
    setSelectAll(checked);
    if (checked && plan) {
      setSelectedFiles(new Set(plan.files_to_restore));
    } else {
      setSelectedFiles(new Set());
    }
  };

  const handleFileToggle = (file: string) => {
    const newSelected = new Set(selectedFiles);
    if (newSelected.has(file)) {
      newSelected.delete(file);
    } else {
      newSelected.add(file);
    }
    setSelectedFiles(newSelected);
    setSelectAll(plan ? newSelected.size === plan.files_to_restore.length : false);
  };

  const handleRestore = async () => {
    if (!backup) return;

    setRestoring(true);
    setError(null);
    try {
      const options: RestoreOptions = {
        selective_restore: selectAll ? undefined : Array.from(selectedFiles),
        install_dependencies: false, // We'll do this separately
        dry_run: dryRun,
        skip_plugins: skipPlugins,
        skip_skills: skipSkills,
      };

      const result = await apiClient<RestoreResult>(
        `/api/v1/backup/${backup.id}/restore`,
        {
          method: "POST",
          body: JSON.stringify(options),
        }
      );

      setRestoreResult(result);
      setStep(5); // Go to results step

      // Install dependencies if requested and not dry run
      if (installDependencies && !dryRun && plan?.has_dependencies) {
        await handleInstallDependencies();
      }

      onRestoreComplete?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to restore backup");
    } finally {
      setRestoring(false);
    }
  };

  const handleInstallDependencies = async () => {
    if (!backup) return;

    setInstallingDeps(true);
    try {
      const request: DependencyInstallRequest = {
        install_npm: true,
        install_pip: true,
        install_plugins: !skipPlugins,
      };

      const result = await apiClient<DependencyInstallResult>(
        `/api/v1/backup/${backup.id}/install-dependencies`,
        {
          method: "POST",
          body: JSON.stringify(request),
        }
      );

      setDepResult(result);
    } catch (err) {
      console.error("Dependency installation failed:", err);
    } finally {
      setInstallingDeps(false);
    }
  };

  // Group files by type
  const groupedFiles = useMemo(() => {
    if (!plan) return { skills: [], plugins: [], mcp: [], agents: [], commands: [], other: [] };

    const groups = {
      skills: [] as string[],
      plugins: [] as string[],
      mcp: [] as string[],
      agents: [] as string[],
      commands: [] as string[],
      other: [] as string[],
    };

    plan.files_to_restore.forEach((file) => {
      if (file.includes("/skills/") || file.includes("\\skills\\")) {
        groups.skills.push(file);
      } else if (file.includes("/plugins/") || file.includes("\\plugins\\")) {
        groups.plugins.push(file);
      } else if (file.includes("mcp") || file.includes(".mcp.json")) {
        groups.mcp.push(file);
      } else if (file.includes("/agents/") || file.includes("\\agents\\")) {
        groups.agents.push(file);
      } else if (file.includes("/commands/") || file.includes("\\commands\\")) {
        groups.commands.push(file);
      } else {
        groups.other.push(file);
      }
    });

    return groups;
  }, [plan]);

  const renderStepContent = () => {
    if (!backup) return null;

    if (loadingPlan) {
      return (
        <div className="flex flex-col items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary mb-4" />
          <p className="text-muted-foreground">Analyzing backup...</p>
        </div>
      );
    }

    switch (step) {
      // Step 0: Select/Review backup
      case 0:
        return (
          <div className="space-y-4">
            <div className="p-4 bg-muted rounded-lg">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <span className="text-muted-foreground">Name:</span>
                <span className="font-medium">{backup.name}</span>
                <span className="text-muted-foreground">Scope:</span>
                <span className="font-medium capitalize">{backup.scope}</span>
                <span className="text-muted-foreground">Size:</span>
                <span className="font-medium">{formatBytes(backup.size_bytes)}</span>
                <span className="text-muted-foreground">Created:</span>
                <span className="font-medium">{formatDate(backup.created_at)}</span>
              </div>
            </div>

            {plan && (
              <>
                {/* Platform info */}
                <div className="flex items-center gap-2 p-3 bg-muted/50 rounded-lg">
                  <Monitor className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm">
                    Created on{" "}
                    <span className="font-medium">
                      {PLATFORM_NAMES[plan.platform_backup] || plan.platform_backup}
                    </span>
                  </span>
                  {!plan.platform_compatible && (
                    <Badge variant="outline" className="ml-auto bg-amber-50 text-amber-700 border-amber-200">
                      <AlertTriangle className="h-3 w-3 mr-1" />
                      Different OS
                    </Badge>
                  )}
                </div>

                {/* Warnings */}
                {plan.warnings.map((warning, i) => (
                  <div
                    key={i}
                    className={`flex items-start gap-2 p-3 rounded-lg ${
                      warning.severity === "error"
                        ? "bg-red-50 border border-red-200"
                        : "bg-amber-50 border border-amber-200"
                    }`}
                  >
                    <AlertTriangle
                      className={`h-4 w-4 mt-0.5 ${
                        warning.severity === "error" ? "text-red-600" : "text-amber-600"
                      }`}
                    />
                    <span className="text-sm">{warning.message}</span>
                  </div>
                ))}

                {/* Summary badges */}
                <div className="flex flex-wrap gap-2">
                  {plan.skills_to_restore.length > 0 && (
                    <Badge variant="secondary">
                      <Package className="h-3 w-3 mr-1" />
                      {plan.skills_to_restore.length} Skills
                    </Badge>
                  )}
                  {plan.plugins_to_restore.length > 0 && (
                    <Badge variant="secondary">
                      <Puzzle className="h-3 w-3 mr-1" />
                      {plan.plugins_to_restore.length} Plugins
                    </Badge>
                  )}
                  {plan.mcp_servers_to_restore.length > 0 && (
                    <Badge variant="secondary">
                      <Server className="h-3 w-3 mr-1" />
                      {plan.mcp_servers_to_restore.length} MCP Servers
                    </Badge>
                  )}
                  {plan.has_dependencies && (
                    <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200">
                      <Download className="h-3 w-3 mr-1" />
                      Has dependencies
                    </Badge>
                  )}
                </div>
              </>
            )}
          </div>
        );

      // Step 1: Review contents
      case 1:
        return (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              This backup contains {plan?.files_to_restore.length || 0} files:
            </p>

            <ScrollArea className="h-[300px] border rounded-lg p-3">
              <div className="space-y-4">
                {groupedFiles.skills.length > 0 && (
                  <div>
                    <h4 className="font-medium flex items-center gap-2 mb-2">
                      <Package className="h-4 w-4 text-green-600" />
                      Skills ({groupedFiles.skills.length})
                    </h4>
                    {plan?.skills_to_restore.map((skill) => (
                      <div key={skill.name} className="ml-6 py-1 text-sm">
                        <span className="font-mono">{skill.name}</span>
                        {skill.dependencies.length > 0 && (
                          <span className="ml-2 text-muted-foreground">
                            ({skill.dependencies.length} deps)
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {groupedFiles.plugins.length > 0 && (
                  <div>
                    <h4 className="font-medium flex items-center gap-2 mb-2">
                      <Puzzle className="h-4 w-4 text-purple-600" />
                      Plugins ({plan?.plugins_to_restore.length})
                    </h4>
                    {plan?.plugins_to_restore.map((plugin) => (
                      <div key={plugin.name} className="ml-6 py-1 text-sm">
                        <span className="font-mono">{plugin.name}</span>
                        {plugin.version && (
                          <span className="ml-2 text-muted-foreground">v{plugin.version}</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {groupedFiles.mcp.length > 0 && (
                  <div>
                    <h4 className="font-medium flex items-center gap-2 mb-2">
                      <Server className="h-4 w-4 text-blue-600" />
                      MCP Servers ({plan?.mcp_servers_to_restore.length})
                    </h4>
                    {plan?.mcp_servers_to_restore.map((server) => (
                      <div key={server.name} className="ml-6 py-1 text-sm">
                        <span className="font-mono">{server.name}</span>
                        <Badge variant="outline" className="ml-2 text-xs">
                          {server.type}
                        </Badge>
                      </div>
                    ))}
                  </div>
                )}

                {groupedFiles.agents.length > 0 && (
                  <div>
                    <h4 className="font-medium flex items-center gap-2 mb-2">
                      <Bot className="h-4 w-4 text-orange-600" />
                      Agents ({groupedFiles.agents.length})
                    </h4>
                    {groupedFiles.agents.map((file) => (
                      <div key={file} className="ml-6 py-1 text-sm font-mono text-muted-foreground">
                        {file.split("/").pop()}
                      </div>
                    ))}
                  </div>
                )}

                {groupedFiles.commands.length > 0 && (
                  <div>
                    <h4 className="font-medium flex items-center gap-2 mb-2">
                      <Terminal className="h-4 w-4 text-cyan-600" />
                      Commands ({groupedFiles.commands.length})
                    </h4>
                    {groupedFiles.commands.map((file) => (
                      <div key={file} className="ml-6 py-1 text-sm font-mono text-muted-foreground">
                        {file.split("/").pop()}
                      </div>
                    ))}
                  </div>
                )}

                {groupedFiles.other.length > 0 && (
                  <div>
                    <h4 className="font-medium flex items-center gap-2 mb-2">
                      <FileCode className="h-4 w-4 text-gray-600" />
                      Config Files ({groupedFiles.other.length})
                    </h4>
                    {groupedFiles.other.map((file) => (
                      <div key={file} className="ml-6 py-1 text-sm font-mono text-muted-foreground">
                        {file}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </ScrollArea>
          </div>
        );

      // Step 2: Choose components
      case 2:
        return (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Choose which components to restore. Uncheck items you want to skip.
            </p>

            <div className="flex items-center gap-2 pb-2 border-b">
              <Checkbox
                id="select-all"
                checked={selectAll}
                onCheckedChange={(checked) => handleSelectAllFiles(checked === true)}
              />
              <Label htmlFor="select-all" className="font-medium">
                Select All ({plan?.files_to_restore.length} files)
              </Label>
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 border rounded-lg">
                <div className="flex items-center gap-2">
                  <Package className="h-4 w-4 text-green-600" />
                  <span>Skills</span>
                  <Badge variant="outline">{plan?.skills_to_restore.length || 0}</Badge>
                </div>
                <Switch
                  checked={!skipSkills}
                  onCheckedChange={(checked) => setSkipSkills(!checked)}
                />
              </div>

              <div className="flex items-center justify-between p-3 border rounded-lg">
                <div className="flex items-center gap-2">
                  <Puzzle className="h-4 w-4 text-purple-600" />
                  <span>Plugins</span>
                  <Badge variant="outline">{plan?.plugins_to_restore.length || 0}</Badge>
                </div>
                <Switch
                  checked={!skipPlugins}
                  onCheckedChange={(checked) => setSkipPlugins(!checked)}
                />
              </div>
            </div>

            {!selectAll && (
              <ScrollArea className="h-[200px] border rounded-lg p-3">
                <div className="space-y-2">
                  {plan?.files_to_restore.map((file) => (
                    <div key={file} className="flex items-center gap-2">
                      <Checkbox
                        id={file}
                        checked={selectedFiles.has(file)}
                        onCheckedChange={() => handleFileToggle(file)}
                      />
                      <Label htmlFor={file} className="font-mono text-xs truncate">
                        {file}
                      </Label>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            )}
          </div>
        );

      // Step 3: Dependencies
      case 3:
        return (
          <div className="space-y-4">
            {plan?.has_dependencies ? (
              <>
                <p className="text-sm text-muted-foreground">
                  The following dependencies need to be installed after restore:
                </p>

                <ScrollArea className="h-[200px] border rounded-lg p-3">
                  <div className="space-y-2">
                    {plan.dependencies.map((dep, i) => (
                      <div
                        key={`${dep.kind}-${dep.name}-${i}`}
                        className="flex items-center gap-2 py-1"
                      >
                        <Badge
                          variant="outline"
                          className={DEPENDENCY_KINDS[dep.kind]?.color || ""}
                        >
                          {DEPENDENCY_KINDS[dep.kind]?.label || dep.kind}
                        </Badge>
                        <span className="font-mono text-sm">{dep.name}</span>
                        {dep.version && (
                          <span className="text-muted-foreground text-sm">@{dep.version}</span>
                        )}
                        {dep.source && (
                          <span className="text-muted-foreground text-xs">from {dep.source}</span>
                        )}
                      </div>
                    ))}
                  </div>
                </ScrollArea>

                <div className="flex items-center justify-between p-3 bg-muted rounded-lg">
                  <div>
                    <p className="font-medium">Auto-install dependencies</p>
                    <p className="text-sm text-muted-foreground">
                      Run npm/pip install after restore
                    </p>
                  </div>
                  <Switch
                    checked={installDependencies}
                    onCheckedChange={setInstallDependencies}
                  />
                </div>

                {plan.manual_steps.length > 0 && (
                  <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg">
                    <h4 className="font-medium text-amber-800 flex items-center gap-2">
                      <AlertCircle className="h-4 w-4" />
                      Manual Steps Required
                    </h4>
                    <ul className="mt-2 text-sm text-amber-700 list-disc list-inside">
                      {plan.manual_steps.map((step, i) => (
                        <li key={i}>{step}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            ) : (
              <div className="text-center py-8">
                <Check className="h-12 w-12 text-green-500 mx-auto mb-4" />
                <h3 className="font-medium text-lg">No Dependencies Required</h3>
                <p className="text-muted-foreground mt-1">
                  This backup contains only configuration files.
                </p>
              </div>
            )}
          </div>
        );

      // Step 4: Confirm
      case 4:
        return (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">Review your restore settings:</p>

            <div className="p-4 bg-muted rounded-lg space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Backup:</span>
                <span className="font-medium">{backup.name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Files:</span>
                <span className="font-medium">
                  {selectAll ? plan?.files_to_restore.length : selectedFiles.size} files
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Skip skills:</span>
                <span className="font-medium">{skipSkills ? "Yes" : "No"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Skip plugins:</span>
                <span className="font-medium">{skipPlugins ? "Yes" : "No"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Install deps:</span>
                <span className="font-medium">
                  {installDependencies && plan?.has_dependencies ? "Yes" : "No"}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2 p-3 border rounded-lg">
              <Checkbox
                id="dry-run"
                checked={dryRun}
                onCheckedChange={(checked) => setDryRun(checked === true)}
              />
              <Label htmlFor="dry-run" className="cursor-pointer">
                <span className="font-medium">Dry run</span>
                <p className="text-xs text-muted-foreground">
                  Preview what would be restored without making changes
                </p>
              </Label>
            </div>

            {!dryRun && (
              <div className="flex items-center gap-2 p-3 bg-destructive/10 rounded-lg">
                <AlertTriangle className="h-4 w-4 text-destructive" />
                <span className="text-sm text-destructive">
                  Existing files will be overwritten. This cannot be undone.
                </span>
              </div>
            )}
          </div>
        );

      // Step 5: Results
      case 5:
        return (
          <div className="space-y-4">
            {restoreResult && (
              <>
                <div
                  className={`p-4 rounded-lg flex items-start gap-3 ${
                    restoreResult.success
                      ? "bg-green-50 border border-green-200"
                      : "bg-red-50 border border-red-200"
                  }`}
                >
                  {restoreResult.success ? (
                    <CheckCircle2 className="h-5 w-5 text-green-600 mt-0.5" />
                  ) : (
                    <XCircle className="h-5 w-5 text-red-600 mt-0.5" />
                  )}
                  <div>
                    <h4 className="font-medium">
                      {restoreResult.dry_run ? "Dry Run Complete" : "Restore Complete"}
                    </h4>
                    <p className="text-sm mt-1">{restoreResult.message}</p>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="p-4 bg-muted rounded-lg text-center">
                    <p className="text-2xl font-bold">{restoreResult.files_restored}</p>
                    <p className="text-sm text-muted-foreground">
                      Files {restoreResult.dry_run ? "would be" : ""} restored
                    </p>
                  </div>
                  <div className="p-4 bg-muted rounded-lg text-center">
                    <p className="text-2xl font-bold">{restoreResult.files_skipped}</p>
                    <p className="text-sm text-muted-foreground">Files skipped</p>
                  </div>
                </div>
              </>
            )}

            {installingDeps && (
              <div className="flex items-center justify-center gap-2 p-4">
                <Loader2 className="h-5 w-5 animate-spin" />
                <span>Installing dependencies...</span>
              </div>
            )}

            {depResult && (
              <div className="space-y-2">
                <h4 className="font-medium">Dependency Installation</h4>
                <div className="space-y-1">
                  {depResult.installed.map((dep, i) => (
                    <div key={i} className="flex items-center gap-2 text-sm">
                      <CheckCircle2 className="h-4 w-4 text-green-600" />
                      <span>{dep.name}</span>
                      <Badge variant="outline" className="text-xs">
                        {dep.kind}
                      </Badge>
                    </div>
                  ))}
                  {depResult.failed.map((dep, i) => (
                    <div key={i} className="flex items-center gap-2 text-sm">
                      <XCircle className="h-4 w-4 text-red-600" />
                      <span>{dep.name}</span>
                      <Badge variant="outline" className="text-xs">
                        {dep.kind}
                      </Badge>
                      <span className="text-muted-foreground">{dep.message}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {restoreResult?.manual_steps && restoreResult.manual_steps.length > 0 && (
              <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg">
                <h4 className="font-medium text-amber-800">Manual Steps</h4>
                <ul className="mt-2 text-sm text-amber-700 list-disc list-inside">
                  {restoreResult.manual_steps.map((step, i) => (
                    <li key={i} className="font-mono text-xs">
                      {step}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        );

      default:
        return null;
    }
  };

  const canProceed = () => {
    switch (step) {
      case 0:
        return plan !== null && !loadingPlan;
      case 2:
        return selectAll || selectedFiles.size > 0;
      case 5:
        return true; // Results step - just close
      default:
        return true;
    }
  };

  const isLastStep = step === STEPS.length - 2; // Step 4 is confirm, step 5 is results
  const isResultsStep = step === STEPS.length - 1;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[550px]">
        <DialogHeader>
          <DialogTitle>Restore Backup</DialogTitle>
          <DialogDescription>
            Step {step + 1} of {STEPS.length}: {STEPS[step].description}
          </DialogDescription>
        </DialogHeader>

        {!isResultsStep && (
          <div className="space-y-2">
            <Progress value={((step + 1) / STEPS.length) * 100} />
            <div className="flex justify-between text-xs text-muted-foreground">
              {STEPS.map((s, i) => (
                <span
                  key={i}
                  className={i <= step ? "text-primary font-medium" : ""}
                >
                  {s.title}
                </span>
              ))}
            </div>
          </div>
        )}

        {error && (
          <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-md flex items-center gap-2">
            <AlertCircle className="h-4 w-4" />
            {error}
          </div>
        )}

        <div className="py-4 min-h-[300px]">{renderStepContent()}</div>

        <DialogFooter className="flex justify-between">
          {!isResultsStep ? (
            <>
              <Button variant="outline" onClick={handleBack} disabled={step === 0}>
                <ChevronLeft className="h-4 w-4 mr-2" />
                Back
              </Button>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => handleOpenChange(false)}>
                  Cancel
                </Button>
                {isLastStep ? (
                  <Button
                    variant={dryRun ? "secondary" : "destructive"}
                    onClick={handleRestore}
                    disabled={restoring || !canProceed()}
                  >
                    {restoring ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        Restoring...
                      </>
                    ) : dryRun ? (
                      "Preview Restore"
                    ) : (
                      "Restore Backup"
                    )}
                  </Button>
                ) : (
                  <Button onClick={handleNext} disabled={!canProceed()}>
                    Next
                    <ChevronRight className="h-4 w-4 ml-2" />
                  </Button>
                )}
              </div>
            </>
          ) : (
            <Button onClick={() => handleOpenChange(false)} className="ml-auto">
              <X className="h-4 w-4 mr-2" />
              Close
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
