import { useState } from "react";
import type { MCPServerCreate } from "@/types/mcp";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { X } from "lucide-react";

interface MCPServerWizardProps {
  onSave: (server: MCPServerCreate) => Promise<void>;
  onCancel: () => void;
}

export function MCPServerWizard({ onSave, onCancel }: MCPServerWizardProps) {
  const [step, setStep] = useState(1);
  const [saving, setSaving] = useState(false);

  const [formData, setFormData] = useState<MCPServerCreate>({
    name: "",
    type: "stdio",
    scope: "user",
    command: "",
    args: [],
    url: "",
    headers: {},
    env: {},
  });

  const [argsInput, setArgsInput] = useState("");
  const [envKey, setEnvKey] = useState("");
  const [envValue, setEnvValue] = useState("");

  const handleNext = () => {
    if (step < 5) setStep(step + 1);
  };

  const handleBack = () => {
    if (step > 1) setStep(step - 1);
  };

  const handleSubmit = async () => {
    setSaving(true);
    try {
      // Parse args from space-separated string
      const parsedArgs = argsInput.trim() ? argsInput.trim().split(/\s+/) : [];

      await onSave({
        ...formData,
        args: parsedArgs.length > 0 ? parsedArgs : undefined,
      });
    } finally {
      setSaving(false);
    }
  };

  const addEnv = () => {
    if (envKey && envValue) {
      setFormData({
        ...formData,
        env: { ...formData.env, [envKey]: envValue },
      });
      setEnvKey("");
      setEnvValue("");
    }
  };

  const removeEnv = (key: string) => {
    const newEnv = { ...formData.env };
    delete newEnv[key];
    setFormData({ ...formData, env: newEnv });
  };

  const canProceed = () => {
    switch (step) {
      case 1:
        return !!formData.type;
      case 2:
        if (formData.type === "stdio") {
          return formData.name.trim() !== "" && (formData.command?.trim() ?? "") !== "";
        } else {
          // Both http and sse types require URL
          return formData.name.trim() !== "" && (formData.url?.trim() ?? "") !== "";
        }
      case 3:
      case 4:
      case 5:
        return true;
      default:
        return false;
    }
  };

  return (
    <div className="space-y-6">
      {/* Progress indicator */}
      <div className="flex items-center justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            {[1, 2, 3, 4, 5].map((s) => (
              <div
                key={s}
                className={`h-2 flex-1 rounded ${
                  s <= step ? "bg-primary" : "bg-muted"
                }`}
              />
            ))}
          </div>
          <p className="text-sm text-muted-foreground mt-2">
            Step {step} of 5
          </p>
        </div>
      </div>

      {/* Step 1: Choose Type */}
      {step === 1 && (
        <div className="space-y-4">
          <div>
            <h3 className="text-lg font-semibold">Choose Server Type</h3>
            <p className="text-sm text-muted-foreground">
              Select the type of MCP server you want to add
            </p>
          </div>

          <div className="space-y-3">
            <button
              type="button"
              onClick={() => setFormData({ ...formData, type: "stdio" })}
              className={`w-full p-4 border rounded-lg text-left transition-colors ${
                formData.type === "stdio"
                  ? "border-primary bg-primary/5"
                  : "border-input hover:bg-muted/50"
              }`}
            >
              <div className="font-medium">Standard I/O (stdio)</div>
              <div className="text-sm text-muted-foreground mt-1">
                Communicates via stdin/stdout. Runs a command locally.
              </div>
            </button>

            <button
              type="button"
              onClick={() => setFormData({ ...formData, type: "sse" })}
              className={`w-full p-4 border rounded-lg text-left transition-colors ${
                formData.type === "sse"
                  ? "border-primary bg-primary/5"
                  : "border-input hover:bg-muted/50"
              }`}
            >
              <div className="font-medium">Server-Sent Events (SSE)</div>
              <div className="text-sm text-muted-foreground mt-1">
                Connects via SSE stream. Recommended for remote MCP servers.
              </div>
            </button>

            <button
              type="button"
              onClick={() => setFormData({ ...formData, type: "http" })}
              className={`w-full p-4 border rounded-lg text-left transition-colors ${
                formData.type === "http"
                  ? "border-primary bg-primary/5"
                  : "border-input hover:bg-muted/50"
              }`}
            >
              <div className="font-medium">HTTP</div>
              <div className="text-sm text-muted-foreground mt-1">
                Communicates via HTTP requests. Legacy remote server support.
              </div>
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Configure */}
      {step === 2 && (
        <div className="space-y-4">
          <div>
            <h3 className="text-lg font-semibold">Configure Server</h3>
            <p className="text-sm text-muted-foreground">
              Provide the {formData.type === "stdio" ? "command" : "URL"} and name
            </p>
          </div>

          <div>
            <Label htmlFor="name">Server Name *</Label>
            <Input
              id="name"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g., github, filesystem"
              required
            />
          </div>

          {formData.type === "stdio" && (
            <>
              <div>
                <Label htmlFor="command">Command *</Label>
                <Input
                  id="command"
                  value={formData.command}
                  onChange={(e) => setFormData({ ...formData, command: e.target.value })}
                  placeholder="e.g., npx"
                  required
                />
              </div>

              <div>
                <Label htmlFor="args">Arguments</Label>
                <Input
                  id="args"
                  value={argsInput}
                  onChange={(e) => setArgsInput(e.target.value)}
                  placeholder="e.g., @modelcontextprotocol/server-github"
                />
                <p className="text-xs text-muted-foreground mt-1">
                  Space-separated list of arguments
                </p>
              </div>
            </>
          )}

          {(formData.type === "http" || formData.type === "sse") && (
            <div>
              <Label htmlFor="url">Server URL *</Label>
              <Input
                id="url"
                type="url"
                value={formData.url}
                onChange={(e) => setFormData({ ...formData, url: e.target.value })}
                placeholder={formData.type === "sse" ? "https://example.com/sse" : "https://example.com/mcp"}
                required
              />
              {formData.type === "sse" && (
                <p className="text-xs text-muted-foreground mt-1">
                  The SSE endpoint URL for the MCP server
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {/* Step 3: Environment Variables */}
      {step === 3 && (
        <div className="space-y-4">
          <div>
            <h3 className="text-lg font-semibold">Environment Variables</h3>
            <p className="text-sm text-muted-foreground">
              Add any required environment variables (optional)
            </p>
          </div>

          <div className="space-y-2">
            {formData.env && Object.entries(formData.env).map(([key, _value]) => (
              <div key={key} className="flex items-center gap-2">
                <div className="flex-1 flex gap-2">
                  <span className="text-sm font-mono flex-1">{key}:</span>
                  <span className="text-sm font-mono text-muted-foreground flex-1">
                    ••••••••
                  </span>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => removeEnv(key)}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ))}

            <div className="flex gap-2">
              <Input
                placeholder="Variable name (e.g., API_KEY)"
                value={envKey}
                onChange={(e) => setEnvKey(e.target.value)}
              />
              <Input
                type="password"
                placeholder="Variable value"
                value={envValue}
                onChange={(e) => setEnvValue(e.target.value)}
              />
              <Button type="button" variant="outline" onClick={addEnv}>
                Add
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Step 4: Scope Selection */}
      {step === 4 && (
        <div className="space-y-4">
          <div>
            <h3 className="text-lg font-semibold">Choose Scope</h3>
            <p className="text-sm text-muted-foreground">
              Where should this server configuration be saved?
            </p>
          </div>

          <div>
            <Label htmlFor="scope">Scope</Label>
            <Select
              value={formData.scope}
              onValueChange={(value: "user" | "project") =>
                setFormData({ ...formData, scope: value })
              }
            >
              <SelectTrigger id="scope">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="user">User (~/.claude.json)</SelectItem>
                <SelectItem value="project">Project (.mcp.json)</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground mt-2">
              <strong>User:</strong> Available in all projects<br />
              <strong>Project:</strong> Only available in this project
            </p>
          </div>
        </div>
      )}

      {/* Step 5: Review */}
      {step === 5 && (
        <div className="space-y-4">
          <div>
            <h3 className="text-lg font-semibold">Review & Save</h3>
            <p className="text-sm text-muted-foreground">
              Review your server configuration before saving
            </p>
          </div>

          <div className="border rounded-lg p-4 space-y-3 bg-muted/30">
            <div>
              <div className="text-sm font-medium">Name</div>
              <div className="text-sm text-muted-foreground">{formData.name}</div>
            </div>

            <div>
              <div className="text-sm font-medium">Type</div>
              <div className="text-sm text-muted-foreground">
                {formData.type === "stdio" ? "Standard I/O" : formData.type === "sse" ? "Server-Sent Events" : "HTTP"}
              </div>
            </div>

            {formData.type === "stdio" && (
              <>
                <div>
                  <div className="text-sm font-medium">Command</div>
                  <div className="text-sm text-muted-foreground font-mono">
                    {formData.command}
                  </div>
                </div>
                {argsInput && (
                  <div>
                    <div className="text-sm font-medium">Arguments</div>
                    <div className="text-sm text-muted-foreground font-mono">
                      {argsInput}
                    </div>
                  </div>
                )}
              </>
            )}

            {(formData.type === "http" || formData.type === "sse") && (
              <div>
                <div className="text-sm font-medium">URL</div>
                <div className="text-sm text-muted-foreground font-mono break-all">
                  {formData.url}
                </div>
              </div>
            )}

            {formData.env && Object.keys(formData.env).length > 0 && (
              <div>
                <div className="text-sm font-medium">Environment Variables</div>
                <div className="text-sm text-muted-foreground">
                  {Object.keys(formData.env).length} variable(s)
                </div>
              </div>
            )}

            <div>
              <div className="text-sm font-medium">Scope</div>
              <div className="text-sm text-muted-foreground capitalize">
                {formData.scope}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Navigation */}
      <div className="flex justify-between pt-4">
        <Button
          type="button"
          variant="outline"
          onClick={step === 1 ? onCancel : handleBack}
        >
          {step === 1 ? "Cancel" : "Back"}
        </Button>

        <div className="flex gap-2">
          {step < 5 && (
            <Button
              type="button"
              onClick={handleNext}
              disabled={!canProceed()}
            >
              Next
            </Button>
          )}
          {step === 5 && (
            <Button
              type="button"
              onClick={handleSubmit}
              disabled={saving}
            >
              {saving ? "Saving..." : "Save Server"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
