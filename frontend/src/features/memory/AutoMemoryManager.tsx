import { useState, useEffect, useCallback } from "react";
import { Brain, FileText, FolderOpen, RefreshCw } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { CLICKABLE_CARD } from "@/lib/constants";
import { apiClient, buildEndpoint } from "@/lib/api";
import { toast } from "sonner";
import { MemoryEditor } from "./MemoryEditor";
import type { AutoMemoryFileInfo, AutoMemoryListResponse, MemoryHierarchyItem } from "@/types/memory";

interface AutoMemoryManagerProps {
  projectPath?: string;
  onRefresh: () => void;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleString();
}

export function AutoMemoryManager({ projectPath, onRefresh }: AutoMemoryManagerProps) {
  const [files, setFiles] = useState<AutoMemoryFileInfo[]>([]);
  const [memoryDir, setMemoryDir] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<MemoryHierarchyItem | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);

  const fetchFiles = useCallback(async () => {
    if (!projectPath) {
      setFiles([]);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const params = { project_path: projectPath };
      const response = await apiClient<AutoMemoryListResponse>(
        buildEndpoint("memory/auto-memory", params)
      );
      setFiles(response.files);
      setMemoryDir(response.memory_dir);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch auto-memory files");
      toast.error("Failed to load auto-memory files");
    } finally {
      setLoading(false);
    }
  }, [projectPath]);

  useEffect(() => {
    fetchFiles();
  }, [fetchFiles]);

  const handleFileClick = (file: AutoMemoryFileInfo) => {
    setSelectedFile({
      path: file.path,
      scope: "auto",
      type: "auto_memory",
      exists: true,
      readonly: false,
      description: `Auto-memory file: ${file.name}`,
      name: file.name,
    });
    setEditorOpen(true);
  };

  const handleEditorClose = () => {
    setEditorOpen(false);
    setSelectedFile(null);
  };

  const handleSaveSuccess = () => {
    fetchFiles();
    onRefresh();
    toast.success("File saved successfully");
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-lg flex items-center gap-2">
                <Brain className="h-5 w-5" />
                Auto Memory
              </CardTitle>
              <CardDescription>
                Persistent notes Claude writes across sessions for the active project
              </CardDescription>
            </div>
            {projectPath && (
              <Button
                variant="outline"
                size="sm"
                onClick={fetchFiles}
                disabled={loading}
              >
                <RefreshCw
                  className={`h-4 w-4 ${loading ? "animate-spin" : ""}`}
                />
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {!projectPath ? (
            <div className="text-center py-8 text-muted-foreground">
              <FolderOpen className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p>Select a project to view auto-memory files</p>
            </div>
          ) : error ? (
            <div className="text-center py-8 text-destructive">
              <p>{error}</p>
            </div>
          ) : loading ? (
            <div className="text-center py-8 text-muted-foreground">
              <RefreshCw className="h-6 w-6 mx-auto mb-2 animate-spin" />
              <p>Loading auto-memory files...</p>
            </div>
          ) : files.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Brain className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p>No auto-memory files yet</p>
              <p className="text-sm mt-1">
                Claude creates these during sessions in{" "}
                <span className="font-mono text-xs">{memoryDir}</span>
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground font-mono mb-3">
                {memoryDir}
              </p>
              {files.map((file) => (
                <div
                  key={file.path}
                  className={`flex items-center justify-between p-3 rounded-lg ${CLICKABLE_CARD}`}
                  tabIndex={0}
                  onClick={() => handleFileClick(file)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      handleFileClick(file);
                    }
                  }}
                >
                  <div className="flex items-center gap-3">
                    <FileText className="h-5 w-5 text-muted-foreground" />
                    <div>
                      <div className="font-medium">{file.name}</div>
                      <div className="text-xs text-muted-foreground">
                        Modified {formatDate(file.modified_at)}
                      </div>
                    </div>
                  </div>
                  <Badge variant="outline" className="text-xs">
                    {formatFileSize(file.size)}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {selectedFile && (
        <MemoryEditor
          open={editorOpen}
          onClose={handleEditorClose}
          file={selectedFile}
          projectPath={projectPath}
          onSaveSuccess={handleSaveSuccess}
        />
      )}
    </div>
  );
}
