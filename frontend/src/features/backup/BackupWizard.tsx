import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { ChevronLeft, ChevronRight, Globe, User, FolderOpen, Check } from "lucide-react";
import { type BackupCreate, type BackupScope, BACKUP_SCOPES } from "@/types/backup";

interface BackupWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (backup: BackupCreate) => Promise<void>;
  currentProjectPath?: string;
}

const STEPS = [
  { title: "Name", description: "Name your backup" },
  { title: "Scope", description: "Select what to backup" },
  { title: "Confirm", description: "Review and create" },
];

export function BackupWizard({
  open,
  onOpenChange,
  onCreate,
  currentProjectPath,
}: BackupWizardProps) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [scope, setScope] = useState<BackupScope>("user");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const resetForm = () => {
    setStep(0);
    setName("");
    setDescription("");
    setScope("user");
    setError(null);
    setSuccess(false);
  };

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      resetForm();
    }
    onOpenChange(open);
  };

  const generateDefaultName = () => {
    const date = new Date();
    const dateStr = date.toISOString().slice(0, 10).replace(/-/g, "");
    return `backup-${scope}-${dateStr}`;
  };

  const canProceed = () => {
    switch (step) {
      case 0:
        return name.trim().length > 0;
      case 1:
        // Full and project scopes require a project path
        if ((scope === "full" || scope === "project") && !currentProjectPath) {
          return false;
        }
        return true;
      case 2:
        return true;
      default:
        return false;
    }
  };

  const handleNext = () => {
    if (step === 0 && !name.trim()) {
      setName(generateDefaultName());
    }
    if (step < STEPS.length - 1) {
      setStep(step + 1);
    }
  };

  const handleBack = () => {
    if (step > 0) {
      setStep(step - 1);
    }
  };

  const handleCreate = async () => {
    setCreating(true);
    setError(null);
    try {
      await onCreate({
        name: name.trim() || generateDefaultName(),
        description: description.trim() || undefined,
        scope,
        project_path: scope !== "user" ? currentProjectPath : undefined,
      });
      setSuccess(true);
      setTimeout(() => {
        handleOpenChange(false);
      }, 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create backup");
    } finally {
      setCreating(false);
    }
  };

  const getScopeIcon = (scopeValue: BackupScope) => {
    switch (scopeValue) {
      case "full":
        return <Globe className="h-5 w-5" />;
      case "user":
        return <User className="h-5 w-5" />;
      case "project":
        return <FolderOpen className="h-5 w-5" />;
    }
  };

  const renderStepContent = () => {
    if (success) {
      return (
        <div className="text-center py-8">
          <div className="mx-auto w-12 h-12 rounded-full bg-success/10 flex items-center justify-center mb-4">
            <Check className="h-6 w-6 text-success" />
          </div>
          <h3 className="text-lg font-semibold">Backup Created!</h3>
          <p className="text-muted-foreground mt-2">
            Your backup has been created successfully.
          </p>
        </div>
      );
    }

    switch (step) {
      case 0:
        return (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">Backup Name</Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={generateDefaultName()}
              />
              <p className="text-xs text-muted-foreground">
                A descriptive name for this backup
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="description">Description (optional)</Label>
              <Textarea
                id="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional notes about this backup..."
                className="min-h-[80px]"
              />
            </div>
          </div>
        );

      case 1:
        return (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Select what configuration files to include in the backup.
            </p>
            <RadioGroup
              value={scope}
              onValueChange={(v) => setScope(v as BackupScope)}
            >
              {BACKUP_SCOPES.map((s) => {
                const isDisabled = (s.value === "full" || s.value === "project") && !currentProjectPath;
                return (
                  <div
                    key={s.value}
                    className={`flex items-center space-x-2 p-3 border rounded-md ${
                      isDisabled ? "opacity-50" : "hover:bg-muted/50"
                    }`}
                  >
                    <RadioGroupItem
                      value={s.value}
                      id={`scope-${s.value}`}
                      disabled={isDisabled}
                    />
                    <label
                      htmlFor={`scope-${s.value}`}
                      className={`flex-1 ${isDisabled ? "" : "cursor-pointer"}`}
                    >
                      <div className="flex items-center gap-2">
                        {getScopeIcon(s.value)}
                        <span className="font-medium">{s.label}</span>
                      </div>
                      <p className="text-sm text-muted-foreground">
                        {s.description}
                      </p>
                      {isDisabled && (
                        <p className="text-xs text-destructive mt-1">
                          No project selected
                        </p>
                      )}
                    </label>
                  </div>
                );
              })}
            </RadioGroup>
          </div>
        );

      case 2:
        return (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Review your backup settings before creating.
            </p>
            <div className="space-y-2 p-4 bg-muted rounded-md">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Name:</span>
                <span className="font-medium">
                  {name.trim() || generateDefaultName()}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Scope:</span>
                <span className="font-medium capitalize">{scope}</span>
              </div>
              {description && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Description:</span>
                  <span className="font-medium">{description}</span>
                </div>
              )}
              {scope !== "user" && currentProjectPath && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Project:</span>
                  <span className="font-medium text-sm truncate max-w-[200px]">
                    {currentProjectPath}
                  </span>
                </div>
              )}
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
          <DialogTitle>Create Backup</DialogTitle>
          <DialogDescription>
            {success
              ? "Backup completed"
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
                <Button onClick={handleNext} disabled={!canProceed()}>
                  Next
                  <ChevronRight className="h-4 w-4 ml-2" />
                </Button>
              ) : (
                <Button onClick={handleCreate} disabled={creating}>
                  {creating ? "Creating..." : "Create Backup"}
                </Button>
              )}
            </div>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
