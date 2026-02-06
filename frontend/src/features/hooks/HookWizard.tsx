import { useState } from "react";
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
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  HOOK_EVENTS,
  HOOK_TEMPLATES,
  MATCHER_EXAMPLES,
  HOOK_ENV_VARS,
  AGENT_MODELS,
  type HookEvent,
  type HookType,
  type HookTemplate,
} from "@/types/hooks";
import { ChevronDown, ChevronRight, Info, Check, Terminal, MessageSquare, Bot } from "lucide-react";

interface HookWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (hook: {
    event: HookEvent;
    matcher?: string;
    type: HookType;
    command?: string;
    prompt?: string;
    model?: string;
    async_?: boolean;
    statusMessage?: string;
    once?: boolean;
    timeout?: number;
    scope: "user" | "project";
  }) => Promise<void>;
}

export function HookWizard({ open, onOpenChange, onCreate }: HookWizardProps) {
  const [step, setStep] = useState(1);
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
  const [scope, setScope] = useState<"user" | "project">("user");
  const [creating, setCreating] = useState(false);
  const [showMatcherHelp, setShowMatcherHelp] = useState(false);
  const [showEnvHelp, setShowEnvHelp] = useState(false);

  const resetForm = () => {
    setStep(1);
    setEvent("PreToolUse");
    setMatcher("");
    setType("command");
    setCommand("");
    setPrompt("");
    setModel("haiku");
    setAsyncRun(false);
    setStatusMessage("");
    setOnce(false);
    setTimeout(undefined);
    setScope("user");
    setShowMatcherHelp(false);
    setShowEnvHelp(false);
  };

  const handleCreate = async () => {
    setCreating(true);
    try {
      const hook: {
        event: HookEvent;
        matcher?: string;
        type: HookType;
        command?: string;
        prompt?: string;
        model?: string;
        async_?: boolean;
        statusMessage?: string;
        once?: boolean;
        timeout?: number;
        scope: "user" | "project";
      } = {
        event,
        matcher: matcher || undefined,
        type,
        scope,
        timeout,
      };

      if (type === "command") {
        hook.command = command;
      } else {
        hook.prompt = prompt;
        if (type === "agent") {
          hook.model = model;
        }
      }

      // Add optional fields
      if (asyncRun) hook.async_ = true;
      if (statusMessage) hook.statusMessage = statusMessage;
      if (once) hook.once = true;

      await onCreate(hook);
      resetForm();
      onOpenChange(false);
    } finally {
      setCreating(false);
    }
  };

  const applyTemplate = (template: HookTemplate) => {
    setEvent(template.event);
    setType(template.type);
    setMatcher(template.matcher || "");
    setCommand(template.command || "");
    setPrompt(template.prompt || "");
    setModel(template.model || "haiku");
    setAsyncRun(template.async_ || false);
    setStatusMessage(template.statusMessage || "");
    setOnce(template.once || false);
    setTimeout(template.timeout);
  };

  const canProceed = () => {
    if (step === 1) return true; // Event selection always valid
    if (step === 2) return true; // Matcher is optional
    if (step === 3) {
      if (type === "command") return command.trim() !== "";
      return prompt.trim() !== ""; // prompt and agent both need prompt
    }
    if (step === 4) return true; // Scope selection always valid
    return false;
  };

  const getTypeIcon = (t: HookType) => {
    switch (t) {
      case "command":
        return <Terminal className="h-4 w-4" />;
      case "prompt":
        return <MessageSquare className="h-4 w-4" />;
      case "agent":
        return <Bot className="h-4 w-4" />;
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o);
        if (!o) resetForm();
      }}
    >
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Create New Hook</DialogTitle>
          <DialogDescription>
            Step {step} of 4 - Configure your Claude Code hook
          </DialogDescription>
        </DialogHeader>

        {/* Progress Bar */}
        <div className="w-full bg-muted h-2 rounded-full overflow-hidden">
          <div
            className="bg-primary h-full transition-all duration-300"
            style={{ width: `${(step / 4) * 100}%` }}
          />
        </div>

        <div className="space-y-6 py-4">
          {/* Step 1: Select Event Type */}
          {step === 1 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-lg font-medium mb-2">
                  Step 1: Select Event Type
                </h3>
                <p className="text-sm text-muted-foreground">
                  Choose when your hook should be triggered
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {HOOK_EVENTS.map((e) => (
                  <button
                    key={e.name}
                    onClick={() => setEvent(e.name)}
                    className={`p-4 border-2 rounded-lg text-left transition-all ${
                      event === e.name
                        ? "border-primary bg-primary/5"
                        : "border-muted hover:border-primary/50"
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-2xl">{e.icon}</span>
                          <span className="font-medium">{e.label}</span>
                        </div>
                        <p className="text-sm text-muted-foreground">
                          {e.description}
                        </p>
                      </div>
                      {event === e.name && (
                        <Check className="h-5 w-5 text-primary flex-shrink-0 ml-2" />
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Step 2: Configure Matcher */}
          {step === 2 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-lg font-medium mb-2">
                  Step 2: Configure Matcher (Optional)
                </h3>
                <p className="text-sm text-muted-foreground">
                  Specify which tools or patterns this hook should match
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="matcher-wizard">
                  Matcher Pattern
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
                  id="matcher-wizard"
                  value={matcher}
                  onChange={(e) => setMatcher(e.target.value)}
                  placeholder="Leave empty to match all tools"
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
            </div>
          )}

          {/* Step 3: Choose Type and Configure */}
          {step === 3 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-lg font-medium mb-2">
                  Step 3: Choose Type and Configure
                </h3>
                <p className="text-sm text-muted-foreground">
                  Select the hook type and configure its behavior
                </p>
              </div>

              {/* Type Toggle */}
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

              {/* Type description */}
              <p className="text-sm text-muted-foreground">
                {type === "command" && "Execute a shell command when the hook triggers."}
                {type === "prompt" && "Append a prompt to Claude's context when the hook triggers."}
                {type === "agent" && "Spawn a subagent to process the hook with a specific model."}
              </p>

              {/* Templates */}
              <div className="space-y-2">
                <Label>Quick Start Templates</Label>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {HOOK_TEMPLATES.filter(
                    (t) => t.type === type || t.name === "Blank Hook"
                  ).map((template) => (
                    <button
                      key={template.name}
                      onClick={() => applyTemplate(template)}
                      className="p-3 border rounded-lg text-left hover:bg-muted transition-colors"
                    >
                      <div className="font-medium text-sm flex items-center gap-2">
                        {getTypeIcon(template.type)}
                        {template.name}
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">
                        {template.description}
                      </p>
                    </button>
                  ))}
                </div>
              </div>

              {/* Command input */}
              {type === "command" && (
                <div className="space-y-2">
                  <Label htmlFor="command-wizard">
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
                    id="command-wizard"
                    value={command}
                    onChange={(e) => setCommand(e.target.value)}
                    rows={6}
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
                  <Label htmlFor="prompt-wizard">Prompt</Label>
                  <textarea
                    id="prompt-wizard"
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    rows={6}
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
                  <Label htmlFor="model-wizard">Agent Model</Label>
                  <Select value={model} onValueChange={setModel}>
                    <SelectTrigger id="model-wizard">
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
            </div>
          )}

          {/* Step 4: Advanced Options */}
          {step === 4 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-lg font-medium mb-2">
                  Step 4: Scope and Advanced Options
                </h3>
                <p className="text-sm text-muted-foreground">
                  Configure where the hook is stored and additional settings
                </p>
              </div>

              {/* Scope Selection */}
              <div className="space-y-2">
                <Label>Scope</Label>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    onClick={() => setScope("user")}
                    className={`p-4 border-2 rounded-lg text-left transition-all ${
                      scope === "user"
                        ? "border-primary bg-primary/5"
                        : "border-muted hover:border-primary/50"
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="font-medium mb-1">User</div>
                        <p className="text-sm text-muted-foreground">
                          ~/.claude/settings.json
                        </p>
                        <p className="text-xs text-muted-foreground mt-1">
                          Available in all projects
                        </p>
                      </div>
                      {scope === "user" && (
                        <Check className="h-5 w-5 text-primary flex-shrink-0 ml-2" />
                      )}
                    </div>
                  </button>

                  <button
                    onClick={() => setScope("project")}
                    className={`p-4 border-2 rounded-lg text-left transition-all ${
                      scope === "project"
                        ? "border-primary bg-primary/5"
                        : "border-muted hover:border-primary/50"
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="font-medium mb-1">Project</div>
                        <p className="text-sm text-muted-foreground">
                          .claude/settings.json
                        </p>
                        <p className="text-xs text-muted-foreground mt-1">
                          Only in this project
                        </p>
                      </div>
                      {scope === "project" && (
                        <Check className="h-5 w-5 text-primary flex-shrink-0 ml-2" />
                      )}
                    </div>
                  </button>
                </div>
              </div>

              {/* Advanced Options */}
              <div className="space-y-4 border rounded-lg p-4">
                <h4 className="font-medium">Advanced Options</h4>
                
                {/* Async toggle */}
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="async-wizard">Run Async</Label>
                    <p className="text-sm text-muted-foreground">
                      Run the hook in the background without blocking
                    </p>
                  </div>
                  <Switch
                    id="async-wizard"
                    checked={asyncRun}
                    onCheckedChange={setAsyncRun}
                  />
                </div>

                {/* Once toggle */}
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="once-wizard">Run Once</Label>
                    <p className="text-sm text-muted-foreground">
                      Only run this hook once per session
                    </p>
                  </div>
                  <Switch
                    id="once-wizard"
                    checked={once}
                    onCheckedChange={setOnce}
                  />
                </div>

                {/* Status Message */}
                <div className="space-y-2">
                  <Label htmlFor="status-message-wizard">
                    Status Message (optional)
                  </Label>
                  <Input
                    id="status-message-wizard"
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
                    <Label htmlFor="timeout-wizard">
                      Timeout (seconds, optional)
                    </Label>
                    <Input
                      id="timeout-wizard"
                      type="number"
                      min="1"
                      max="300"
                      value={timeout || ""}
                      onChange={(e) =>
                        setTimeout(
                          e.target.value ? parseInt(e.target.value) : undefined
                        )
                      }
                      placeholder="30"
                    />
                    <p className="text-sm text-muted-foreground">
                      Command will be killed if it runs longer than this timeout.
                    </p>
                  </div>
                )}
              </div>

              {/* Review Summary */}
              <div className="bg-muted p-4 rounded-lg space-y-2">
                <h4 className="font-medium flex items-center gap-2">
                  <Info className="h-4 w-4" />
                  Review Your Hook
                </h4>
                <div className="space-y-1 text-sm">
                  <div>
                    <span className="text-muted-foreground">Event:</span>{" "}
                    <Badge variant="secondary">
                      {HOOK_EVENTS.find((e) => e.name === event)?.label}
                    </Badge>
                  </div>
                  {matcher && (
                    <div>
                      <span className="text-muted-foreground">Matcher:</span>{" "}
                      <code className="bg-background px-2 py-1 rounded">
                        {matcher}
                      </code>
                    </div>
                  )}
                  <div className="flex items-center gap-2">
                    <span className="text-muted-foreground">Type:</span>{" "}
                    <Badge variant="outline" className="flex items-center gap-1">
                      {getTypeIcon(type)}
                      {type}
                    </Badge>
                  </div>
                  {type === "agent" && (
                    <div>
                      <span className="text-muted-foreground">Model:</span>{" "}
                      <Badge variant="outline">{model}</Badge>
                    </div>
                  )}
                  <div>
                    <span className="text-muted-foreground">Scope:</span>{" "}
                    <Badge>{scope}</Badge>
                  </div>
                  {asyncRun && (
                    <div>
                      <Badge variant="outline">Async</Badge>
                    </div>
                  )}
                  {once && (
                    <div>
                      <Badge variant="outline">Once per session</Badge>
                    </div>
                  )}
                  {statusMessage && (
                    <div>
                      <span className="text-muted-foreground">Status:</span>{" "}
                      "{statusMessage}"
                    </div>
                  )}
                  {timeout && (
                    <div>
                      <span className="text-muted-foreground">Timeout:</span>{" "}
                      {timeout}s
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Navigation */}
        <div className="flex gap-2">
          {step > 1 && (
            <Button
              variant="outline"
              onClick={() => setStep(step - 1)}
              disabled={creating}
            >
              Back
            </Button>
          )}
          {step < 4 ? (
            <Button
              onClick={() => setStep(step + 1)}
              disabled={!canProceed()}
              className="flex-1"
            >
              Next
            </Button>
          ) : (
            <Button
              onClick={handleCreate}
              disabled={creating || !canProceed()}
              className="flex-1"
            >
              {creating ? "Creating..." : "Create Hook"}
            </Button>
          )}
          <Button
            variant="outline"
            onClick={() => {
              resetForm();
              onOpenChange(false);
            }}
            disabled={creating}
          >
            Cancel
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
