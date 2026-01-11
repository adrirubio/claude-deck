import { useState, useEffect, useCallback } from "react";
import { Terminal, Check, Eye, Sparkles, Settings, Code, Activity, ChevronDown, Zap, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { RefreshButton } from "@/components/shared/RefreshButton";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { TerminalPreview } from "./TerminalPreview";
import type {
  StatusLineConfig,
  StatusLinePreset,
  StatusLinePresetsResponse,
  StatusLinePreviewResponse,
  StatusLineUpdate,
  PowerlinePreset,
  PowerlinePresetsResponse,
  NodejsCheckResponse,
} from "@/types/statusline";

export function StatusLinePage() {
  const [config, setConfig] = useState<StatusLineConfig | null>(null);
  const [presets, setPresets] = useState<StatusLinePreset[]>([]);
  const [powerlinePresets, setPowerlinePresets] = useState<PowerlinePreset[]>([]);
  const [nodejsAvailable, setNodejsAvailable] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [previewPreset, setPreviewPreset] = useState<StatusLinePreset | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewOutput, setPreviewOutput] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [customScriptOpen, setCustomScriptOpen] = useState(false);
  const [customScript, setCustomScript] = useState("");
  const [padding, setPadding] = useState<string>("");
  const [saving, setSaving] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [configRes, presetsRes, powerlineRes] = await Promise.all([
        apiClient<StatusLineConfig>("statusline"),
        apiClient<StatusLinePresetsResponse>("statusline/presets"),
        apiClient<PowerlinePresetsResponse>("statusline/powerline-presets"),
      ]);
      setConfig(configRes);
      setPresets(presetsRes.presets);
      setPowerlinePresets(powerlineRes.presets);
      setCustomScript(configRes.script_content || "");
      setPadding(configRes.padding?.toString() || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch status line config");
      toast.error("Failed to load status line configuration");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleApplyPreset = async (presetId: string) => {
    setSaving(true);
    try {
      const response = await apiClient<StatusLineConfig>(
        `statusline/apply-preset/${presetId}`,
        { method: "POST" }
      );
      setConfig(response);
      setCustomScript(response.script_content || "");
      toast.success("Preset applied successfully");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to apply preset");
    } finally {
      setSaving(false);
    }
  };

  const handleToggleEnabled = async (enabled: boolean) => {
    setSaving(true);
    try {
      const update: StatusLineUpdate = { enabled };
      const response = await apiClient<StatusLineConfig>("statusline", {
        method: "PUT",
        body: JSON.stringify(update),
      });
      setConfig(response);
      toast.success(enabled ? "Status line enabled" : "Status line disabled");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update status line");
    } finally {
      setSaving(false);
    }
  };

  const handleSaveConfig = async () => {
    setSaving(true);
    try {
      const update: StatusLineUpdate = {
        padding: padding ? parseInt(padding, 10) : undefined,
        enabled: true,
      };
      const response = await apiClient<StatusLineConfig>("statusline", {
        method: "PUT",
        body: JSON.stringify(update),
      });
      setConfig(response);
      toast.success("Configuration saved");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save configuration");
    } finally {
      setSaving(false);
    }
  };

  const handleSaveCustomScript = async () => {
    setSaving(true);
    try {
      const response = await apiClient<StatusLineConfig>("statusline/script", {
        method: "POST",
        body: JSON.stringify(customScript),
        headers: { "Content-Type": "application/json" },
      });
      setConfig(response);
      toast.success("Custom script saved and applied");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save script");
    } finally {
      setSaving(false);
    }
  };

  const fetchPreview = async (script: string) => {
    setPreviewLoading(true);
    setPreviewOutput(null);
    setPreviewError(null);

    try {
      const response = await apiClient<StatusLinePreviewResponse>(
        "statusline/preview",
        {
          method: "POST",
          body: JSON.stringify({ script }),
        }
      );

      if (response.success) {
        setPreviewOutput(response.output);
      } else {
        setPreviewError(response.error || "Preview failed");
      }
    } catch (err) {
      setPreviewError(
        err instanceof Error ? err.message : "Failed to load preview"
      );
    } finally {
      setPreviewLoading(false);
    }
  };

  const handlePreviewClick = (preset: StatusLinePreset) => {
    setPreviewPreset(preset);
    fetchPreview(preset.script);
  };

  const handleApplyPowerline = async (presetId: string) => {
    // Check Node.js on first use
    if (nodejsAvailable === null) {
      try {
        const check = await apiClient<NodejsCheckResponse>("statusline/check-nodejs");
        setNodejsAvailable(check.available);
        if (!check.available) {
          toast.error("Node.js 18+ is required for Powerline themes. Please install Node.js first.");
          return;
        }
      } catch {
        toast.error("Failed to check Node.js availability");
        return;
      }
    } else if (!nodejsAvailable) {
      toast.error("Node.js 18+ is required for Powerline themes");
      return;
    }

    setSaving(true);
    try {
      const response = await apiClient<StatusLineConfig>(
        `statusline/apply-powerline/${presetId}`,
        { method: "POST" }
      );
      setConfig(response);
      toast.success("Powerline theme applied successfully");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to apply powerline theme");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Activity className="h-8 w-8" />
            Status Line
          </h1>
          <p className="text-muted-foreground mt-1">
            Customize the status bar displayed at the bottom of Claude Code
          </p>
        </div>
        <RefreshButton onClick={fetchData} loading={loading} />
      </div>

      {/* Error Display */}
      {error && (
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-destructive">Error</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      )}

      {/* Current Status */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Terminal className="h-6 w-6 text-primary" />
              <div>
                <CardTitle>Current Status</CardTitle>
                <CardDescription>
                  {config?.enabled
                    ? `Using script: ${config.command || "Not configured"}`
                    : "Status line is disabled"}
                </CardDescription>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Label htmlFor="enabled" className="text-sm text-muted-foreground">
                {config?.enabled ? "Enabled" : "Disabled"}
              </Label>
              <Switch
                id="enabled"
                checked={config?.enabled || false}
                onCheckedChange={handleToggleEnabled}
                disabled={saving || loading}
              />
            </div>
          </div>
        </CardHeader>
        {config?.enabled && config?.padding !== null && config?.padding !== undefined && (
          <CardContent>
            <Badge variant="secondary">Padding: {config.padding}</Badge>
          </CardContent>
        )}
      </Card>

      {/* Presets Section */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-amber-500" />
            <CardTitle>Presets</CardTitle>
          </div>
          <CardDescription>
            Choose from pre-configured status line scripts for quick setup
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {presets.map((preset) => (
              <Card key={preset.id} className="border-2 hover:border-primary/50 transition-colors">
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between">
                    <div>
                      <CardTitle className="text-lg">{preset.name}</CardTitle>
                      <CardDescription className="mt-1">
                        {preset.description}
                      </CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handlePreviewClick(preset)}
                    >
                      <Eye className="h-4 w-4 mr-2" />
                      Preview
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => handleApplyPreset(preset.id)}
                      disabled={saving}
                    >
                      <Check className="h-4 w-4 mr-2" />
                      Apply
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Powerline Themes Section */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-purple-500" />
            <CardTitle>Powerline Themes</CardTitle>
          </div>
          <CardDescription>
            Beautiful themes powered by{" "}
            <a
              href="https://github.com/Owloops/claude-powerline"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary hover:underline inline-flex items-center gap-1"
            >
              claude-powerline
              <ExternalLink className="h-3 w-3" />
            </a>
            . Requires Node.js 18+.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {powerlinePresets.map((preset) => (
              <Card
                key={preset.id}
                className="border-2 hover:border-purple-500/50 transition-colors"
              >
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between">
                    <div>
                      <CardTitle className="text-lg">{preset.name}</CardTitle>
                      <CardDescription className="mt-1">
                        {preset.description}
                      </CardDescription>
                    </div>
                  </div>
                  <div className="flex gap-2 mt-2">
                    <Badge variant="secondary">{preset.theme}</Badge>
                    <Badge variant="outline">{preset.style}</Badge>
                  </div>
                </CardHeader>
                <CardContent>
                  <Button
                    size="sm"
                    onClick={() => handleApplyPowerline(preset.id)}
                    disabled={saving}
                    className="w-full"
                  >
                    <Check className="h-4 w-4 mr-2" />
                    Apply
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Custom Script Section */}
      <Card>
        <Collapsible open={customScriptOpen} onOpenChange={setCustomScriptOpen}>
          <CardHeader>
            <CollapsibleTrigger className="flex items-center justify-between w-full">
              <div className="flex items-center gap-2">
                <Code className="h-5 w-5 text-blue-500" />
                <div className="text-left">
                  <CardTitle>Custom Script</CardTitle>
                  <CardDescription>
                    Write your own status line script
                  </CardDescription>
                </div>
              </div>
              <Badge variant="outline">
                {customScriptOpen ? "Collapse" : "Expand"}
              </Badge>
            </CollapsibleTrigger>
          </CardHeader>
          <CollapsibleContent>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="script">Script Content</Label>
                <textarea
                  id="script"
                  value={customScript}
                  onChange={(e) => setCustomScript(e.target.value)}
                  className="w-full h-64 p-4 font-mono text-sm border rounded-md resize-y focus:outline-none focus:ring-2 focus:ring-primary bg-muted/50"
                  placeholder="#!/bin/bash&#10;input=$(cat)&#10;# Your script here..."
                />
                <p className="text-xs text-muted-foreground">
                  The script receives JSON context via stdin. Use jq to parse fields like
                  model.display_name, workspace.current_dir, etc.
                </p>
              </div>
              <Button
                onClick={handleSaveCustomScript}
                disabled={saving || !customScript.trim()}
              >
                {saving ? "Saving..." : "Save & Apply Script"}
              </Button>
            </CardContent>
          </CollapsibleContent>
        </Collapsible>
      </Card>

      {/* Configuration Section */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Settings className="h-5 w-5 text-gray-500" />
            <CardTitle>Configuration</CardTitle>
          </div>
          <CardDescription>
            Additional status line settings
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="padding">Padding</Label>
            <Input
              id="padding"
              type="number"
              min="0"
              value={padding}
              onChange={(e) => setPadding(e.target.value)}
              placeholder="0 (edge) or leave empty"
              className="max-w-xs"
            />
            <p className="text-xs text-muted-foreground">
              Set to 0 to let the status line extend to the edge. Leave empty for default.
            </p>
          </div>
          <Button onClick={handleSaveConfig} disabled={saving}>
            {saving ? "Saving..." : "Save Configuration"}
          </Button>
        </CardContent>
      </Card>

      {/* Preview Dialog */}
      <Dialog
        open={!!previewPreset}
        onOpenChange={(open) => {
          if (!open) {
            setPreviewPreset(null);
            setPreviewOutput(null);
            setPreviewError(null);
          }
        }}
      >
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{previewPreset?.name}</DialogTitle>
            <DialogDescription>{previewPreset?.description}</DialogDescription>
          </DialogHeader>

          {/* Rendered Preview - Primary */}
          <div className="space-y-2">
            <Label className="text-sm font-medium">Preview Output</Label>
            <TerminalPreview
              output={previewOutput || ""}
              loading={previewLoading}
              error={previewError}
            />
            <p className="text-xs text-muted-foreground">
              Sample data: claude-sonnet-4-20250514, /home/user/my-project
            </p>
          </div>

          {/* Script Code - Collapsible Secondary */}
          <Collapsible className="space-y-2">
            <CollapsibleTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="w-full justify-between"
              >
                <span className="flex items-center gap-2">
                  <Code className="h-4 w-4" />
                  View Script Code
                </span>
                <ChevronDown className="h-4 w-4" />
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="rounded-lg border bg-muted/50 p-4 overflow-auto max-h-64">
                <pre className="text-sm font-mono whitespace-pre-wrap">
                  {previewPreset?.script}
                </pre>
              </div>
            </CollapsibleContent>
          </Collapsible>

          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setPreviewPreset(null)}>
              Close
            </Button>
            <Button
              onClick={() => {
                if (previewPreset) {
                  handleApplyPreset(previewPreset.id);
                  setPreviewPreset(null);
                }
              }}
              disabled={saving}
            >
              <Check className="h-4 w-4 mr-2" />
              Apply This Preset
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
