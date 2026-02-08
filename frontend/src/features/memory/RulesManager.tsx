import { useState, useEffect, useCallback } from "react";
import {
  Plus,
  BookOpen,
  FileText,
  Trash2,
  FolderOpen,
  MapPin,
  RefreshCw,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { apiClient, buildEndpoint } from "@/lib/api";
import { toast } from "sonner";
import type { RuleInfo, RulesListResponse, SaveMemoryResponse } from "@/types/memory";

interface RulesManagerProps {
  projectPath?: string;
  onRefresh: () => void;
}

interface CreateRuleForm {
  name: string;
  description: string;
  paths: string;
  content: string;
}

export function RulesManager({ projectPath, onRefresh }: RulesManagerProps) {
  const [rules, setRules] = useState<RuleInfo[]>([]);
  const [rulesDir, setRulesDir] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<RuleInfo | null>(null);
  const [editContent, setEditContent] = useState("");
  const [createForm, setCreateForm] = useState<CreateRuleForm>({
    name: "",
    description: "",
    paths: "",
    content: "",
  });
  const [creating, setCreating] = useState(false);

  const fetchRules = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { project_path: projectPath };
      const response = await apiClient<RulesListResponse>(
        buildEndpoint("memory/rules", params)
      );
      setRules(response.rules);
      setRulesDir(response.rules_dir);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch rules");
      toast.error("Failed to load rules");
    } finally {
      setLoading(false);
    }
  }, [projectPath]);

  useEffect(() => {
    fetchRules();
  }, [fetchRules]);

  const handleCreateRule = async () => {
    if (!createForm.name.trim()) {
      toast.error("Rule name is required");
      return;
    }

    setCreating(true);
    try {
      const params = { project_path: projectPath };
      const body = {
        name: createForm.name.trim(),
        content: createForm.content,
        description: createForm.description || undefined,
        paths: createForm.paths
          ? createForm.paths.split(",").map((p) => p.trim())
          : undefined,
      };

      await apiClient<SaveMemoryResponse>(
        buildEndpoint("memory/rules", params),
        {
          method: "POST",
          body: JSON.stringify(body),
        }
      );

      toast.success(`Rule "${createForm.name}" created`);
      setCreateDialogOpen(false);
      setCreateForm({ name: "", description: "", paths: "", content: "" });
      fetchRules();
      onRefresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create rule");
    } finally {
      setCreating(false);
    }
  };

  const handleEditRule = async (rule: RuleInfo) => {
    // Load full content
    try {
      const params = { file_path: rule.path, include_imports: false };
      const response = await apiClient<{ content: string }>(
        buildEndpoint("memory/file", params)
      );
      setEditContent(response.content || "");
      setEditingRule(rule);
    } catch {
      toast.error("Failed to load rule content");
    }
  };

  const handleSaveEdit = async () => {
    if (!editingRule) return;

    try {
      const params = { file_path: editingRule.path };
      await apiClient<SaveMemoryResponse>(
        buildEndpoint("memory/file", params),
        {
          method: "PUT",
          body: JSON.stringify({ content: editContent }),
        }
      );

      toast.success("Rule saved");
      setEditingRule(null);
      fetchRules();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save rule");
    }
  };

  const handleDeleteRule = async (rule: RuleInfo) => {
    try {
      const params = { file_path: rule.path };
      await apiClient<SaveMemoryResponse>(
        buildEndpoint("memory/file", params),
        { method: "DELETE" }
      );

      toast.success(`Rule "${rule.name}" deleted`);
      fetchRules();
      onRefresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete rule");
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-lg flex items-center gap-2">
                <BookOpen className="h-5 w-5" />
                Project Rules
              </CardTitle>
              <CardDescription>
                Modular, topic-specific rules in{" "}
                <span className="font-mono text-xs">.claude/rules/</span>
              </CardDescription>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={fetchRules}
                disabled={loading}
              >
                <RefreshCw
                  className={`h-4 w-4 ${loading ? "animate-spin" : ""}`}
                />
              </Button>
              <Button
                size="sm"
                onClick={() => setCreateDialogOpen(true)}
                disabled={!projectPath}
                className="gap-2"
              >
                <Plus className="h-4 w-4" />
                New Rule
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {!projectPath ? (
            <div className="text-center py-8 text-muted-foreground">
              <FolderOpen className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p>Select a project to manage rules</p>
            </div>
          ) : error ? (
            <div className="text-center py-8 text-destructive">
              <p>{error}</p>
            </div>
          ) : loading ? (
            <div className="text-center py-8 text-muted-foreground">
              <RefreshCw className="h-6 w-6 mx-auto mb-2 animate-spin" />
              <p>Loading rules...</p>
            </div>
          ) : rules.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <BookOpen className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p>No rules defined yet</p>
              <p className="text-sm">
                Rules are stored in{" "}
                <span className="font-mono">{rulesDir}</span>
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {rules.map((rule) => (
                <div
                  key={rule.path}
                  className="flex items-center justify-between p-3 rounded-lg border hover:bg-muted/50 cursor-pointer"
                  onClick={() => handleEditRule(rule)}
                >
                  <div className="flex items-center gap-3">
                    <FileText className="h-5 w-5 text-muted-foreground" />
                    <div>
                      <div className="font-medium">{rule.name}</div>
                      {rule.description && (
                        <div className="text-sm text-muted-foreground">
                          {rule.description}
                        </div>
                      )}
                      {rule.scoped_paths.length > 0 && (
                        <div className="flex items-center gap-1 mt-1">
                          <MapPin className="h-3 w-3 text-muted-foreground" />
                          <span className="text-xs text-muted-foreground">
                            Scoped to: {rule.scoped_paths.join(", ")}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-xs">
                      {rule.relative_path}
                    </Badge>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>Delete rule?</AlertDialogTitle>
                          <AlertDialogDescription>
                            This will permanently delete the rule "{rule.name}".
                            This action cannot be undone.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancel</AlertDialogCancel>
                          <AlertDialogAction
                            onClick={() => handleDeleteRule(rule)}
                            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                          >
                            Delete
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create Rule Dialog */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Create New Rule</DialogTitle>
            <DialogDescription>
              Create a modular rule file in .claude/rules/
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="name">Rule Name *</Label>
                <Input
                  id="name"
                  placeholder="e.g., testing, security, api-design"
                  value={createForm.name}
                  onChange={(e) =>
                    setCreateForm({ ...createForm, name: e.target.value })
                  }
                />
                <p className="text-xs text-muted-foreground">
                  Will be saved as {createForm.name || "name"}.md
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Input
                  id="description"
                  placeholder="Brief description"
                  value={createForm.description}
                  onChange={(e) =>
                    setCreateForm({ ...createForm, description: e.target.value })
                  }
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="paths">Path Scoping (optional)</Label>
              <Input
                id="paths"
                placeholder="e.g., src/tests, **/*.test.ts"
                value={createForm.paths}
                onChange={(e) =>
                  setCreateForm({ ...createForm, paths: e.target.value })
                }
              />
              <p className="text-xs text-muted-foreground">
                Comma-separated paths. Rule will only apply to matching files.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="content">Content</Label>
              <Textarea
                id="content"
                placeholder="# Rule Title&#10;&#10;Rule content in markdown..."
                value={createForm.content}
                onChange={(e) =>
                  setCreateForm({ ...createForm, content: e.target.value })
                }
                className="min-h-[200px] font-mono text-sm"
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreateRule} disabled={creating}>
              {creating ? "Creating..." : "Create Rule"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Rule Dialog */}
      <Dialog open={!!editingRule} onOpenChange={() => setEditingRule(null)}>
        <DialogContent className="max-w-3xl h-[80vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>Edit Rule: {editingRule?.name}</DialogTitle>
            <DialogDescription className="font-mono text-xs">
              {editingRule?.path}
            </DialogDescription>
          </DialogHeader>

          <Textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            className="flex-1 min-h-[400px] font-mono text-sm resize-none"
          />

          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingRule(null)}>
              Cancel
            </Button>
            <Button onClick={handleSaveEdit}>Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
