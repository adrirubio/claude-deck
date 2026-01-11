import { Download, Trash2, RotateCcw, Archive, User, FolderOpen, Globe } from "lucide-react";
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
import { type Backup, type BackupScope, formatBytes, formatDate } from "@/types/backup";

interface BackupListProps {
  backups: Backup[];
  onRestore: (backup: Backup) => void;
  onDownload: (backup: Backup) => void;
  onDelete: (backup: Backup) => void;
}

export function BackupList({ backups, onRestore, onDownload, onDelete }: BackupListProps) {
  const getScopeIcon = (scope: BackupScope) => {
    switch (scope) {
      case "full":
        return <Globe className="h-4 w-4" />;
      case "user":
        return <User className="h-4 w-4" />;
      case "project":
        return <FolderOpen className="h-4 w-4" />;
    }
  };

  const getScopeBadgeVariant = (scope: BackupScope) => {
    switch (scope) {
      case "full":
        return "default" as const;
      case "user":
        return "secondary" as const;
      case "project":
        return "outline" as const;
    }
  };

  if (backups.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <Archive className="h-12 w-12 mx-auto mb-4 opacity-50" />
        <p className="text-lg">No backups found</p>
        <p className="text-sm mt-1">Create your first backup to get started</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {backups.map((backup) => (
        <Card key={backup.id} className="hover:bg-muted/50 transition-colors">
          <CardHeader className="pb-2">
            <div className="flex items-start justify-between">
              <div>
                <CardTitle className="text-lg flex items-center gap-2">
                  <Archive className="h-5 w-5 text-primary" />
                  {backup.name}
                </CardTitle>
                {backup.description && (
                  <CardDescription className="mt-1">
                    {backup.description}
                  </CardDescription>
                )}
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => onDownload(backup)}
                  title="Download backup"
                >
                  <Download className="h-4 w-4" />
                </Button>

                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      title="Restore backup"
                    >
                      <RotateCcw className="h-4 w-4" />
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Restore Backup</AlertDialogTitle>
                      <AlertDialogDescription>
                        This will restore all files from this backup. Existing
                        files will be overwritten. This action cannot be undone.
                        <br /><br />
                        <strong>Backup:</strong> {backup.name}
                        <br />
                        <strong>Created:</strong> {formatDate(backup.created_at)}
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction onClick={() => onRestore(backup)}>
                        Restore
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>

                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="text-destructive hover:text-destructive"
                      title="Delete backup"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Delete Backup</AlertDialogTitle>
                      <AlertDialogDescription>
                        Are you sure you want to delete this backup? This action
                        cannot be undone.
                        <br /><br />
                        <strong>Backup:</strong> {backup.name}
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => onDelete(backup)}
                        className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                      >
                        Delete
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2 text-sm">
              <Badge variant={getScopeBadgeVariant(backup.scope)} className="flex items-center gap-1">
                {getScopeIcon(backup.scope)}
                {backup.scope.charAt(0).toUpperCase() + backup.scope.slice(1)}
              </Badge>
              <Badge variant="outline">
                {formatBytes(backup.size_bytes)}
              </Badge>
              <span className="text-muted-foreground">
                Created: {formatDate(backup.created_at)}
              </span>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
