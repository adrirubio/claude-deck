import { Pencil, Trash2, Terminal, Shield } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { SlashCommand } from "@/types/commands";
import { CLICKABLE_CARD } from "@/lib/constants";

interface CommandCardProps {
  command: SlashCommand;
  onViewDetail: (command: SlashCommand) => void;
  onEdit: (command: SlashCommand) => void;
  onDelete: (command: SlashCommand) => void;
}

export function CommandCard({ command, onViewDetail, onEdit, onDelete }: CommandCardProps) {
  const isPlugin = command.scope.startsWith("plugin:");

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm(`Are you sure you want to delete the command "/${command.name}"?`)) {
      onDelete(command);
    }
  };

  const getScopeBadge = () => {
    if (command.scope === "user") {
      return <Badge variant="default">user</Badge>;
    }
    if (command.scope === "project") {
      return <Badge variant="secondary">project</Badge>;
    }
    // Plugin scope
    const pluginName = command.scope.replace("plugin:", "");
    return (
      <Badge variant="outline" className="text-emerald-600 border-emerald-300">
        {pluginName}
      </Badge>
    );
  };

  return (
    <Card
      className={CLICKABLE_CARD}
      tabIndex={0}
      onClick={() => onViewDetail(command)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onViewDetail(command);
        }
      }}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between">
          <CardTitle className="text-lg flex items-center gap-2">
            <Terminal className="h-4 w-4" />
            /{command.name}
          </CardTitle>
          {getScopeBadge()}
        </div>
        <CardDescription className="line-clamp-2">
          {command.description || <span className="text-muted-foreground italic">No description</span>}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {/* Allowed tools badge */}
          {command.allowed_tools && command.allowed_tools.length > 0 && (
            <Badge variant="outline" className="flex items-center gap-1 w-fit">
              <Shield className="h-3 w-3" />
              {command.allowed_tools.length} tools
            </Badge>
          )}

          {/* Content preview */}
          {command.content && (
            <p className="text-sm text-muted-foreground line-clamp-2">
              {command.content.slice(0, 100)}
            </p>
          )}

          {/* Action buttons - hidden for plugin scope */}
          {!isPlugin && (
            <div className="flex gap-2 pt-2" onClick={(e) => e.stopPropagation()}>
              <Button
                variant="outline"
                size="sm"
                onClick={() => onEdit(command)}
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
          )}
        </div>
      </CardContent>
    </Card>
  );
}
