import { useState } from "react";
import type { MCPServer, MCPServerUpdate } from "@/types/mcp";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { X } from "lucide-react";

interface MCPServerFormProps {
  server: MCPServer;
  onSave: (name: string, scope: string, updates: MCPServerUpdate) => Promise<void>;
  onCancel: () => void;
}

export function MCPServerForm({ server, onSave, onCancel }: MCPServerFormProps) {
  const [formData, setFormData] = useState<MCPServerUpdate>({
    type: server.type,
    command: server.command || "",
    args: server.args || [],
    url: server.url || "",
    headers: server.headers || {},
    env: server.env || {},
  });

  const [argsInput, setArgsInput] = useState(server.args?.join(" ") || "");
  const [headerKey, setHeaderKey] = useState("");
  const [headerValue, setHeaderValue] = useState("");
  const [envKey, setEnvKey] = useState("");
  const [envValue, setEnvValue] = useState("");
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);

    try {
      // Parse args from space-separated string
      const parsedArgs = argsInput.trim() ? argsInput.trim().split(/\s+/) : [];

      await onSave(server.name, server.scope, {
        ...formData,
        args: parsedArgs.length > 0 ? parsedArgs : undefined,
      });
    } finally {
      setSaving(false);
    }
  };

  const addHeader = () => {
    if (headerKey && headerValue) {
      setFormData({
        ...formData,
        headers: { ...formData.headers, [headerKey]: headerValue },
      });
      setHeaderKey("");
      setHeaderValue("");
    }
  };

  const removeHeader = (key: string) => {
    const newHeaders = { ...formData.headers };
    delete newHeaders[key];
    setFormData({ ...formData, headers: newHeaders });
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

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Server Type - Read Only */}
      <div>
        <Label>Server Type</Label>
        <div className="mt-1 text-sm text-muted-foreground">
          {formData.type === "stdio" ? "Standard I/O" : formData.type === "sse" ? "Server-Sent Events" : "HTTP"}
        </div>
      </div>

      {/* stdio fields */}
      {formData.type === "stdio" && (
        <>
          <div>
            <Label htmlFor="command">Command *</Label>
            <Input
              id="command"
              value={formData.command || ""}
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

      {/* http/sse fields */}
      {(formData.type === "http" || formData.type === "sse") && (
        <>
          <div>
            <Label htmlFor="url">URL *</Label>
            <Input
              id="url"
              type="url"
              value={formData.url || ""}
              onChange={(e) => setFormData({ ...formData, url: e.target.value })}
              placeholder="https://example.com/mcp"
              required
            />
          </div>

          {/* Headers */}
          <div>
            <Label>HTTP Headers</Label>
            <div className="space-y-2 mt-2">
              {formData.headers && Object.entries(formData.headers).map(([key, value]) => (
                <div key={key} className="flex items-center gap-2">
                  <div className="flex-1 flex gap-2">
                    <span className="text-sm font-mono flex-1">{key}:</span>
                    <span className="text-sm font-mono text-muted-foreground flex-1">{value}</span>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => removeHeader(key)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ))}
              <div className="flex gap-2">
                <Input
                  placeholder="Header name"
                  value={headerKey}
                  onChange={(e) => setHeaderKey(e.target.value)}
                />
                <Input
                  placeholder="Header value"
                  value={headerValue}
                  onChange={(e) => setHeaderValue(e.target.value)}
                />
                <Button type="button" variant="outline" onClick={addHeader}>
                  Add
                </Button>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Environment Variables */}
      <div>
        <Label>Environment Variables</Label>
        <div className="space-y-2 mt-2">
          {formData.env && Object.entries(formData.env).map(([key, value]) => (
            <div key={key} className="flex items-center gap-2">
              <div className="flex-1 flex gap-2">
                <span className="text-sm font-mono flex-1">{key}:</span>
                <span className="text-sm font-mono text-muted-foreground flex-1">
                  {value === "***MASKED***" ? value : "••••••••"}
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
              placeholder="Variable name"
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

      {/* Actions */}
      <div className="flex justify-end gap-2 pt-4">
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={saving}>
          {saving ? "Saving..." : "Save Changes"}
        </Button>
      </div>
    </form>
  );
}
