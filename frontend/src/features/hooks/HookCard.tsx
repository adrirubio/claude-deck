import { Pencil, Trash2, Terminal, MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { Hook } from "@/types/hooks";

interface HookCardProps {
  hook: Hook;
  onEdit: (hook: Hook) => void;
  onDelete: (hookId: string, scope: "user" | "project") => void;
}

export function HookCard({ hook, onEdit, onDelete }: HookCardProps) {
  const handleDelete = () => {
    if (
      confirm(
        `Are you sure you want to delete this ${hook.type} hook for ${hook.event}?`
      )
    ) {
      onDelete(hook.id, hook.scope);
    }
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <CardTitle className="text-lg flex items-center gap-2">
              {hook.type === "command" ? (
                <Terminal className="h-4 w-4" />
              ) : (
                <MessageSquare className="h-4 w-4" />
              )}
              {hook.event}
            </CardTitle>
            <CardDescription>
              Type: <span className="font-medium">{hook.type}</span>
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Badge variant={hook.scope === "user" ? "default" : "secondary"}>
              {hook.scope}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {hook.matcher && (
            <div>
              <div className="text-sm font-medium text-muted-foreground">
                Matcher Pattern:
              </div>
              <code className="text-sm bg-muted px-2 py-1 rounded">
                {hook.matcher}
              </code>
            </div>
          )}

          {hook.type === "command" && hook.command && (
            <div>
              <div className="text-sm font-medium text-muted-foreground">
                Command:
              </div>
              <pre className="text-sm bg-muted px-3 py-2 rounded overflow-x-auto">
                {hook.command}
              </pre>
            </div>
          )}

          {hook.type === "prompt" && hook.prompt && (
            <div>
              <div className="text-sm font-medium text-muted-foreground">
                Prompt:
              </div>
              <p className="text-sm bg-muted px-3 py-2 rounded">
                {hook.prompt}
              </p>
            </div>
          )}

          {hook.timeout && (
            <div>
              <div className="text-sm font-medium text-muted-foreground">
                Timeout:
              </div>
              <span className="text-sm">{hook.timeout}s</span>
            </div>
          )}

          <div className="flex gap-2 pt-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => onEdit(hook)}
              className="flex-1"
            >
              <Pencil className="h-4 w-4 mr-2" />
              Edit
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={handleDelete}
              className="flex-1"
            >
              <Trash2 className="h-4 w-4 mr-2" />
              Delete
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
