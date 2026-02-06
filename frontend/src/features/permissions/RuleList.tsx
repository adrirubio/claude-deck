import { Pencil, Trash2, User, FolderOpen, ShieldCheck, ShieldQuestion, ShieldX } from "lucide-react";
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

function getTypeIcon(type: PermissionType) {
  switch (type) {
    case "allow":
      return <ShieldCheck className="h-4 w-4 text-success" />;
    case "ask":
      return <ShieldQuestion className="h-4 w-4 text-warning" />;
    case "deny":
      return <ShieldX className="h-4 w-4 text-destructive" />;
  }
}

function getTypeBorderClass(type: PermissionType) {
  switch (type) {
    case "allow":
      return "border-l-4 border-l-success";
    case "ask":
      return "border-l-4 border-l-warning";
    case "deny":
      return "border-l-4 border-l-destructive";
  }
}

function getTypeLabel(type: PermissionType) {
  switch (type) {
    case "allow":
      return "allowed";
    case "ask":
      return "ask";
    case "deny":
      return "denied";
  }
}

export function RuleList({ rules, type, onEdit, onDelete }: RuleListProps) {
  if (rules.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        <div className="flex flex-col items-center gap-2">
          {getTypeIcon(type)}
          <span>No {getTypeLabel(type)} rules configured</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {rules.map((rule) => (
        <Card
          key={rule.id}
          className={`hover:bg-muted/50 transition-colors ${getTypeBorderClass(rule.type)}`}
        >
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {/* Type Icon */}
                {getTypeIcon(rule.type)}

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

                {/* Pattern Type Hints */}
                {rule.pattern.includes("domain:") && (
                  <Badge variant="secondary" className="text-xs">
                    domain filter
                  </Badge>
                )}
                {rule.pattern.startsWith("MCP(") && (
                  <Badge variant="secondary" className="text-xs">
                    MCP
                  </Badge>
                )}
                {rule.pattern.startsWith("Skill(") && (
                  <Badge variant="secondary" className="text-xs">
                    skill
                  </Badge>
                )}
                {rule.pattern.startsWith("Task") && (
                  <Badge variant="secondary" className="text-xs">
                    subagent
                  </Badge>
                )}
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
