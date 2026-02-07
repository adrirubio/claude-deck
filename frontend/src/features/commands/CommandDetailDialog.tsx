import { useEffect, useState, useCallback } from "react";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { MarkdownRenderer } from "@/components/shared/MarkdownRenderer";
import { MODAL_SIZES } from "@/lib/constants";
import { Terminal, Shield, Loader2, Pencil, Trash2 } from "lucide-react";
import type { SlashCommand } from "@/types/commands";
import { apiClient, buildEndpoint } from "@/lib/api";
import { useProjectContext } from "@/contexts/ProjectContext";

interface CommandDetailDialogProps {
  command: SlashCommand | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onEdit: (command: SlashCommand) => void;
  onDelete: (command: SlashCommand) => void;
}

export function CommandDetailDialog({
  command,
  open,
  onOpenChange,
  onEdit,
  onDelete,
}: CommandDetailDialogProps) {
  const { activeProject } = useProjectContext();
  const [fullCommand, setFullCommand] = useState<SlashCommand | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchCommandDetails = useCallback(async () => {
    if (!command) return;

    setLoading(true);
    try {
      const endpoint = buildEndpoint(
        `commands/${command.scope}/${command.path}`,
        { project_path: activeProject?.path }
      );
      const data = await apiClient<SlashCommand>(endpoint);
      setFullCommand(data);
    } catch {
      // Fall back to prop data on error
      setFullCommand(command);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [command?.scope, command?.path, activeProject?.path]);

  useEffect(() => {
    if (open && command) {
      fetchCommandDetails();
    } else {
      setFullCommand(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, fetchCommandDetails]);

  if (!command) return null;

  const displayCommand = fullCommand || command;
  const isPlugin = command.scope.startsWith("plugin:");

  const getScopeBadge = () => {
    if (command.scope === "user") {
      return <Badge variant="default">user</Badge>;
    }
    if (command.scope === "project") {
      return <Badge variant="secondary">project</Badge>;
    }
    const pluginName = command.scope.replace("plugin:", "");
    return (
      <Badge variant="outline" className="text-emerald-600 border-emerald-300">
        {pluginName}
      </Badge>
    );
  };

  const handleEdit = () => {
    onOpenChange(false);
    onEdit(displayCommand);
  };

  const handleDelete = () => {
    if (confirm(`Are you sure you want to delete the command "/${command.name}"?`)) {
      onDelete(displayCommand);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={MODAL_SIZES.SM}>
        <DialogHeader>
          <div className="flex items-center gap-3">
            <Terminal className="h-5 w-5" />
            <DialogTitle className="text-xl">/{command.name}</DialogTitle>
            {getScopeBadge()}
          </div>
          <DialogDescription>
            {displayCommand.description || "No description"}
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="space-y-4">
            {/* File path */}
            {displayCommand.path && (
              <div className="space-y-1">
                <div className="text-sm font-medium text-muted-foreground">File</div>
                <code className="block text-sm bg-muted px-3 py-2 rounded-md">
                  {displayCommand.path}
                </code>
              </div>
            )}

            {/* Allowed tools */}
            {displayCommand.allowed_tools && displayCommand.allowed_tools.length > 0 && (
              <div className="space-y-1.5">
                <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                  <Shield className="h-4 w-4" />
                  Allowed Tools
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {displayCommand.allowed_tools.map((tool) => (
                    <Badge key={tool} variant="outline" className="text-xs font-mono">
                      {tool}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {/* Content */}
            {displayCommand.content ? (
              <div className="space-y-1">
                <div className="text-sm font-medium text-muted-foreground">Content</div>
                <div className="border rounded-md p-3 bg-muted/30">
                  <MarkdownRenderer content={displayCommand.content} />
                </div>
              </div>
            ) : (
              <div className="text-center py-4 text-muted-foreground">
                No content available.
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          {!isPlugin && (
            <>
              <Button variant="destructive" onClick={handleDelete}>
                <Trash2 className="h-4 w-4 mr-2" />
                Delete
              </Button>
              <Button onClick={handleEdit}>
                <Pencil className="h-4 w-4 mr-2" />
                Edit
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
