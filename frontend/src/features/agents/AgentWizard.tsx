import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import { ChevronLeft, ChevronRight, User, FolderOpen, X } from "lucide-react";
import {
  type AgentCreate,
  type AgentScope,
  type PermissionMode,
  type MemoryScope,
  type Skill,
  AGENT_TOOLS,
  AGENT_MODELS,
  PERMISSION_MODES,
  MEMORY_SCOPES,
} from "@/types/agents";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

interface AgentWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (agent: AgentCreate) => Promise<void>;
}

const STEPS = [
  { title: "Name & Scope", description: "Choose a name and where to save" },
  { title: "Tools", description: "Select available tools" },
  { title: "Model", description: "Choose the AI model" },
  { title: "Advanced", description: "Subagent settings (optional)" },
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

  // New subagent management fields
  const [disallowedTools, setDisallowedTools] = useState<string[]>([]);
  const [permissionMode, setPermissionMode] = useState<PermissionMode | "">("");
  const [skills, setSkills] = useState<string[]>([]);
  const [memory, setMemory] = useState<MemoryScope | "">("");
  const [newDisallowedTool, setNewDisallowedTool] = useState("");

  // Fetch available skills for multi-select
  const { data: skillsData } = useQuery({
    queryKey: ["skills"],
    queryFn: async () => {
      const response = await api.get<{ skills: Skill[] }>("/skills");
      return response.data.skills;
    },
    enabled: open,
  });

  const resetForm = () => {
    setStep(0);
    setName("");
    setScope("user");
    setDescription("");
    setTools([]);
    setModel("sonnet");
    setPrompt("");
    setError(null);
    // Reset new fields
    setDisallowedTools([]);
    setPermissionMode("");
    setSkills([]);
    setMemory("");
    setNewDisallowedTool("");
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

  const handleSkillToggle = (skillName: string, checked: boolean) => {
    if (checked) {
      setSkills([...skills, skillName]);
    } else {
      setSkills(skills.filter((s) => s !== skillName));
    }
  };

  const handleAddDisallowedTool = () => {
    const trimmed = newDisallowedTool.trim();
    if (trimmed && !disallowedTools.includes(trimmed)) {
      setDisallowedTools([...disallowedTools, trimmed]);
      setNewDisallowedTool("");
    }
  };

  const handleRemoveDisallowedTool = (tool: string) => {
    setDisallowedTools(disallowedTools.filter((t) => t !== tool));
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
        return true; // Advanced settings are optional
      case 4:
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
        // New subagent fields
        disallowed_tools: disallowedTools.length > 0 ? disallowedTools : undefined,
        permission_mode: permissionMode || undefined,
        skills: skills.length > 0 ? skills : undefined,
        memory: memory || undefined,
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
              Configure advanced subagent settings. All fields are optional.
            </p>

            {/* Permission Mode */}
            <div className="space-y-2">
              <Label>Permission Mode</Label>
              <Select
                value={permissionMode || "__default__"}
                onValueChange={(value) => setPermissionMode(value === "__default__" ? "" : value as PermissionMode)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select permission mode" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__default__">
                    <span className="text-muted-foreground">Default (inherit)</span>
                  </SelectItem>
                  {PERMISSION_MODES.map((mode) => (
                    <SelectItem key={mode.value} value={mode.value}>
                      {mode.label} - {mode.description}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Memory Scope */}
            <div className="space-y-2">
              <Label>Memory Scope</Label>
              <Select
                value={memory || "__none__"}
                onValueChange={(value) => setMemory(value === "__none__" ? "" : value as MemoryScope)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select memory scope" />
                </SelectTrigger>
                <SelectContent>
                  {MEMORY_SCOPES.map((scope) => (
                    <SelectItem key={scope.value} value={scope.value}>
                      {scope.label} - {scope.description}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Skills to Preload */}
            <div className="space-y-2">
              <Label>Skills to Preload ({skills.length} selected)</Label>
              {skillsData && skillsData.length > 0 ? (
                <div className="grid grid-cols-2 gap-2 max-h-[120px] overflow-y-auto p-2 border rounded-md">
                  {skillsData.map((skill) => (
                    <div key={skill.name} className="flex items-center space-x-2">
                      <Checkbox
                        id={`wizard-skill-${skill.name}`}
                        checked={skills.includes(skill.name)}
                        onCheckedChange={(checked) =>
                          handleSkillToggle(skill.name, checked as boolean)
                        }
                      />
                      <label
                        htmlFor={`wizard-skill-${skill.name}`}
                        className="text-sm cursor-pointer truncate"
                        title={skill.description || skill.name}
                      >
                        {skill.name}
                      </label>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No skills available</p>
              )}
            </div>

            {/* Disallowed Tools */}
            <div className="space-y-2">
              <Label>Disallowed Tools</Label>
              <div className="flex gap-2">
                <Input
                  value={newDisallowedTool}
                  onChange={(e) => setNewDisallowedTool(e.target.value)}
                  placeholder="Tool name to disallow"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleAddDisallowedTool();
                    }
                  }}
                />
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleAddDisallowedTool}
                >
                  Add
                </Button>
              </div>
              {disallowedTools.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-2">
                  {disallowedTools.map((tool) => (
                    <Badge key={tool} variant="secondary" className="flex items-center gap-1">
                      {tool}
                      <button
                        type="button"
                        onClick={() => handleRemoveDisallowedTool(tool)}
                        className="ml-1 hover:text-destructive"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          </div>
        );

      case 4:
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
