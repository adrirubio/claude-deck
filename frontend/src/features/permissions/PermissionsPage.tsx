import { useState, useEffect, useCallback } from "react";
import { Plus, Shield, ShieldCheck, ShieldX, ShieldQuestion, Settings2, FolderPlus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RuleList } from "./RuleList";
import { RuleBuilder } from "./RuleBuilder";
import { RefreshButton } from "@/components/shared/RefreshButton";
import { apiClient, buildEndpoint } from "@/lib/api";
import { useProjectContext } from "@/contexts/ProjectContext";
import { toast } from "sonner";
import {
  type PermissionRule,
  type PermissionType,
  type PermissionScope,
  type PermissionListResponse,
  type PermissionSettings,
  type PermissionSettingsUpdate,
  type PermissionMode,
  PERMISSION_MODES,
} from "@/types/permissions";

export function PermissionsPage() {
  const { activeProject } = useProjectContext();
  const [rules, setRules] = useState<PermissionRule[]>([]);
  const [settings, setSettings] = useState<PermissionSettings>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingRule, setEditingRule] = useState<PermissionRule | null>(null);
  const [showBuilder, setShowBuilder] = useState(false);
  const [builderType, setBuilderType] = useState<PermissionType>("allow");
  const [newDirectory, setNewDirectory] = useState("");
  const [savingSettings, setSavingSettings] = useState(false);

  const fetchPermissions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const endpoint = buildEndpoint("permissions", { project_path: activeProject?.path });
      const response = await apiClient<PermissionListResponse>(endpoint);
      setRules(response.rules);
      setSettings(response.settings || {});
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch permissions");
      toast.error("Failed to load permissions");
    } finally {
      setLoading(false);
    }
  }, [activeProject?.path]);

  useEffect(() => {
    fetchPermissions();
  }, [fetchPermissions]);

  const handleCreate = async (rule: {
    type: PermissionType;
    pattern: string;
    scope: PermissionScope;
  }) => {
    try {
      const endpoint = buildEndpoint("permissions", { project_path: activeProject?.path });
      await apiClient<PermissionRule>(endpoint, { method: "POST", body: JSON.stringify(rule) });
      toast.success("Permission rule created");
      await fetchPermissions();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create rule");
      throw err;
    }
  };

  const handleEdit = (rule: PermissionRule) => {
    setEditingRule(rule);
    setBuilderType(rule.type);
    setShowBuilder(true);
  };

  const handleUpdate = async (rule: {
    type: PermissionType;
    pattern: string;
    scope: PermissionScope;
  }) => {
    if (!editingRule) return;

    try {
      const endpoint = buildEndpoint(`permissions/${editingRule.id}`, {
        scope: editingRule.scope,
        project_path: activeProject?.path,
      });
      await apiClient<PermissionRule>(endpoint, {
        method: "PUT",
        body: JSON.stringify({ type: rule.type, pattern: rule.pattern }),
      });
      toast.success("Permission rule updated");
      await fetchPermissions();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update rule");
      throw err;
    }
  };

  const handleDelete = async (ruleId: string, scope: PermissionScope) => {
    try {
      const endpoint = buildEndpoint(`permissions/${ruleId}`, {
        scope,
        project_path: activeProject?.path,
      });
      await apiClient(endpoint, { method: "DELETE" });
      toast.success("Permission rule deleted");
      await fetchPermissions();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete rule");
    }
  };

  const handleUpdateSettings = async (update: PermissionSettingsUpdate) => {
    setSavingSettings(true);
    try {
      const endpoint = buildEndpoint("permissions/settings", {
        scope: "user",
        project_path: activeProject?.path,
      });
      await apiClient<PermissionSettings>(endpoint, {
        method: "PUT",
        body: JSON.stringify(update),
      });
      toast.success("Settings updated");
      await fetchPermissions();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update settings");
    } finally {
      setSavingSettings(false);
    }
  };

  const handleModeChange = (mode: PermissionMode) => {
    handleUpdateSettings({ defaultMode: mode });
  };

  const handleAddDirectory = () => {
    if (!newDirectory.trim()) return;
    const currentDirs = settings.additionalDirectories || [];
    if (currentDirs.includes(newDirectory.trim())) {
      toast.error("Directory already added");
      return;
    }
    handleUpdateSettings({
      additionalDirectories: [...currentDirs, newDirectory.trim()],
    });
    setNewDirectory("");
  };

  const handleRemoveDirectory = (dir: string) => {
    const currentDirs = settings.additionalDirectories || [];
    handleUpdateSettings({
      additionalDirectories: currentDirs.filter((d) => d !== dir),
    });
  };

  const handleBypassToggle = (disabled: boolean) => {
    handleUpdateSettings({ disableBypassPermissionsMode: disabled });
  };

  const openBuilder = (type: PermissionType) => {
    setEditingRule(null);
    setBuilderType(type);
    setShowBuilder(true);
  };

  const allowRules = rules.filter((r) => r.type === "allow");
  const askRules = rules.filter((r) => r.type === "ask");
  const denyRules = rules.filter((r) => r.type === "deny");

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Shield className="h-8 w-8" />
            Permissions
          </h1>
          <p className="text-muted-foreground mt-1">
            Control which operations Claude Code can perform
          </p>
        </div>
        <RefreshButton onClick={fetchPermissions} loading={loading} />
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

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Total Rules</CardDescription>
            <CardTitle className="text-3xl">{rules.length}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-success" />
              Allow Rules
            </CardDescription>
            <CardTitle className="text-3xl text-success">
              {allowRules.length}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription className="flex items-center gap-2">
              <ShieldQuestion className="h-4 w-4 text-warning" />
              Ask Rules
            </CardDescription>
            <CardTitle className="text-3xl text-warning">
              {askRules.length}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription className="flex items-center gap-2">
              <ShieldX className="h-4 w-4 text-destructive" />
              Deny Rules
            </CardDescription>
            <CardTitle className="text-3xl text-destructive">
              {denyRules.length}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Settings Card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Settings2 className="h-5 w-5" />
            Permission Settings
          </CardTitle>
          <CardDescription>
            Configure default behavior and additional directories
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Permission Mode */}
          <div className="space-y-2">
            <Label>Default Permission Mode</Label>
            <Select
              value={settings.defaultMode || "default"}
              onValueChange={(v) => handleModeChange(v as PermissionMode)}
              disabled={savingSettings}
            >
              <SelectTrigger className="w-full md:w-[300px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PERMISSION_MODES.map((mode) => (
                  <SelectItem key={mode.value} value={mode.value}>
                    <div className="flex flex-col">
                      <span className="font-medium">{mode.label}</span>
                      <span className="text-xs text-muted-foreground">
                        {mode.description}
                      </span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Disable Bypass Mode */}
          <div className="flex items-center justify-between rounded-lg border p-4">
            <div className="space-y-0.5">
              <Label>Disable Bypass Permissions Mode</Label>
              <p className="text-sm text-muted-foreground">
                Prevent using --dangerously-skip-permissions flag
              </p>
            </div>
            <Switch
              checked={settings.disableBypassPermissionsMode || false}
              onCheckedChange={handleBypassToggle}
              disabled={savingSettings}
            />
          </div>

          {/* Additional Directories */}
          <div className="space-y-3">
            <Label className="flex items-center gap-2">
              <FolderPlus className="h-4 w-4" />
              Additional Allowed Directories
            </Label>
            <p className="text-sm text-muted-foreground">
              Directories outside the project that Claude can access
            </p>
            <div className="flex gap-2">
              <Input
                value={newDirectory}
                onChange={(e) => setNewDirectory(e.target.value)}
                placeholder="/path/to/directory"
                onKeyDown={(e) => e.key === "Enter" && handleAddDirectory()}
              />
              <Button onClick={handleAddDirectory} disabled={savingSettings}>
                Add
              </Button>
            </div>
            {(settings.additionalDirectories?.length ?? 0) > 0 && (
              <div className="flex flex-wrap gap-2 mt-2">
                {settings.additionalDirectories?.map((dir) => (
                  <Badge
                    key={dir}
                    variant="secondary"
                    className="flex items-center gap-1 py-1 px-2"
                  >
                    <code className="text-xs">{dir}</code>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-4 w-4 p-0 hover:bg-transparent"
                      onClick={() => handleRemoveDirectory(dir)}
                    >
                      <X className="h-3 w-3" />
                    </Button>
                  </Badge>
                ))}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Rules Tabs */}
      <Tabs defaultValue="allow" className="w-full">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="allow" className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4" />
            Allow ({allowRules.length})
          </TabsTrigger>
          <TabsTrigger value="ask" className="flex items-center gap-2">
            <ShieldQuestion className="h-4 w-4" />
            Ask ({askRules.length})
          </TabsTrigger>
          <TabsTrigger value="deny" className="flex items-center gap-2">
            <ShieldX className="h-4 w-4" />
            Deny ({denyRules.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="allow" className="mt-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <ShieldCheck className="h-5 w-5 text-success" />
                    Allow Rules
                  </CardTitle>
                  <CardDescription>
                    Operations that Claude Code is permitted to perform automatically
                  </CardDescription>
                </div>
                <Button
                  size="sm"
                  onClick={() => openBuilder("allow")}
                  className="bg-success text-success-foreground hover:bg-success/90"
                >
                  <Plus className="h-4 w-4 mr-2" />
                  Add Allow Rule
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="text-center py-8 text-muted-foreground">
                  Loading...
                </div>
              ) : (
                <RuleList
                  rules={allowRules}
                  type="allow"
                  onEdit={handleEdit}
                  onDelete={handleDelete}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="ask" className="mt-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <ShieldQuestion className="h-5 w-5 text-warning" />
                    Ask Rules
                  </CardTitle>
                  <CardDescription>
                    Operations that will prompt for confirmation before executing
                  </CardDescription>
                </div>
                <Button
                  size="sm"
                  onClick={() => openBuilder("ask")}
                  className="bg-warning text-warning-foreground hover:bg-warning/90"
                >
                  <Plus className="h-4 w-4 mr-2" />
                  Add Ask Rule
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="text-center py-8 text-muted-foreground">
                  Loading...
                </div>
              ) : (
                <RuleList
                  rules={askRules}
                  type="ask"
                  onEdit={handleEdit}
                  onDelete={handleDelete}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="deny" className="mt-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <ShieldX className="h-5 w-5 text-destructive" />
                    Deny Rules
                  </CardTitle>
                  <CardDescription>
                    Operations that Claude Code is blocked from performing
                  </CardDescription>
                </div>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => openBuilder("deny")}
                >
                  <Plus className="h-4 w-4 mr-2" />
                  Add Deny Rule
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="text-center py-8 text-muted-foreground">
                  Loading...
                </div>
              ) : (
                <RuleList
                  rules={denyRules}
                  type="deny"
                  onEdit={handleEdit}
                  onDelete={handleDelete}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Pattern Syntax Help */}
      <Card>
        <CardHeader>
          <CardTitle>Pattern Syntax</CardTitle>
          <CardDescription>
            How to write permission patterns
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 text-sm">
            <div>
              <h4 className="font-medium mb-2">Basic Format</h4>
              <ul className="space-y-1 text-muted-foreground">
                <li><code className="bg-muted px-1 rounded">Tool</code> - Match any use of the tool</li>
                <li><code className="bg-muted px-1 rounded">Tool(pattern)</code> - Match with argument pattern</li>
                <li><code className="bg-muted px-1 rounded">Tool:subcommand</code> - Match specific subcommand</li>
                <li><code className="bg-muted px-1 rounded">Tool(prefix *)</code> - Match with prefix and wildcard</li>
              </ul>
            </div>
            <div>
              <h4 className="font-medium mb-2">Extended Patterns</h4>
              <ul className="space-y-1 text-muted-foreground">
                <li><code className="bg-muted px-1 rounded">WebFetch(domain:*.com)</code> - Domain matching</li>
                <li><code className="bg-muted px-1 rounded">MCP(server:tool)</code> - MCP server tools</li>
                <li><code className="bg-muted px-1 rounded">Task(*)</code> - All subagent tasks</li>
                <li><code className="bg-muted px-1 rounded">Skill(name)</code> - Specific skills</li>
              </ul>
            </div>
            <div>
              <h4 className="font-medium mb-2">Examples</h4>
              <ul className="space-y-1 text-muted-foreground">
                <li><code className="bg-muted px-1 rounded">Bash(npm run *)</code> - Any npm run command</li>
                <li><code className="bg-muted px-1 rounded">Read(*.env)</code> - Read .env files</li>
                <li><code className="bg-muted px-1 rounded">Write(/tmp/*)</code> - Write to /tmp</li>
                <li><code className="bg-muted px-1 rounded">MCP(postgres:*)</code> - All postgres MCP</li>
              </ul>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Rule Builder Dialog */}
      <RuleBuilder
        open={showBuilder}
        onOpenChange={(open) => {
          setShowBuilder(open);
          if (!open) setEditingRule(null);
        }}
        onSave={editingRule ? handleUpdate : handleCreate}
        editingRule={editingRule}
        defaultType={builderType}
      />
    </div>
  );
}
