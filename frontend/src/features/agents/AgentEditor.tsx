import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { MarkdownPreviewToggle } from "@/components/shared/MarkdownPreviewToggle";
import { MODAL_SIZES } from "@/lib/constants";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ChevronDown, Wrench, Shield, BookOpen, HardDrive, X } from "lucide-react";
import {
  type Agent,
  type AgentUpdate,
  type PermissionMode,
  type MemoryScope,
  type Skill,
  type SkillListResponse,
  AGENT_TOOLS,
  AGENT_MODELS,
  PERMISSION_MODES,
  MEMORY_SCOPES,
} from "@/types/agents";
import { apiClient, buildEndpoint } from "@/lib/api";

interface AgentEditorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agent: Agent | null;
  onSave: (update: AgentUpdate) => Promise<void>;
}

export function AgentEditor({
  open,
  onOpenChange,
  agent,
  onSave,
}: AgentEditorProps) {
  const [description, setDescription] = useState("");
  const [model, setModel] = useState<string>("");
  const [tools, setTools] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("");
  const [saving, setSaving] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // New subagent management fields
  const [disallowedTools, setDisallowedTools] = useState<string[]>([]);
  const [permissionMode, setPermissionMode] = useState<PermissionMode | "">("");
  const [skills, setSkills] = useState<string[]>([]);
  const [memory, setMemory] = useState<MemoryScope | "">("");
  const [newDisallowedTool, setNewDisallowedTool] = useState("");
  const [availableSkills, setAvailableSkills] = useState<Skill[]>([]);

  // Fetch available skills for multi-select
  const fetchSkills = useCallback(async () => {
    try {
      const response = await apiClient<SkillListResponse>(buildEndpoint("agents/skills"));
      setAvailableSkills(response.skills);
    } catch {
      // Silently fail - skills list is optional
    }
  }, []);

  useEffect(() => {
    if (open) {
      fetchSkills();
    }
  }, [open, fetchSkills]);

  // Reset form when agent changes
  useEffect(() => {
    if (agent) {
      setDescription(agent.description || "");
      setModel(agent.model || "");
      setTools(agent.tools || []);
      setPrompt(agent.prompt || "");
      // New fields
      setDisallowedTools(agent.disallowed_tools || []);
      setPermissionMode(agent.permission_mode || "");
      setSkills(agent.skills || []);
      setMemory(agent.memory || "");
    }
  }, [agent]);

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

  const handleSave = async () => {
    if (!agent) return;

    setSaving(true);
    try {
      await onSave({
        description: description || undefined,
        model: model || undefined,
        tools: tools.length > 0 ? tools : undefined,
        prompt,
        // New subagent fields
        disallowed_tools: disallowedTools.length > 0 ? disallowedTools : undefined,
        permission_mode: permissionMode || undefined,
        skills: skills.length > 0 ? skills : undefined,
        memory: memory || undefined,
      });
      onOpenChange(false);
    } catch {
      // Error handled by parent
    } finally {
      setSaving(false);
    }
  };

  if (!agent) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={`${MODAL_SIZES.LG} overflow-y-auto`}>
        <DialogHeader>
          <DialogTitle>Edit Agent: {agent.name}</DialogTitle>
          <DialogDescription>
            Modify the agent's configuration and system prompt
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Description */}
          <div className="space-y-2">
            <Label htmlFor="description">Description</Label>
            <Input
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="A brief description of what this agent does"
            />
          </div>

          {/* Model Selection */}
          <div className="space-y-2">
            <Label>Model</Label>
            <Select
              value={model || "__default__"}
              onValueChange={(value) => setModel(value === "__default__" ? "" : value)}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select a model (optional)" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__default__">
                  <span className="text-muted-foreground">Default (inherit)</span>
                </SelectItem>
                {AGENT_MODELS.map((m) => (
                  <SelectItem key={m.value} value={m.value}>
                    <span className="flex items-center gap-2">
                      <span>{m.label}</span>
                      <span className="text-muted-foreground text-sm">
                        - {m.description}
                      </span>
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Tools Selection */}
          <Collapsible open={showTools} onOpenChange={setShowTools}>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" className="w-full justify-start">
                <Wrench className="h-4 w-4 mr-2" />
                Tools ({tools.length} selected)
                <ChevronDown
                  className={`h-4 w-4 ml-auto transition-transform ${
                    showTools ? "rotate-180" : ""
                  }`}
                />
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-2">
              <div className="grid grid-cols-2 gap-2 p-4 border rounded-md">
                {AGENT_TOOLS.map((tool) => (
                  <div key={tool.name} className="flex items-center space-x-2">
                    <Checkbox
                      id={`tool-${tool.name}`}
                      checked={tools.includes(tool.name)}
                      onCheckedChange={(checked) =>
                        handleToolToggle(tool.name, checked as boolean)
                      }
                    />
                    <label
                      htmlFor={`tool-${tool.name}`}
                      className="text-sm cursor-pointer"
                    >
                      <span className="font-medium">{tool.name}</span>
                      <span className="text-muted-foreground ml-1">
                        - {tool.description}
                      </span>
                    </label>
                  </div>
                ))}
              </div>
            </CollapsibleContent>
          </Collapsible>

          {/* Advanced Subagent Settings */}
          <Collapsible open={showAdvanced} onOpenChange={setShowAdvanced}>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" className="w-full justify-start">
                <Shield className="h-4 w-4 mr-2" />
                Advanced Subagent Settings
                <ChevronDown
                  className={`h-4 w-4 ml-auto transition-transform ${
                    showAdvanced ? "rotate-180" : ""
                  }`}
                />
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-2 space-y-4 p-4 border rounded-md">
              {/* Permission Mode */}
              <div className="space-y-2">
                <Label className="flex items-center gap-2">
                  <Shield className="h-4 w-4" />
                  Permission Mode
                </Label>
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
                        <span className="flex items-center gap-2">
                          <span>{mode.label}</span>
                          <span className="text-muted-foreground text-sm">
                            - {mode.description}
                          </span>
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Memory Scope */}
              <div className="space-y-2">
                <Label className="flex items-center gap-2">
                  <HardDrive className="h-4 w-4" />
                  Memory Scope
                </Label>
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
                        <span className="flex items-center gap-2">
                          <span>{scope.label}</span>
                          <span className="text-muted-foreground text-sm">
                            - {scope.description}
                          </span>
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Skills to Preload */}
              <div className="space-y-2">
                <Label className="flex items-center gap-2">
                  <BookOpen className="h-4 w-4" />
                  Skills to Preload ({skills.length} selected)
                </Label>
                {availableSkills.length > 0 ? (
                  <div className="grid grid-cols-2 gap-2 max-h-[150px] overflow-y-auto p-2 border rounded-md">
                    {availableSkills.map((skill: Skill) => (
                      <div key={skill.name} className="flex items-center space-x-2">
                        <Checkbox
                          id={`skill-${skill.name}`}
                          checked={skills.includes(skill.name)}
                          onCheckedChange={(checked) =>
                            handleSkillToggle(skill.name, checked as boolean)
                          }
                        />
                        <label
                          htmlFor={`skill-${skill.name}`}
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
                <p className="text-xs text-muted-foreground">
                  Tools that this agent is not allowed to use
                </p>
              </div>
            </CollapsibleContent>
          </Collapsible>

          {/* System Prompt */}
          <div className="space-y-2">
            <Label>System Prompt</Label>
            <MarkdownPreviewToggle
              value={prompt}
              onChange={setPrompt}
              placeholder="The system prompt that defines this agent's behavior..."
              minHeight="300px"
            />
            <p className="text-xs text-muted-foreground">
              This is the markdown content of the agent definition file
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "Saving..." : "Save Changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
