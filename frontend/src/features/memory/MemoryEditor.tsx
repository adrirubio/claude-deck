import { useState, useEffect, useCallback } from "react";
import { Save, X, FileText, AlertTriangle, Trash2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { MarkdownPreviewToggle } from "@/components/shared/MarkdownPreviewToggle";
import { MODAL_SIZES } from "@/lib/constants";
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
import type {
  MemoryHierarchyItem,
  MemoryFileResponse,
  SaveMemoryResponse,
} from "@/types/memory";

interface MemoryEditorProps {
  open: boolean;
  onClose: () => void;
  file: MemoryHierarchyItem;
  projectPath?: string;
  onSaveSuccess: () => void;
}

export function MemoryEditor({
  open,
  onClose,
  file,
  onSaveSuccess,
}: MemoryEditorProps) {
  const [content, setContent] = useState("");
  const [originalContent, setOriginalContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [imports, setImports] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const hasChanges = content !== originalContent;

  const loadFile = useCallback(async () => {
    setLoading(true);
    setError(null);

    if (!file.exists) {
      const template = getTemplate(file.scope);
      setContent(template);
      setOriginalContent("");
      setImports([]);
      setLoading(false);
      return;
    }

    try {
      const params = { file_path: file.path, include_imports: true };
      const response = await apiClient<MemoryFileResponse>(
        buildEndpoint("memory/file", params)
      );

      if (response.error) {
        setError(response.error);
        return;
      }

      setContent(response.content || "");
      setOriginalContent(response.content || "");
      setImports(response.imports || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load file");
      toast.error("Failed to load file");
    } finally {
      setLoading(false);
    }
  }, [file]);

  useEffect(() => {
    if (open && file) {
      loadFile();
    }
  }, [open, file, loadFile]);

  const handleSave = async () => {
    if (file.readonly) {
      toast.error("This file is read-only");
      return;
    }

    setSaving(true);
    try {
      const params = { file_path: file.path };
      await apiClient<SaveMemoryResponse>(buildEndpoint("memory/file", params), {
        method: "PUT",
        body: JSON.stringify({ content }),
      });

      setOriginalContent(content);
      onSaveSuccess();
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save file");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (file.readonly || !file.exists) {
      return;
    }

    try {
      const params = { file_path: file.path };
      await apiClient<SaveMemoryResponse>(buildEndpoint("memory/file", params), {
        method: "DELETE",
      });

      toast.success("File deleted");
      onSaveSuccess();
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete file");
    }
  };

  const handleClose = () => {
    if (hasChanges) {
      if (confirm("You have unsaved changes. Are you sure you want to close?")) {
        onClose();
      }
    } else {
      onClose();
    }
  };

  const getTemplate = (scope: string): string => {
    switch (scope) {
      case "user":
        return `# User Preferences

These instructions apply to all projects.

## General Preferences

- 

## Code Style

- 
`;
      case "project":
        return `# Project Instructions

These instructions apply to this project.

## Overview

Brief description of the project.

## Guidelines

- 

## Important Files

- 
`;
      case "local":
        return `# Local Preferences

Personal preferences for this project (not committed to git).

## Notes

- 
`;
      default:
        return "";
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
      <DialogContent className={`${MODAL_SIZES.LG} h-[80vh] flex flex-col`}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            {file.scope.charAt(0).toUpperCase() + file.scope.slice(1)} CLAUDE.md
            {file.readonly && (
              <Badge variant="outline" className="ml-2">
                Read-only
              </Badge>
            )}
            {hasChanges && (
              <Badge variant="default" className="ml-2">
                Modified
              </Badge>
            )}
          </DialogTitle>
          <DialogDescription className="font-mono text-xs">
            {file.path}
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 min-h-0 space-y-3">
          {/* Imports indicator */}
          {imports.length > 0 && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground bg-muted/50 rounded-md p-2">
              <AlertTriangle className="h-4 w-4" />
              <span>
                This file imports {imports.length} other file(s):{" "}
                {imports.slice(0, 3).join(", ")}
                {imports.length > 3 && ` and ${imports.length - 3} more`}
              </span>
            </div>
          )}

          {error ? (
            <div className="flex items-center gap-2 text-destructive bg-destructive/10 rounded-md p-3">
              <AlertTriangle className="h-4 w-4" />
              <span>{error}</span>
            </div>
          ) : loading ? (
            <div className="flex items-center justify-center h-full">
              <span className="text-muted-foreground">Loading...</span>
            </div>
          ) : (
            <MarkdownPreviewToggle
              value={content}
              onChange={setContent}
              placeholder="Enter markdown content..."
              minHeight="400px"
              disabled={file.readonly}
              defaultTab={file.readonly ? "preview" : "edit"}
            />
          )}
        </div>

        <DialogFooter className="flex items-center justify-between sm:justify-between">
          <div>
            {file.exists && !file.readonly && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button variant="destructive" size="sm" className="gap-2">
                    <Trash2 className="h-4 w-4" />
                    Delete
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Delete this file?</AlertDialogTitle>
                    <AlertDialogDescription>
                      This will permanently delete{" "}
                      <span className="font-mono">{file.path}</span>. This action
                      cannot be undone.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction
                      onClick={handleDelete}
                      className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                    >
                      Delete
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={handleClose}>
              <X className="h-4 w-4 mr-2" />
              Cancel
            </Button>
            <Button
              onClick={handleSave}
              disabled={!hasChanges || file.readonly || saving}
            >
              <Save className="h-4 w-4 mr-2" />
              {saving ? "Saving..." : "Save"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
