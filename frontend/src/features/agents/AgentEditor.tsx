import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
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
import { ChevronDown, Wrench } from "lucide-react";
import {
  type Agent,
  type AgentUpdate,
  AGENT_TOOLS,
  AGENT_MODELS,
} from "@/types/agents";

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

  // Reset form when agent changes
  useEffect(() => {
    if (agent) {
      setDescription(agent.description || "");
      setModel(agent.model || "");
      setTools(agent.tools || []);
      setPrompt(agent.prompt || "");
    }
  }, [agent]);

  const handleToolToggle = (toolName: string, checked: boolean) => {
    if (checked) {
      setTools([...tools, toolName]);
    } else {
      setTools(tools.filter((t) => t !== toolName));
    }
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
      });
      onOpenChange(false);
    } catch (error) {
      // Error handled by parent
    } finally {
      setSaving(false);
    }
  };

  if (!agent) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[700px] max-h-[90vh] overflow-y-auto">
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

          {/* System Prompt */}
          <div className="space-y-2">
            <Label htmlFor="prompt">System Prompt</Label>
            <Textarea
              id="prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="The system prompt that defines this agent's behavior..."
              className="min-h-[300px] font-mono text-sm"
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
