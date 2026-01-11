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
import {
  HOOK_EVENTS,
  HOOK_TEMPLATES,
  MATCHER_EXAMPLES,
  HOOK_ENV_VARS,
  type HookEvent,
  type HookType,
  type HookTemplate,
} from "@/types/hooks";
import { ChevronDown, ChevronRight, Info, Check } from "lucide-react";

interface HookWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (hook: {
    event: HookEvent;
    matcher?: string;
    type: HookType;
    command?: string;
    prompt?: string;
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
      }

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
    setTimeout(template.timeout);
  };

  const canProceed = () => {
    if (step === 1) return true; // Event selection always valid
    if (step === 2) return true; // Matcher is optional
    if (step === 3) {
      return type === "command" ? command.trim() !== "" : prompt.trim() !== "";
    }
    if (step === 4) return true; // Scope selection always valid
    return false;
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
                  Select whether to run a command or append a prompt
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
                  Command
                </Button>
                <Button
                  type="button"
                  variant={type === "prompt" ? "default" : "outline"}
                  className="flex-1"
                  onClick={() => setType("prompt")}
                >
                  Prompt
                </Button>
              </div>

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
                      <div className="font-medium text-sm">
                        {template.name}
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">
                        {template.description}
                      </p>
                    </button>
                  ))}
                </div>
              </div>

              {/* Command or Prompt */}
              {type === "command" ? (
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
              ) : (
                <div className="space-y-2">
                  <Label htmlFor="prompt-wizard">Prompt</Label>
                  <textarea
                    id="prompt-wizard"
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    rows={6}
                    className="w-full px-3 py-2 border rounded-md text-sm"
                    placeholder="Remember to follow security best practices..."
                  />
                  <p className="text-sm text-muted-foreground">
                    This prompt will be appended to Claude's context when the
                    hook is triggered.
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
                  <div>
                    <span className="text-muted-foreground">Type:</span>{" "}
                    <Badge variant="outline">{type}</Badge>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Scope:</span>{" "}
                    <Badge>{scope}</Badge>
                  </div>
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
