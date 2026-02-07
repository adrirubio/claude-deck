import { User, FolderOpen, Puzzle, Loader2, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { SlashCommand } from "@/types/commands";
import { CommandCard } from "./CommandCard";

interface CommandListProps {
  commands: SlashCommand[];
  loading: boolean;
  searchQuery: string;
  onViewDetail: (command: SlashCommand) => void;
  onEdit: (command: SlashCommand) => void;
  onDelete: (command: SlashCommand) => void;
}

export function CommandList({
  commands,
  loading,
  searchQuery,
  onViewDetail,
  onEdit,
  onDelete,
}: CommandListProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (commands.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No commands found. Click "Add Command" to create one.
      </div>
    );
  }

  // Filter by search query
  const query = searchQuery.toLowerCase();
  const filtered = query
    ? commands.filter(
        (cmd) =>
          cmd.name.toLowerCase().includes(query) ||
          (cmd.description?.toLowerCase().includes(query)) ||
          (cmd.content?.toLowerCase().includes(query))
      )
    : commands;

  if (filtered.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        <Search className="h-8 w-8 mx-auto mb-2 opacity-50" />
        <p>No commands match "{searchQuery}"</p>
      </div>
    );
  }

  // Group by scope
  const userCommands = filtered.filter((c) => c.scope === "user");
  const projectCommands = filtered.filter((c) => c.scope === "project");
  const pluginCommands = filtered.filter((c) => c.scope.startsWith("plugin:"));

  // Group plugin commands by plugin name
  const pluginGroups: Record<string, SlashCommand[]> = {};
  pluginCommands.forEach((cmd) => {
    const pluginName = cmd.scope.replace("plugin:", "");
    if (!pluginGroups[pluginName]) {
      pluginGroups[pluginName] = [];
    }
    pluginGroups[pluginName].push(cmd);
  });

  return (
    <div className="space-y-6">
      {/* User Commands */}
      {userCommands.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <User className="h-5 w-5" />
            User Commands
            <Badge variant="secondary">{userCommands.length}</Badge>
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {userCommands.map((cmd) => (
              <CommandCard
                key={`${cmd.scope}-${cmd.path}`}
                command={cmd}
                onViewDetail={onViewDetail}
                onEdit={onEdit}
                onDelete={onDelete}
              />
            ))}
          </div>
        </div>
      )}

      {/* Project Commands */}
      {projectCommands.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <FolderOpen className="h-5 w-5" />
            Project Commands
            <Badge variant="secondary">{projectCommands.length}</Badge>
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {projectCommands.map((cmd) => (
              <CommandCard
                key={`${cmd.scope}-${cmd.path}`}
                command={cmd}
                onViewDetail={onViewDetail}
                onEdit={onEdit}
                onDelete={onDelete}
              />
            ))}
          </div>
        </div>
      )}

      {/* Plugin Commands - Grouped by plugin */}
      {Object.entries(pluginGroups).map(([pluginName, cmds]) => (
        <div key={pluginName} className="space-y-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Puzzle className="h-5 w-5 text-emerald-500" />
            {pluginName}
            <Badge variant="secondary">
              {cmds.length} command{cmds.length !== 1 ? "s" : ""}
            </Badge>
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {cmds.map((cmd) => (
              <CommandCard
                key={`${cmd.scope}-${cmd.path}`}
                command={cmd}
                onViewDetail={onViewDetail}
                onEdit={onEdit}
                onDelete={onDelete}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
