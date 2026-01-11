import { Pencil, Trash2, User, FolderOpen, Bot, Wrench, Cpu, Puzzle } from "lucide-react";
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
import { type Agent, type AgentScope } from "@/types/agents";

interface AgentListProps {
  agents: Agent[];
  onEdit: (agent: Agent) => void;
  onDelete: (name: string, scope: AgentScope) => void;
}

export function AgentList({ agents, onEdit, onDelete }: AgentListProps) {
  const userAgents = agents.filter((a) => a.scope === "user");
  const projectAgents = agents.filter((a) => a.scope === "project");
  const pluginAgents = agents.filter((a) => a.scope.startsWith("plugin:"));

  // Group plugin agents by plugin name
  const pluginGroups: Record<string, Agent[]> = {};
  pluginAgents.forEach((agent) => {
    const pluginName = agent.scope.replace("plugin:", "");
    if (!pluginGroups[pluginName]) {
      pluginGroups[pluginName] = [];
    }
    pluginGroups[pluginName].push(agent);
  });

  const isPluginAgent = (agent: Agent) => agent.scope.startsWith("plugin:");

  const renderAgentCard = (agent: Agent) => (
    <Card key={`${agent.scope}-${agent.name}`} className="hover:bg-muted/50 transition-colors">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <Bot className="h-5 w-5 text-primary" />
            <CardTitle className="text-lg">{agent.name}</CardTitle>
          </div>
          {/* Only show edit/delete for non-plugin agents */}
          {!isPluginAgent(agent) && (
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                onClick={() => onEdit(agent)}
                title="Edit agent"
              >
                <Pencil className="h-4 w-4" />
              </Button>

              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="text-destructive hover:text-destructive"
                    title="Delete agent"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Delete Agent</AlertDialogTitle>
                    <AlertDialogDescription>
                      Are you sure you want to delete the agent "{agent.name}"?
                      This action cannot be undone.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction
                      onClick={() => onDelete(agent.name, agent.scope)}
                      className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                    >
                      Delete
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          )}
        </div>
        {agent.description && (
          <CardDescription className="line-clamp-2">{agent.description}</CardDescription>
        )}
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-2">
          {/* Scope Badge */}
          <Badge variant="outline" className="flex items-center gap-1">
            {agent.scope === "user" ? (
              <>
                <User className="h-3 w-3" />
                User
              </>
            ) : agent.scope === "project" ? (
              <>
                <FolderOpen className="h-3 w-3" />
                Project
              </>
            ) : (
              <>
                <Puzzle className="h-3 w-3" />
                Plugin
              </>
            )}
          </Badge>

          {/* Model Badge */}
          {agent.model && (
            <Badge variant="secondary" className="flex items-center gap-1">
              <Cpu className="h-3 w-3" />
              {agent.model}
            </Badge>
          )}

          {/* Tools Badge */}
          {agent.tools && agent.tools.length > 0 && (
            <Badge variant="secondary" className="flex items-center gap-1">
              <Wrench className="h-3 w-3" />
              {agent.tools.length} tools
            </Badge>
          )}
        </div>

        {/* Show first few tools */}
        {agent.tools && agent.tools.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {agent.tools.slice(0, 5).map((tool) => (
              <Badge key={tool} variant="outline" className="text-xs">
                {tool}
              </Badge>
            ))}
            {agent.tools.length > 5 && (
              <Badge variant="outline" className="text-xs">
                +{agent.tools.length - 5} more
              </Badge>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );

  if (agents.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No agents configured. Create your first agent to get started.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* User Agents */}
      {userAgents.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <User className="h-5 w-5" />
            User Agents
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {userAgents.map(renderAgentCard)}
          </div>
        </div>
      )}

      {/* Project Agents */}
      {projectAgents.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <FolderOpen className="h-5 w-5" />
            Project Agents
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {projectAgents.map(renderAgentCard)}
          </div>
        </div>
      )}

      {/* Plugin Agents - Grouped by plugin */}
      {Object.entries(pluginGroups).map(([pluginName, pluginAgentList]) => (
        <div key={pluginName} className="space-y-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Puzzle className="h-5 w-5 text-success" />
            {pluginName}
            <Badge variant="secondary" className="text-xs">
              {pluginAgentList.length} agent{pluginAgentList.length !== 1 ? "s" : ""}
            </Badge>
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {pluginAgentList.map(renderAgentCard)}
          </div>
        </div>
      ))}
    </div>
  );
}
