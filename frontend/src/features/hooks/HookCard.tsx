import { Pencil, Trash2, Terminal, MessageSquare, Bot, Clock, Repeat, Loader2 } from "lucide-react";
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
import { AGENT_MODELS } from "@/types/hooks";

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

  const getTypeIcon = () => {
    switch (hook.type) {
      case "command":
        return <Terminal className="h-4 w-4" />;
      case "prompt":
        return <MessageSquare className="h-4 w-4" />;
      case "agent":
        return <Bot className="h-4 w-4" />;
    }
  };

  const getTypeLabel = () => {
    switch (hook.type) {
      case "command":
        return "Command";
      case "prompt":
        return "Prompt";
      case "agent":
        return "Agent";
    }
  };

  const getModelLabel = (modelValue: string) => {
    const model = AGENT_MODELS.find((m) => m.value === modelValue);
    return model?.label || modelValue;
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <CardTitle className="text-lg flex items-center gap-2">
              {getTypeIcon()}
              {hook.event}
            </CardTitle>
            <CardDescription className="flex items-center gap-2">
              Type: <span className="font-medium">{getTypeLabel()}</span>
              {hook.type === "agent" && hook.model && (
                <>
                  <span className="text-muted-foreground">•</span>
                  <span className="font-medium">{getModelLabel(hook.model)}</span>
                </>
              )}
            </CardDescription>
          </div>
          <div className="flex gap-2 flex-wrap justify-end">
            <Badge variant={hook.scope === "user" ? "default" : "secondary"}>
              {hook.scope}
            </Badge>
            {hook.async_ && (
              <Badge variant="outline" className="flex items-center gap-1">
                <Loader2 className="h-3 w-3" />
                Async
              </Badge>
            )}
            {hook.once && (
              <Badge variant="outline" className="flex items-center gap-1">
                <Repeat className="h-3 w-3" />
                Once
              </Badge>
            )}
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

          {(hook.type === "prompt" || hook.type === "agent") && hook.prompt && (
            <div>
              <div className="text-sm font-medium text-muted-foreground">
                {hook.type === "agent" ? "Agent Prompt:" : "Prompt:"}
              </div>
              <p className="text-sm bg-muted px-3 py-2 rounded whitespace-pre-wrap">
                {hook.prompt}
              </p>
            </div>
          )}

          {hook.statusMessage && (
            <div>
              <div className="text-sm font-medium text-muted-foreground">
                Status Message:
              </div>
              <span className="text-sm italic">"{hook.statusMessage}"</span>
            </div>
          )}

          {hook.timeout && (
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm">Timeout: {hook.timeout}s</span>
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
