import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { AlertTriangle, Check, File, ChevronLeft, ChevronRight } from "lucide-react";
import { apiClient } from "@/lib/api";
import { type Backup, type BackupContentsResponse, formatBytes, formatDate } from "@/types/backup";

interface RestoreWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  backup: Backup | null;
  onRestore: (backup: Backup) => Promise<void>;
}

const STEPS = [
  { title: "Preview", description: "Review backup contents" },
  { title: "Warning", description: "Understand the implications" },
  { title: "Confirm", description: "Confirm restore" },
];

export function RestoreWizard({
  open,
  onOpenChange,
  backup,
  onRestore,
}: RestoreWizardProps) {
  const [step, setStep] = useState(0);
  const [files, setFiles] = useState<string[]>([]);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    if (open && backup) {
      fetchBackupContents();
    }
  }, [open, backup]);

  const fetchBackupContents = async () => {
    if (!backup) return;

    setLoadingFiles(true);
    try {
      const response = await apiClient<BackupContentsResponse>(
        `/api/v1/backup/${backup.id}/contents`
      );
      setFiles(response.files);
    } catch (err) {
      setError("Failed to load backup contents");
    } finally {
      setLoadingFiles(false);
    }
  };

  const resetForm = () => {
    setStep(0);
    setFiles([]);
    setError(null);
    setSuccess(false);
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

  const handleRestore = async () => {
    if (!backup) return;

    setRestoring(true);
    setError(null);
    try {
      await onRestore(backup);
      setSuccess(true);
      setTimeout(() => {
        handleOpenChange(false);
      }, 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to restore backup");
    } finally {
      setRestoring(false);
    }
  };

  const renderStepContent = () => {
    if (!backup) return null;

    if (success) {
      return (
        <div className="text-center py-8">
          <div className="mx-auto w-12 h-12 rounded-full bg-success/10 flex items-center justify-center mb-4">
            <Check className="h-6 w-6 text-success" />
          </div>
          <h3 className="text-lg font-semibold">Restore Complete!</h3>
          <p className="text-muted-foreground mt-2">
            Your configuration has been restored successfully.
          </p>
        </div>
      );
    }

    switch (step) {
      case 0:
        return (
          <div className="space-y-4">
            <div className="p-4 bg-muted rounded-md">
              <div className="grid grid-cols-2 gap-2 text-sm">
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

            <div>
              <h4 className="font-medium mb-2">Files ({files.length})</h4>
              {loadingFiles ? (
                <div className="text-center py-4 text-muted-foreground">
                  Loading files...
                </div>
              ) : (
                <div className="max-h-[200px] overflow-y-auto border rounded-md p-2">
                  {files.map((file) => (
                    <div
                      key={file}
                      className="flex items-center gap-2 py-1 text-sm"
                    >
                      <File className="h-4 w-4 text-muted-foreground" />
                      <span className="font-mono text-xs truncate">{file}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        );

      case 1:
        return (
          <div className="space-y-4">
            <div className="flex items-start gap-3 p-4 bg-amber-50 border border-amber-200 rounded-md">
              <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
              <div className="text-sm">
                <h4 className="font-semibold text-amber-800">Warning</h4>
                <p className="text-amber-700 mt-1">
                  Restoring this backup will overwrite existing configuration
                  files. Any changes made since the backup was created will be
                  lost.
                </p>
              </div>
            </div>

            <div className="space-y-2 text-sm">
              <h4 className="font-medium">This will affect:</h4>
              <ul className="list-disc list-inside text-muted-foreground space-y-1">
                {backup.scope === "full" && (
                  <>
                    <li>User-level settings and configuration</li>
                    <li>User commands, agents, and skills</li>
                    <li>Project-level configuration</li>
                  </>
                )}
                {backup.scope === "user" && (
                  <>
                    <li>User-level settings and configuration</li>
                    <li>User commands, agents, and skills</li>
                    <li>User plugins configuration</li>
                  </>
                )}
                {backup.scope === "project" && (
                  <>
                    <li>Project .claude directory</li>
                    <li>Project MCP configuration</li>
                    <li>Project CLAUDE.md</li>
                  </>
                )}
              </ul>
            </div>
          </div>
        );

      case 2:
        return (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              You are about to restore the following backup:
            </p>
            <div className="p-4 bg-muted rounded-md space-y-2">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Backup:</span>
                <span className="font-medium">{backup.name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Files:</span>
                <span className="font-medium">{files.length} files</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Size:</span>
                <span className="font-medium">{formatBytes(backup.size_bytes)}</span>
              </div>
            </div>
            <div className="flex items-center gap-2 p-3 bg-destructive/10 rounded-md">
              <AlertTriangle className="h-4 w-4 text-destructive" />
              <span className="text-sm text-destructive">
                This action cannot be undone
              </span>
            </div>
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Restore Backup</DialogTitle>
          <DialogDescription>
            {success
              ? "Restore completed"
              : `Step ${step + 1} of ${STEPS.length}: ${STEPS[step].description}`}
          </DialogDescription>
        </DialogHeader>

        {!success && (
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
          <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-md">
            {error}
          </div>
        )}

        <div className="py-4">{renderStepContent()}</div>

        {!success && (
          <DialogFooter className="flex justify-between">
            <Button
              variant="outline"
              onClick={handleBack}
              disabled={step === 0}
            >
              <ChevronLeft className="h-4 w-4 mr-2" />
              Back
            </Button>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => handleOpenChange(false)}>
                Cancel
              </Button>
              {step < STEPS.length - 1 ? (
                <Button onClick={handleNext}>
                  Next
                  <ChevronRight className="h-4 w-4 ml-2" />
                </Button>
              ) : (
                <Button
                  variant="destructive"
                  onClick={handleRestore}
                  disabled={restoring}
                >
                  {restoring ? "Restoring..." : "Restore Backup"}
                </Button>
              )}
            </div>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
