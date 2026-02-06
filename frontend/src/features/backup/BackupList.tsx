import { useState } from "react";
import {
  Download,
  Trash2,
  RotateCcw,
  Archive,
  User,
  FolderOpen,
  Globe,
  Package,
  FileCode,
  Eye,
  Loader2,
  Monitor,
  AlertTriangle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { apiClient } from "@/lib/api";
import {
  type Backup,
  type BackupScope,
  type RestorePlan,
  formatBytes,
  formatDate,
  PLATFORM_NAMES,
  DEPENDENCY_KINDS,
} from "@/types/backup";

interface BackupListProps {
  backups: Backup[];
  onRestore: (backup: Backup) => void;
  onDownload: (backup: Backup) => void;
  onDelete: (backup: Backup) => void;
}

// Get current platform
const getCurrentPlatform = () => {
  const platform = navigator.platform.toLowerCase();
  if (platform.includes("mac")) return "darwin";
  if (platform.includes("win")) return "win32";
  return "linux";
};

export function BackupList({ backups, onRestore, onDownload, onDelete }: BackupListProps) {
  const [planDialogOpen, setPlanDialogOpen] = useState(false);
  const [selectedBackup, setSelectedBackup] = useState<Backup | null>(null);
  const [loadingPlan, setLoadingPlan] = useState(false);
  const [plan, setPlan] = useState<RestorePlan | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);

  // Platform detection for future use
  const _currentPlatform = getCurrentPlatform();
  void _currentPlatform; // Silence unused warning

  const getScopeIcon = (scope: BackupScope) => {
    switch (scope) {
      case "full":
        return <Globe className="h-4 w-4" />;
      case "user":
        return <User className="h-4 w-4" />;
      case "project":
        return <FolderOpen className="h-4 w-4" />;
    }
  };

  const getScopeBadgeVariant = (scope: BackupScope) => {
    switch (scope) {
      case "full":
        return "default" as const;
      case "user":
        return "secondary" as const;
      case "project":
        return "outline" as const;
    }
  };

  const handleViewPlan = async (backup: Backup) => {
    setSelectedBackup(backup);
    setPlanDialogOpen(true);
    setLoadingPlan(true);
    setPlanError(null);
    setPlan(null);

    try {
      const response = await apiClient<RestorePlan>(`/api/v1/backup/${backup.id}/plan`);
      setPlan(response);
    } catch (err) {
      setPlanError(err instanceof Error ? err.message : "Failed to load plan");
    } finally {
      setLoadingPlan(false);
    }
  };

  if (backups.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <Archive className="h-12 w-12 mx-auto mb-4 opacity-50" />
        <p className="text-lg">No backups found</p>
        <p className="text-sm mt-1">Create your first backup to get started</p>
      </div>
    );
  }

  return (
    <>
      <div className="space-y-4">
        {backups.map((backup) => (
            <Card key={backup.id} className="hover:bg-muted/50 transition-colors">
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between">
                  <div>
                    <CardTitle className="text-lg flex items-center gap-2">
                      <Archive className="h-5 w-5 text-primary" />
                      {backup.name}
                    </CardTitle>
                    {backup.description && (
                      <CardDescription className="mt-1">
                        {backup.description}
                      </CardDescription>
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleViewPlan(backup)}
                      title="View restore plan"
                    >
                      <Eye className="h-4 w-4" />
                    </Button>

                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => onDownload(backup)}
                      title="Download backup"
                    >
                      <Download className="h-4 w-4" />
                    </Button>

                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => onRestore(backup)}
                      title="Restore backup"
                    >
                      <RotateCcw className="h-4 w-4" />
                    </Button>

                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="text-destructive hover:text-destructive"
                          title="Delete backup"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>Delete Backup</AlertDialogTitle>
                          <AlertDialogDescription>
                            Are you sure you want to delete this backup? This action
                            cannot be undone.
                            <br />
                            <br />
                            <strong>Backup:</strong> {backup.name}
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancel</AlertDialogCancel>
                          <AlertDialogAction
                            onClick={() => onDelete(backup)}
                            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                          >
                            Delete
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-2 text-sm">
                  <Badge
                    variant={getScopeBadgeVariant(backup.scope)}
                    className="flex items-center gap-1"
                  >
                    {getScopeIcon(backup.scope)}
                    {backup.scope.charAt(0).toUpperCase() + backup.scope.slice(1)}
                  </Badge>

                  <Badge variant="outline">{formatBytes(backup.size_bytes)}</Badge>

                  {/* Dependency indicator */}
                  {backup.has_dependencies ? (
                    <Badge
                      variant="outline"
                      className="bg-blue-50 text-blue-700 border-blue-200 flex items-center gap-1"
                    >
                      <Package className="h-3 w-3" />
                      Has dependencies
                    </Badge>
                  ) : (
                    <Badge
                      variant="outline"
                      className="bg-gray-50 text-gray-600 border-gray-200 flex items-center gap-1"
                    >
                      <FileCode className="h-3 w-3" />
                      Config only
                    </Badge>
                  )}

                  {/* Component counts */}
                  {backup.skill_count !== undefined && backup.skill_count > 0 && (
                    <Badge variant="outline" className="text-xs">
                      {backup.skill_count} skill{backup.skill_count !== 1 ? "s" : ""}
                    </Badge>
                  )}
                  {backup.plugin_count !== undefined && backup.plugin_count > 0 && (
                    <Badge variant="outline" className="text-xs">
                      {backup.plugin_count} plugin{backup.plugin_count !== 1 ? "s" : ""}
                    </Badge>
                  )}

                  <span className="text-muted-foreground ml-auto">
                    {formatDate(backup.created_at)}
                  </span>
                </div>
              </CardContent>
            </Card>
        ))}
      </div>

      {/* View Plan Dialog */}
      <Dialog open={planDialogOpen} onOpenChange={setPlanDialogOpen}>
        <DialogContent className="sm:max-w-[550px]">
          <DialogHeader>
            <DialogTitle>Restore Plan</DialogTitle>
            <DialogDescription>
              {selectedBackup?.name} - What will be restored
            </DialogDescription>
          </DialogHeader>

          {loadingPlan ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          ) : planError ? (
            <div className="text-center py-8 text-destructive">{planError}</div>
          ) : plan ? (
            <div className="space-y-4">
              {/* Platform info */}
              <div className="flex items-center gap-2 p-3 bg-muted rounded-lg">
                <Monitor className="h-4 w-4" />
                <span className="text-sm">
                  Created on{" "}
                  <span className="font-medium">
                    {PLATFORM_NAMES[plan.platform_backup] || plan.platform_backup}
                  </span>
                </span>
                {!plan.platform_compatible && (
                  <Badge
                    variant="outline"
                    className="ml-auto bg-amber-50 text-amber-700 border-amber-200"
                  >
                    <AlertTriangle className="h-3 w-3 mr-1" />
                    Different OS
                  </Badge>
                )}
              </div>

              {/* Warnings */}
              {plan.warnings.map((warning, i) => (
                <div
                  key={i}
                  className={`p-3 rounded-lg text-sm ${
                    warning.severity === "error"
                      ? "bg-red-50 text-red-700 border border-red-200"
                      : "bg-amber-50 text-amber-700 border border-amber-200"
                  }`}
                >
                  <AlertTriangle className="h-4 w-4 inline mr-2" />
                  {warning.message}
                </div>
              ))}

              {/* Summary */}
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="p-3 bg-muted rounded-lg">
                  <p className="text-2xl font-bold">{plan.files_to_restore.length}</p>
                  <p className="text-muted-foreground">Files</p>
                </div>
                <div className="p-3 bg-muted rounded-lg">
                  <p className="text-2xl font-bold">{plan.dependencies.length}</p>
                  <p className="text-muted-foreground">Dependencies</p>
                </div>
              </div>

              {/* Components */}
              <div className="space-y-2">
                <h4 className="font-medium text-sm">Components</h4>
                <div className="flex flex-wrap gap-2">
                  {plan.skills_to_restore.length > 0 && (
                    <Badge variant="secondary">
                      {plan.skills_to_restore.length} Skills
                    </Badge>
                  )}
                  {plan.plugins_to_restore.length > 0 && (
                    <Badge variant="secondary">
                      {plan.plugins_to_restore.length} Plugins
                    </Badge>
                  )}
                  {plan.mcp_servers_to_restore.length > 0 && (
                    <Badge variant="secondary">
                      {plan.mcp_servers_to_restore.length} MCP Servers
                    </Badge>
                  )}
                </div>
              </div>

              {/* Dependencies */}
              {plan.dependencies.length > 0 && (
                <div className="space-y-2">
                  <h4 className="font-medium text-sm">Dependencies to Install</h4>
                  <ScrollArea className="h-[120px] border rounded-lg p-2">
                    {plan.dependencies.map((dep, i) => (
                      <div
                        key={`${dep.kind}-${dep.name}-${i}`}
                        className="flex items-center gap-2 py-1 text-sm"
                      >
                        <Badge
                          variant="outline"
                          className={`text-xs ${
                            DEPENDENCY_KINDS[dep.kind]?.color || ""
                          }`}
                        >
                          {DEPENDENCY_KINDS[dep.kind]?.label || dep.kind}
                        </Badge>
                        <span className="font-mono">{dep.name}</span>
                        {dep.version && (
                          <span className="text-muted-foreground">@{dep.version}</span>
                        )}
                      </div>
                    ))}
                  </ScrollArea>
                </div>
              )}

              {/* Manual steps */}
              {plan.manual_steps.length > 0 && (
                <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg">
                  <h4 className="font-medium text-amber-800 text-sm">
                    Manual Steps Required
                  </h4>
                  <ul className="mt-2 text-sm text-amber-700 list-disc list-inside">
                    {plan.manual_steps.map((step, i) => (
                      <li key={i}>{step}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" onClick={() => setPlanDialogOpen(false)}>
                  Close
                </Button>
                <Button
                  onClick={() => {
                    setPlanDialogOpen(false);
                    if (selectedBackup) {
                      onRestore(selectedBackup);
                    }
                  }}
                >
                  <RotateCcw className="h-4 w-4 mr-2" />
                  Restore Now
                </Button>
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
