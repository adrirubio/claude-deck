import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
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
import {
  type AgentCreate,
  type AgentScope,
  AGENT_TOOLS,
  AGENT_MODELS,
} from "@/types/agents";

interface AgentWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (agent: AgentCreate) => Promise<void>;
}

const STEPS = [
  { title: "Name & Scope", description: "Choose a name and where to save" },
  { title: "Tools", description: "Select available tools" },
  { title: "Model", description: "Choose the AI model" },
  { title: "System Prompt", description: "Define agent behavior" },
];

export function AgentWizard({ open, onOpenChange, onCreate }: AgentWizardProps) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<AgentScope>("user");
  const [description, setDescription] = useState("");
  const [tools, setTools] = useState<string[]>([]);
  const [model, setModel] = useState<string>("sonnet");
  const [prompt, setPrompt] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resetForm = () => {
    setStep(0);
    setName("");
    setScope("user");
    setDescription("");
    setTools([]);
    setModel("sonnet");
    setPrompt("");
    setError(null);
  };

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      resetForm();
    }
    onOpenChange(open);
  };

  const handleToolToggle = (toolName: string, checked: boolean) => {
    if (checked) {
      setTools([...tools, toolName]);
    } else {
      setTools(tools.filter((t) => t !== toolName));
    }
  };

  const canProceed = () => {
    switch (step) {
      case 0:
        return name.trim().length > 0;
      case 1:
        return true; // Tools are optional
      case 2:
        return true; // Model is pre-selected
      case 3:
        return prompt.trim().length > 0;
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
        tools: tools.length > 0 ? tools : undefined,
        model: model || undefined,
        prompt: prompt.trim(),
      });
      handleOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create agent");
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
              <Label htmlFor="name">Agent Name</Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="my-custom-agent"
                pattern="[a-z0-9-]+"
              />
              <p className="text-xs text-muted-foreground">
                Use lowercase letters, numbers, and hyphens only
              </p>
            </div>

            {/* Scope */}
            <div className="space-y-2">
              <Label>Scope</Label>
              <RadioGroup value={scope} onValueChange={(v) => setScope(v as AgentScope)}>
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
                placeholder="A brief description of what this agent does"
              />
            </div>
          </div>
        );

      case 1:
        return (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Select the tools this agent can use. Leave empty to allow all tools.
            </p>
            <div className="grid grid-cols-2 gap-2 max-h-[300px] overflow-y-auto p-4 border rounded-md">
              {AGENT_TOOLS.map((tool) => (
                <div key={tool.name} className="flex items-center space-x-2">
                  <Checkbox
                    id={`wizard-tool-${tool.name}`}
                    checked={tools.includes(tool.name)}
                    onCheckedChange={(checked) =>
                      handleToolToggle(tool.name, checked as boolean)
                    }
                  />
                  <label
                    htmlFor={`wizard-tool-${tool.name}`}
                    className="text-sm cursor-pointer"
                  >
                    <span className="font-medium">{tool.name}</span>
                    <span className="text-muted-foreground block text-xs">
                      {tool.description}
                    </span>
                  </label>
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              {tools.length === 0
                ? "No tools selected (agent will have access to all tools)"
                : `${tools.length} tool${tools.length > 1 ? "s" : ""} selected`}
            </p>
          </div>
        );

      case 2:
        return (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Select the Claude model this agent should use.
            </p>
            <RadioGroup value={model} onValueChange={setModel}>
              {AGENT_MODELS.map((m) => (
                <div
                  key={m.value}
                  className="flex items-center space-x-2 p-3 border rounded-md hover:bg-muted/50"
                >
                  <RadioGroupItem value={m.value} id={`model-${m.value}`} />
                  <label htmlFor={`model-${m.value}`} className="flex-1 cursor-pointer">
                    <span className="font-medium">{m.label}</span>
                    <p className="text-sm text-muted-foreground">
                      {m.description}
                    </p>
                  </label>
                </div>
              ))}
            </RadioGroup>
          </div>
        );

      case 3:
        return (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Write the system prompt that defines this agent's behavior and
              capabilities.
            </p>
            <Textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={`You are a specialized agent that...

Your core responsibilities:
1. ...
2. ...

When working on tasks:
- ...
- ...`}
              className="min-h-[300px] font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">
              This will be saved as the markdown content of the agent file
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
          <DialogTitle>Create New Agent</DialogTitle>
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
                {creating ? "Creating..." : "Create Agent"}
              </Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
