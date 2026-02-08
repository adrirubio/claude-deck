import { useState } from "react";
import {
  GitBranch,
  FileText,
  AlertTriangle,
  ChevronRight,
  ChevronDown,
  RefreshCw,
  Link,
  XCircle,
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiClient, buildEndpoint } from "@/lib/api";
import { toast } from "sonner";
import type { MemoryHierarchyItem, ImportTreeNode, ImportTreeResponse } from "@/types/memory";

interface ImportTreeProps {
  files: MemoryHierarchyItem[];
  projectPath?: string;  // Reserved for future use
}

interface TreeNodeProps {
  node: ImportTreeNode;
  depth: number;
}

function TreeNode({ node, depth }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = node.imports && node.imports.length > 0;
  const fileName = node.path.split("/").pop() || node.path;

  return (
    <div className="select-none">
      <div
        className={`flex items-center gap-2 py-1.5 px-2 rounded-md hover:bg-muted/50 cursor-pointer ${
          depth > 0 ? "ml-4" : ""
        }`}
        style={{ marginLeft: depth * 16 }}
        onClick={() => hasChildren && setExpanded(!expanded)}
      >
        {hasChildren ? (
          expanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )
        ) : (
          <div className="w-4" />
        )}

        {node.cycle ? (
          <AlertTriangle className="h-4 w-4 text-yellow-500" />
        ) : node.exists ? (
          <FileText className="h-4 w-4 text-muted-foreground" />
        ) : (
          <XCircle className="h-4 w-4 text-destructive" />
        )}

        <span className={`font-mono text-sm ${!node.exists ? "text-destructive" : ""}`}>
          {fileName}
        </span>

        {node.cycle && (
          <Badge variant="outline" className="text-xs text-yellow-600">
            Cycle
          </Badge>
        )}
        {!node.exists && (
          <Badge variant="destructive" className="text-xs">
            Missing
          </Badge>
        )}
        {node.error && (
          <Badge variant="destructive" className="text-xs">
            Error
          </Badge>
        )}
      </div>

      {expanded && hasChildren && (
        <div className="border-l border-dashed border-muted-foreground/20 ml-4">
          {node.imports.map((child, idx) => (
            <TreeNode key={`${child.path}-${idx}`} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

export function ImportTree({ files }: ImportTreeProps) {
  const [selectedFile, setSelectedFile] = useState<string>("");
  const [tree, setTree] = useState<ImportTreeNode | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleResolve = async () => {
    if (!selectedFile) return;

    setLoading(true);
    setError(null);
    setTree(null);

    try {
      const params = { file_path: selectedFile };
      const response = await apiClient<ImportTreeResponse>(
        buildEndpoint("memory/imports", params)
      );
      setTree(response.tree);

      if (response.tree.imports.length === 0) {
        toast.info("No imports found in this file");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resolve imports");
      toast.error("Failed to resolve imports");
    } finally {
      setLoading(false);
    }
  };

  const countImports = (node: ImportTreeNode): { total: number; missing: number; cycles: number } => {
    let total = 0;
    let missing = 0;
    let cycles = 0;

    const traverse = (n: ImportTreeNode) => {
      total++;
      if (!n.exists) missing++;
      if (n.cycle) cycles++;
      n.imports.forEach(traverse);
    };

    node.imports.forEach(traverse);
    return { total, missing, cycles };
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <GitBranch className="h-5 w-5" />
          Import Resolver
        </CardTitle>
        <CardDescription>
          Visualize and validate @import references in memory files
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {files.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            <Link className="h-8 w-8 mx-auto mb-2 opacity-50" />
            <p>No memory files to analyze</p>
            <p className="text-sm">Create a CLAUDE.md file first</p>
          </div>
        ) : (
          <>
            <div className="flex gap-2">
              <Select value={selectedFile} onValueChange={setSelectedFile}>
                <SelectTrigger className="flex-1">
                  <SelectValue placeholder="Select a file to analyze" />
                </SelectTrigger>
                <SelectContent>
                  {files.map((file) => (
                    <SelectItem key={file.path} value={file.path}>
                      <div className="flex items-center gap-2">
                        <FileText className="h-4 w-4" />
                        <span>
                          {file.scope.charAt(0).toUpperCase() + file.scope.slice(1)}{" "}
                          CLAUDE.md
                        </span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                onClick={handleResolve}
                disabled={!selectedFile || loading}
                className="gap-2"
              >
                <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
                Resolve
              </Button>
            </div>

            {error && (
              <div className="text-destructive bg-destructive/10 rounded-md p-3">
                {error}
              </div>
            )}

            {tree && (
              <div className="space-y-3">
                {/* Summary */}
                {tree.imports.length > 0 && (
                  <div className="flex gap-2 text-sm">
                    {(() => {
                      const stats = countImports(tree);
                      return (
                        <>
                          <Badge variant="secondary">{stats.total} imports</Badge>
                          {stats.missing > 0 && (
                            <Badge variant="destructive">
                              {stats.missing} missing
                            </Badge>
                          )}
                          {stats.cycles > 0 && (
                            <Badge
                              variant="outline"
                              className="text-yellow-600 border-yellow-600"
                            >
                              {stats.cycles} cycles
                            </Badge>
                          )}
                        </>
                      );
                    })()}
                  </div>
                )}

                {/* Tree visualization */}
                <div className="border rounded-lg p-3 bg-muted/30">
                  <TreeNode node={tree} depth={0} />
                </div>

                {/* Legend */}
                <div className="flex gap-4 text-xs text-muted-foreground">
                  <div className="flex items-center gap-1">
                    <FileText className="h-3 w-3" />
                    <span>Exists</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <XCircle className="h-3 w-3 text-destructive" />
                    <span>Missing</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <AlertTriangle className="h-3 w-3 text-yellow-500" />
                    <span>Circular reference</span>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
