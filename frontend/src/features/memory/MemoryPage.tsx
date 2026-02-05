import { useState, useEffect, useCallback } from "react";
import {
  FileText,
  FolderTree,
  RefreshCw,
  BookOpen,
  Shield,
  User,
  FolderOpen,
  Lock,
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
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { RefreshButton } from "@/components/shared/RefreshButton";
import { MemoryEditor } from "./MemoryEditor";
import { RulesManager } from "./RulesManager";
import { ImportTree } from "./ImportTree";
import { apiClient, buildEndpoint } from "@/lib/api";
import { useProjectContext } from "@/contexts/ProjectContext";
import { toast } from "sonner";
import type { MemoryHierarchyItem, MemoryHierarchyResponse } from "@/types/memory";

type MemoryTab = "hierarchy" | "rules" | "imports";

const SCOPE_ICONS: Record<string, React.ReactNode> = {
  managed: <Shield className="h-4 w-4" />,
  user: <User className="h-4 w-4" />,
  project: <FolderOpen className="h-4 w-4" />,
  local: <Lock className="h-4 w-4" />,
  rules: <BookOpen className="h-4 w-4" />,
};

const SCOPE_COLORS: Record<string, string> = {
  managed: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  user: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  project: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  local: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  rules: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
};

export function MemoryPage() {
  const { activeProject } = useProjectContext();
  const [activeTab, setActiveTab] = useState<MemoryTab>("hierarchy");
  const [files, setFiles] = useState<MemoryHierarchyItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<MemoryHierarchyItem | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);

  const fetchHierarchy = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { project_path: activeProject?.path };
      const response = await apiClient<MemoryHierarchyResponse>(
        buildEndpoint("memory/hierarchy", params)
      );
      setFiles(response.files);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch memory files");
      toast.error("Failed to load memory hierarchy");
    } finally {
      setLoading(false);
    }
  }, [activeProject?.path]);

  useEffect(() => {
    fetchHierarchy();
  }, [fetchHierarchy]);

  const handleFileClick = (file: MemoryHierarchyItem) => {
    setSelectedFile(file);
    setEditorOpen(true);
  };

  const handleEditorClose = () => {
    setEditorOpen(false);
    setSelectedFile(null);
  };

  const handleSaveSuccess = () => {
    fetchHierarchy();
    toast.success("File saved successfully");
  };

  const handleCreateNew = (scope: "user" | "project" | "local") => {
    // Find the corresponding file entry or create a placeholder
    const existing = files.find((f) => f.scope === scope && f.type === "claude_md");
    if (existing) {
      setSelectedFile(existing);
    } else {
      // Create placeholder for new file
      let path = "";
      let description = "";
      switch (scope) {
        case "user":
          path = "~/.claude/CLAUDE.md";
          description = "Personal preferences (all projects)";
          break;
        case "project":
          path = activeProject?.path
            ? `${activeProject.path}/CLAUDE.md`
            : "./CLAUDE.md";
          description = "Team-shared project instructions";
          break;
        case "local":
          path = activeProject?.path
            ? `${activeProject.path}/CLAUDE.local.md`
            : "./CLAUDE.local.md";
          description = "Personal project-specific preferences";
          break;
      }
      setSelectedFile({
        path,
        scope,
        type: "claude_md",
        exists: false,
        readonly: false,
        description,
      });
    }
    setEditorOpen(true);
  };

  // Group files by type
  const claudeMdFiles = files.filter((f) => f.type === "claude_md");
  const ruleFiles = files.filter((f) => f.type === "rule");

  return (
    <div className="container mx-auto py-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Memory</h1>
          <p className="text-muted-foreground">
            Manage CLAUDE.md files and rules that shape Claude's behavior
          </p>
        </div>
        <RefreshButton onClick={fetchHierarchy} loading={loading} />
      </div>

      <Tabs
        value={activeTab}
        onValueChange={(v) => setActiveTab(v as MemoryTab)}
      >
        <TabsList>
          <TabsTrigger value="hierarchy" className="gap-2">
            <FolderTree className="h-4 w-4" />
            Hierarchy
          </TabsTrigger>
          <TabsTrigger value="rules" className="gap-2">
            <BookOpen className="h-4 w-4" />
            Rules
            {ruleFiles.length > 0 && (
              <Badge variant="secondary" className="ml-1">
                {ruleFiles.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="imports" className="gap-2">
            <RefreshCw className="h-4 w-4" />
            Imports
          </TabsTrigger>
        </TabsList>

        <TabsContent value="hierarchy" className="space-y-4">
          {error ? (
            <Card className="border-destructive">
              <CardContent className="pt-6">
                <p className="text-destructive">{error}</p>
              </CardContent>
            </Card>
          ) : loading ? (
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-2">
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  <span>Loading memory hierarchy...</span>
                </div>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4">
              {/* Quick create buttons */}
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-lg">Quick Create</CardTitle>
                  <CardDescription>
                    Create a new CLAUDE.md file at the desired scope
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleCreateNew("user")}
                      className="gap-2"
                    >
                      <User className="h-4 w-4" />
                      User CLAUDE.md
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleCreateNew("project")}
                      className="gap-2"
                      disabled={!activeProject}
                    >
                      <FolderOpen className="h-4 w-4" />
                      Project CLAUDE.md
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleCreateNew("local")}
                      className="gap-2"
                      disabled={!activeProject}
                    >
                      <Lock className="h-4 w-4" />
                      Local CLAUDE.md
                    </Button>
                  </div>
                </CardContent>
              </Card>

              {/* Memory files list */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">Memory Files</CardTitle>
                  <CardDescription>
                    Files are loaded in order: Managed → User → Project → Local →
                    Rules
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {claudeMdFiles.map((file) => (
                      <div
                        key={file.path}
                        className={`flex items-center justify-between p-3 rounded-lg border cursor-pointer transition-colors hover:bg-muted/50 ${
                          file.exists ? "" : "opacity-60"
                        }`}
                        onClick={() => handleFileClick(file)}
                      >
                        <div className="flex items-center gap-3">
                          <div
                            className={`p-2 rounded-md ${SCOPE_COLORS[file.scope]}`}
                          >
                            {SCOPE_ICONS[file.scope]}
                          </div>
                          <div>
                            <div className="font-medium flex items-center gap-2">
                              {file.scope.charAt(0).toUpperCase() +
                                file.scope.slice(1)}{" "}
                              CLAUDE.md
                              {file.readonly && (
                                <Badge variant="outline" className="text-xs">
                                  Read-only
                                </Badge>
                              )}
                            </div>
                            <div className="text-sm text-muted-foreground">
                              {file.description}
                            </div>
                            <div className="text-xs text-muted-foreground font-mono mt-1">
                              {file.path}
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          {file.exists ? (
                            <Badge variant="default">Exists</Badge>
                          ) : (
                            <Badge variant="secondary">Not created</Badge>
                          )}
                          <FileText className="h-4 w-4 text-muted-foreground" />
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>

        <TabsContent value="rules">
          <RulesManager
            projectPath={activeProject?.path}
            onRefresh={fetchHierarchy}
          />
        </TabsContent>

        <TabsContent value="imports">
          <ImportTree
            files={claudeMdFiles.filter((f) => f.exists)}
            projectPath={activeProject?.path}
          />
        </TabsContent>
      </Tabs>

      {/* Memory Editor Dialog */}
      {selectedFile && (
        <MemoryEditor
          open={editorOpen}
          onClose={handleEditorClose}
          file={selectedFile}
          projectPath={activeProject?.path}
          onSaveSuccess={handleSaveSuccess}
        />
      )}
    </div>
  );
}
