import { FileText, Folder, FolderOpen } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import type { SlashCommand, CommandTreeNode } from '../../types/commands';
import { useState } from 'react';

interface CommandListProps {
  commands: SlashCommand[];
  loading: boolean;
  onSelectCommand: (command: SlashCommand) => void;
}

export function CommandList({ commands, loading, onSelectCommand }: CommandListProps) {
  const [expandedNamespaces, setExpandedNamespaces] = useState<Set<string>>(new Set());

  // Build tree structure for commands
  const buildTree = (commands: SlashCommand[]): { user: CommandTreeNode[]; project: CommandTreeNode[] } => {
    const userTree: CommandTreeNode[] = [];
    const projectTree: CommandTreeNode[] = [];

    commands.forEach((command) => {
      const tree = command.scope === 'user' ? userTree : projectTree;
      const parts = command.name.split(':');

      if (parts.length === 1) {
        // Root level command
        tree.push({
          name: command.name,
          path: command.path,
          scope: command.scope,
          isNamespace: false,
          command,
        });
      } else {
        // Namespaced command
        const namespace = parts.slice(0, -1).join(':');
        const commandName = parts[parts.length - 1];

        let namespaceNode = tree.find((n) => n.isNamespace && n.name === namespace);
        if (!namespaceNode) {
          namespaceNode = {
            name: namespace,
            path: '',
            scope: command.scope,
            isNamespace: true,
            children: [],
          };
          tree.push(namespaceNode);
        }

        namespaceNode.children!.push({
          name: commandName,
          path: command.path,
          scope: command.scope,
          isNamespace: false,
          command,
        });
      }
    });

    return { user: userTree, project: projectTree };
  };

  const toggleNamespace = (namespace: string) => {
    const newExpanded = new Set(expandedNamespaces);
    if (newExpanded.has(namespace)) {
      newExpanded.delete(namespace);
    } else {
      newExpanded.add(namespace);
    }
    setExpandedNamespaces(newExpanded);
  };

  const renderTreeNode = (node: CommandTreeNode, depth: number = 0) => {
    if (node.isNamespace) {
      const isExpanded = expandedNamespaces.has(node.name);
      return (
        <div key={node.name} style={{ paddingLeft: `${depth * 16}px` }}>
          <div
            className="flex items-center gap-2 p-2 hover:bg-muted rounded cursor-pointer"
            onClick={() => toggleNamespace(node.name)}
          >
            {isExpanded ? (
              <FolderOpen className="h-4 w-4 text-primary" />
            ) : (
              <Folder className="h-4 w-4 text-primary" />
            )}
            <span className="font-medium">{node.name}</span>
          </div>
          {isExpanded && node.children && (
            <div>
              {node.children.map((child) => renderTreeNode(child, depth + 1))}
            </div>
          )}
        </div>
      );
    }

    return (
      <div key={node.path} style={{ paddingLeft: `${depth * 16}px` }}>
        <div
          className="flex items-center gap-2 p-2 hover:bg-muted rounded cursor-pointer group"
          onClick={() => node.command && onSelectCommand(node.command)}
        >
          <FileText className="h-4 w-4 text-muted-foreground group-hover:text-foreground" />
          <span className="group-hover:text-foreground">{node.name}</span>
        </div>
      </div>
    );
  };

  if (loading) {
    return (
      <Card>
        <CardContent className="pt-6">
          <p className="text-center text-muted-foreground">Loading commands...</p>
        </CardContent>
      </Card>
    );
  }

  const { user, project } = buildTree(commands);

  if (commands.length === 0) {
    return (
      <Card>
        <CardContent className="pt-6">
          <p className="text-center text-muted-foreground">
            No commands found. Click "Add Command" to create one.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid gap-6 grid-cols-1 lg:grid-cols-2">
      {/* User Commands */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            User Commands
            <Badge variant="secondary">{user.length}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {user.length === 0 ? (
            <p className="text-sm text-muted-foreground">No user commands</p>
          ) : (
            <div className="space-y-1">
              {user.map((node) => renderTreeNode(node))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Project Commands */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Project Commands
            <Badge variant="secondary">{project.length}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {project.length === 0 ? (
            <p className="text-sm text-muted-foreground">No project commands</p>
          ) : (
            <div className="space-y-1">
              {project.map((node) => renderTreeNode(node))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
