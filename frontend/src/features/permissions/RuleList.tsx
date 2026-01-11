import { Pencil, Trash2, User, FolderOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
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
import {
  type PermissionRule,
  type PermissionType,
  type PermissionScope,
} from "@/types/permissions";

interface RuleListProps {
  rules: PermissionRule[];
  type: PermissionType;
  onEdit: (rule: PermissionRule) => void;
  onDelete: (ruleId: string, scope: PermissionScope) => void;
}

export function RuleList({ rules, type, onEdit, onDelete }: RuleListProps) {
  if (rules.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No {type} rules configured
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {rules.map((rule) => (
        <Card key={rule.id} className="hover:bg-muted/50 transition-colors">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {/* Pattern */}
                <code className="text-sm bg-muted px-2 py-1 rounded font-mono">
                  {rule.pattern}
                </code>

                {/* Scope Badge */}
                <Badge variant="outline" className="flex items-center gap-1">
                  {rule.scope === "user" ? (
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
              </div>

              {/* Actions */}
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => onEdit(rule)}
                  title="Edit rule"
                >
                  <Pencil className="h-4 w-4" />
                </Button>

                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="text-destructive hover:text-destructive"
                      title="Delete rule"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Delete Permission Rule</AlertDialogTitle>
                      <AlertDialogDescription>
                        Are you sure you want to delete this {type} rule?
                        <br />
                        <code className="mt-2 block bg-muted p-2 rounded">
                          {rule.pattern}
                        </code>
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => onDelete(rule.id, rule.scope)}
                        className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                      >
                        Delete
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
