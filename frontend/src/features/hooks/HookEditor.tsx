import { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import {
  HOOK_EVENTS,
  MATCHER_EXAMPLES,
  HOOK_ENV_VARS,
  AGENT_MODELS,
  type Hook,
  type HookEvent,
  type HookType,
} from "@/types/hooks";
import { ChevronDown, ChevronRight, Info, Terminal, MessageSquare, Bot } from "lucide-react";

interface HookEditorProps {
  hook: Hook | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (
    hookId: string,
    scope: "user" | "project",
    updates: {
      event?: HookEvent;
      matcher?: string;
      type?: HookType;
      command?: string;
      prompt?: string;
      model?: string;
      async_?: boolean;
      statusMessage?: string;
      once?: boolean;
      timeout?: number;
    }
  ) => Promise<void>;
}

export function HookEditor({
  hook,
  open,
  onOpenChange,
  onSave,
}: HookEditorProps) {
  const [event, setEvent] = useState<HookEvent>("PreToolUse");
  const [matcher, setMatcher] = useState("");
  const [type, setType] = useState<HookType>("command");
  const [command, setCommand] = useState("");
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState("haiku");
  const [asyncRun, setAsyncRun] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [once, setOnce] = useState(false);
  const [timeout, setTimeout] = useState<number | undefined>(undefined);
  const [saving, setSaving] = useState(false);
  const [showMatcherHelp, setShowMatcherHelp] = useState(false);
  const [showEnvHelp, setShowEnvHelp] = useState(false);

  useEffect(() => {
    if (hook) {
      setEvent(hook.event);
      setMatcher(hook.matcher || "");
      setType(hook.type);
      setCommand(hook.command || "");
      setPrompt(hook.prompt || "");
      setModel(hook.model || "haiku");
      setAsyncRun(hook.async_ || false);
      setStatusMessage(hook.statusMessage || "");
      setOnce(hook.once || false);
      setTimeout(hook.timeout);
    }
  }, [hook]);

  const handleSave = async () => {
    if (!hook) return;

    setSaving(true);
    try {
      const updates: {
        event?: HookEvent;
        matcher?: string;
        type?: HookType;
        command?: string;
        prompt?: string;
        model?: string;
        async_?: boolean;
        statusMessage?: string;
        once?: boolean;
        timeout?: number;
      } = {
        event,
        matcher: matcher || undefined,
        type,
        timeout,
      };

      if (type === "command") {
        updates.command = command;
        updates.prompt = undefined;
        updates.model = undefined;
      } else {
        updates.prompt = prompt;
        updates.command = undefined;
        if (type === "agent") {
          updates.model = model;
        } else {
          updates.model = undefined;
        }
      }

      // Add optional fields
      updates.async_ = asyncRun;
      updates.statusMessage = statusMessage || undefined;
      updates.once = once;

      await onSave(hook.id, hook.scope, updates);
      onOpenChange(false);
    } finally {
      setSaving(false);
    }
  };

  if (!hook) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Edit Hook</DialogTitle>
          <DialogDescription>
            Modify hook configuration for {hook.event}
            <Badge variant="secondary" className="ml-2">
              {hook.scope}
            </Badge>
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Event Type */}
          <div className="space-y-2">
            <Label htmlFor="event">Event Type</Label>
            <Select value={event} onValueChange={(v) => setEvent(v as HookEvent)}>
              <SelectTrigger id="event">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {HOOK_EVENTS.map((e) => (
                  <SelectItem key={e.name} value={e.name}>
                    {e.icon} {e.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-sm text-muted-foreground">
              {HOOK_EVENTS.find((e) => e.name === event)?.description}
            </p>
          </div>

          {/* Matcher */}
          <div className="space-y-2">
            <Label htmlFor="matcher">
              Matcher Pattern (optional)
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="ml-2 h-6 w-6 p-0"
                onClick={() => setShowMatcherHelp(!showMatcherHelp)}
              >
                {showMatcherHelp ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
              </Button>
            </Label>
            <Input
              id="matcher"
              value={matcher}
              onChange={(e) => setMatcher(e.target.value)}
              placeholder="e.g., Write(*.py)"
            />
            {showMatcherHelp && (
              <div className="bg-muted p-3 rounded text-sm space-y-2">
                <p className="font-medium flex items-center gap-2">
                  <Info className="h-4 w-4" />
                  Pattern Examples:
                </p>
                {MATCHER_EXAMPLES.map((ex) => (
                  <div key={ex.pattern} className="ml-6">
                    <code className="bg-background px-2 py-1 rounded">
                      {ex.pattern}
                    </code>
                    <span className="ml-2 text-muted-foreground">
                      - {ex.description}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Type Toggle */}
          <div className="space-y-2">
            <Label>Hook Type</Label>
            <div className="flex gap-2">
              <Button
                type="button"
                variant={type === "command" ? "default" : "outline"}
                className="flex-1"
                onClick={() => setType("command")}
              >
                <Terminal className="h-4 w-4 mr-2" />
                Command
              </Button>
              <Button
                type="button"
                variant={type === "prompt" ? "default" : "outline"}
                className="flex-1"
                onClick={() => setType("prompt")}
              >
                <MessageSquare className="h-4 w-4 mr-2" />
                Prompt
              </Button>
              <Button
                type="button"
                variant={type === "agent" ? "default" : "outline"}
                className="flex-1"
                onClick={() => setType("agent")}
              >
                <Bot className="h-4 w-4 mr-2" />
                Agent
              </Button>
            </div>
            <p className="text-sm text-muted-foreground">
              {type === "command" && "Execute a shell command when the hook triggers."}
              {type === "prompt" && "Append a prompt to Claude's context when the hook triggers."}
              {type === "agent" && "Spawn a subagent to process the hook with a specific model."}
            </p>
          </div>

          {/* Command input */}
          {type === "command" && (
            <div className="space-y-2">
              <Label htmlFor="command">
                Command
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="ml-2 h-6 w-6 p-0"
                  onClick={() => setShowEnvHelp(!showEnvHelp)}
                >
                  {showEnvHelp ? (
                    <ChevronDown className="h-4 w-4" />
                  ) : (
                    <ChevronRight className="h-4 w-4" />
                  )}
                </Button>
              </Label>
              <textarea
                id="command"
                value={command}
                onChange={(e) => setCommand(e.target.value)}
                rows={4}
                className="w-full px-3 py-2 border rounded-md font-mono text-sm"
                placeholder="echo 'Running tool: $CLAUDE_TOOL_NAME'"
              />
              {showEnvHelp && (
                <div className="bg-muted p-3 rounded text-sm space-y-2">
                  <p className="font-medium flex items-center gap-2">
                    <Info className="h-4 w-4" />
                    Available Environment Variables:
                  </p>
                  {HOOK_ENV_VARS.map((env) => (
                    <div key={env.name} className="ml-6">
                      <code className="bg-background px-2 py-1 rounded">
                        {env.name}
                      </code>
                      <span className="ml-2 text-muted-foreground">
                        - {env.description}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Prompt input (for both prompt and agent types) */}
          {(type === "prompt" || type === "agent") && (
            <div className="space-y-2">
              <Label htmlFor="prompt">Prompt</Label>
              <textarea
                id="prompt"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={4}
                className="w-full px-3 py-2 border rounded-md text-sm"
                placeholder={type === "agent" 
                  ? "Instructions for the agent to execute..."
                  : "Remember to follow security best practices..."}
              />
              <p className="text-sm text-muted-foreground">
                {type === "prompt" && "This prompt will be appended to Claude's context when the hook is triggered."}
                {type === "agent" && "This prompt will be sent to the subagent for processing."}
              </p>
            </div>
          )}

          {/* Model selector for agent type */}
          {type === "agent" && (
            <div className="space-y-2">
              <Label htmlFor="model">Agent Model</Label>
              <Select value={model} onValueChange={setModel}>
                <SelectTrigger id="model">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {AGENT_MODELS.map((m) => (
                    <SelectItem key={m.value} value={m.value}>
                      {m.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-sm text-muted-foreground">
                Choose which Claude model the agent should use.
              </p>
            </div>
          )}

          {/* Advanced Options */}
          <div className="space-y-4 border rounded-lg p-4">
            <h4 className="font-medium">Advanced Options</h4>
            
            {/* Async toggle */}
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label htmlFor="async-edit">Run Async</Label>
                <p className="text-sm text-muted-foreground">
                  Run the hook in the background without blocking
                </p>
              </div>
              <Switch
                id="async-edit"
                checked={asyncRun}
                onCheckedChange={setAsyncRun}
              />
            </div>

            {/* Once toggle */}
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label htmlFor="once-edit">Run Once</Label>
                <p className="text-sm text-muted-foreground">
                  Only run this hook once per session
                </p>
              </div>
              <Switch
                id="once-edit"
                checked={once}
                onCheckedChange={setOnce}
              />
            </div>

            {/* Status Message */}
            <div className="space-y-2">
              <Label htmlFor="status-message-edit">
                Status Message (optional)
              </Label>
              <Input
                id="status-message-edit"
                value={statusMessage}
                onChange={(e) => setStatusMessage(e.target.value)}
                placeholder="Custom spinner message..."
              />
              <p className="text-sm text-muted-foreground">
                Custom message to show while the hook is running.
              </p>
            </div>

            {/* Timeout (only for command type) */}
            {type === "command" && (
              <div className="space-y-2">
                <Label htmlFor="timeout">Timeout (seconds, optional)</Label>
                <Input
                  id="timeout"
                  type="number"
                  min="1"
                  max="300"
                  value={timeout || ""}
                  onChange={(e) =>
                    setTimeout(e.target.value ? parseInt(e.target.value) : undefined)
                  }
                  placeholder="30"
                />
                <p className="text-sm text-muted-foreground">
                  Command will be killed if it runs longer than this timeout.
                </p>
              </div>
            )}
          </div>
        </div>

        <div className="flex gap-2">
          <Button
            onClick={handleSave}
            disabled={saving || (type === "command" ? !command : !prompt)}
            className="flex-1"
          >
            {saving ? "Saving..." : "Save Changes"}
          </Button>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            Cancel
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
