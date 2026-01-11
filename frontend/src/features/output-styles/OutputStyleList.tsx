import { Pencil, Trash2, User, FolderOpen, Paintbrush, Code } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import { type OutputStyle, type OutputStyleScope } from "@/types/output-styles";

interface OutputStyleListProps {
  styles: OutputStyle[];
  onEdit: (style: OutputStyle) => void;
  onDelete: (name: string, scope: OutputStyleScope) => void;
}

export function OutputStyleList({ styles, onEdit, onDelete }: OutputStyleListProps) {
  const userStyles = styles.filter((s) => s.scope === "user");
  const projectStyles = styles.filter((s) => s.scope === "project");

  const renderStyleCard = (style: OutputStyle) => (
    <Card key={`${style.scope}-${style.name}`} className="hover:bg-muted/50 transition-colors">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <Paintbrush className="h-5 w-5 text-primary" />
            <CardTitle className="text-lg">{style.name}</CardTitle>
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onEdit(style)}
              title="Edit output style"
            >
              <Pencil className="h-4 w-4" />
            </Button>

            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-destructive hover:text-destructive"
                  title="Delete output style"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete Output Style</AlertDialogTitle>
                  <AlertDialogDescription>
                    Are you sure you want to delete the output style "{style.name}"?
                    This action cannot be undone.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => onDelete(style.name, style.scope)}
                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  >
                    Delete
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </div>
        {style.description && (
          <CardDescription>{style.description}</CardDescription>
        )}
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-2">
          {/* Scope Badge */}
          <Badge variant="outline" className="flex items-center gap-1">
            {style.scope === "user" ? (
              <>
                <User className="h-3 w-3" />
                User
              </>
            ) : (
              <>
                <FolderOpen className="h-3 w-3" />
                Project
              </>
            )}
          </Badge>

          {/* Keep Coding Instructions Badge */}
          {style.keep_coding_instructions && (
            <Badge variant="secondary" className="flex items-center gap-1">
              <Code className="h-3 w-3" />
              Keep Coding Instructions
            </Badge>
          )}
        </div>

        {/* Content Preview */}
        {style.content && (
          <div className="mt-3 p-2 bg-muted rounded text-xs font-mono text-muted-foreground line-clamp-2">
            {style.content}
          </div>
        )}
      </CardContent>
    </Card>
  );

  if (styles.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No output styles configured. Create your first output style to customize Claude Code responses.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* User Styles */}
      {userStyles.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <User className="h-5 w-5" />
            User Styles
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {userStyles.map(renderStyleCard)}
          </div>
        </div>
      )}

      {/* Project Styles */}
      {projectStyles.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <FolderOpen className="h-5 w-5" />
            Project Styles
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {projectStyles.map(renderStyleCard)}
          </div>
        </div>
      )}
    </div>
  );
}
