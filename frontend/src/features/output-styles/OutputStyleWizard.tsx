import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
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
import { ChevronLeft, ChevronRight, User, FolderOpen } from "lucide-react";
import { type OutputStyleCreate, type OutputStyleScope } from "@/types/output-styles";

interface OutputStyleWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (style: OutputStyleCreate) => Promise<void>;
}

const STEPS = [
  { title: "Name & Scope", description: "Choose a name and where to save" },
  { title: "Options", description: "Configure style options" },
  { title: "Instructions", description: "Write style instructions" },
];

export function OutputStyleWizard({ open, onOpenChange, onCreate }: OutputStyleWizardProps) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<OutputStyleScope>("user");
  const [description, setDescription] = useState("");
  const [keepCodingInstructions, setKeepCodingInstructions] = useState(false);
  const [content, setContent] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resetForm = () => {
    setStep(0);
    setName("");
    setScope("user");
    setDescription("");
    setKeepCodingInstructions(false);
    setContent("");
    setError(null);
  };

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      resetForm();
    }
    onOpenChange(open);
  };

  const canProceed = () => {
    switch (step) {
      case 0:
        return name.trim().length > 0;
      case 1:
        return true; // Options are all optional
      case 2:
        return content.trim().length > 0;
      default:
        return false;
    }
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

  const handleCreate = async () => {
    setCreating(true);
    setError(null);
    try {
      await onCreate({
        name: name.trim(),
        scope,
        description: description.trim() || undefined,
        keep_coding_instructions: keepCodingInstructions,
        content: content.trim(),
      });
      handleOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create output style");
    } finally {
      setCreating(false);
    }
  };

  const renderStepContent = () => {
    switch (step) {
      case 0:
        return (
          <div className="space-y-4">
            {/* Name */}
            <div className="space-y-2">
              <Label htmlFor="name">Style Name</Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="my-custom-style"
                pattern="[a-z0-9-]+"
              />
              <p className="text-xs text-muted-foreground">
                Use lowercase letters, numbers, and hyphens only
              </p>
            </div>

            {/* Scope */}
            <div className="space-y-2">
              <Label>Scope</Label>
              <RadioGroup value={scope} onValueChange={(v) => setScope(v as OutputStyleScope)}>
                <div className="flex items-center space-x-2 p-3 border rounded-md hover:bg-muted/50">
                  <RadioGroupItem value="user" id="scope-user" />
                  <label htmlFor="scope-user" className="flex-1 cursor-pointer">
                    <div className="flex items-center gap-2">
                      <User className="h-4 w-4" />
                      <span className="font-medium">User</span>
                    </div>
                    <p className="text-sm text-muted-foreground">
                      Available globally across all projects
                    </p>
                  </label>
                </div>
                <div className="flex items-center space-x-2 p-3 border rounded-md hover:bg-muted/50">
                  <RadioGroupItem value="project" id="scope-project" />
                  <label htmlFor="scope-project" className="flex-1 cursor-pointer">
                    <div className="flex items-center gap-2">
                      <FolderOpen className="h-4 w-4" />
                      <span className="font-medium">Project</span>
                    </div>
                    <p className="text-sm text-muted-foreground">
                      Only available in the current project
                    </p>
                  </label>
                </div>
              </RadioGroup>
            </div>

            {/* Description */}
            <div className="space-y-2">
              <Label htmlFor="description">Description (optional)</Label>
              <Input
                id="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="A brief description of this output style"
              />
            </div>
          </div>
        );

      case 1:
        return (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Configure optional settings for this output style.
            </p>

            {/* Keep Coding Instructions */}
            <div className="flex items-center justify-between rounded-lg border p-4">
              <div className="space-y-0.5">
                <Label htmlFor="keep-coding-instructions">
                  Keep Coding Instructions
                </Label>
                <p className="text-sm text-muted-foreground">
                  When enabled, Claude Code will retain its default coding-related
                  instructions alongside this style. Useful for maintaining code
                  quality while changing response format.
                </p>
              </div>
              <Switch
                id="keep-coding-instructions"
                checked={keepCodingInstructions}
                onCheckedChange={setKeepCodingInstructions}
              />
            </div>
          </div>
        );

      case 2:
        return (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Write markdown instructions that tell Claude how to format its
              responses when using this style.
            </p>
            <Textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder={`Write in a concise, technical style.

Use bullet points for lists.

Keep explanations brief and to the point.

Format code blocks with appropriate language tags.`}
              className="min-h-[300px] font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">
              This will be saved as the markdown content of the output style file
            </p>
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle>Create New Output Style</DialogTitle>
          <DialogDescription>
            Step {step + 1} of {STEPS.length}: {STEPS[step].description}
          </DialogDescription>
        </DialogHeader>

        {/* Progress */}
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

        {/* Error Display */}
        {error && (
          <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-md">
            {error}
          </div>
        )}

        {/* Step Content */}
        <div className="py-4">{renderStepContent()}</div>

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
              <Button onClick={handleCreate} disabled={!canProceed() || creating}>
                {creating ? "Creating..." : "Create Style"}
              </Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
