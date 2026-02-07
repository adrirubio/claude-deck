import { useState } from "react";
import { Pencil, Trash2, User, FolderOpen, Bot, Wrench, Cpu, Puzzle, Info, Shield, Brain, Zap, FileText } from "lucide-react";
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
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
import { type Agent, type AgentScope, PERMISSION_MODES, MEMORY_SCOPES } from "@/types/agents";

interface AgentListProps {
  agents: Agent[];
  onEdit: (agent: Agent) => void;
  onDelete: (name: string, scope: AgentScope) => void;
}

export function AgentList({ agents, onEdit, onDelete }: AgentListProps) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);

  const handleViewDetails = (agent: Agent) => {
    setSelectedAgent(agent);
    setDetailsOpen(true);
  };

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
          <button
            className="flex items-center gap-2 text-left hover:text-primary transition-colors"
            onClick={() => handleViewDetails(agent)}
          >
            <Bot className="h-5 w-5 text-primary" />
            <CardTitle className="text-lg">{agent.name}</CardTitle>
          </button>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => handleViewDetails(agent)}
              title="View details"
            >
              <Info className="h-4 w-4" />
            </Button>
            {/* Only show edit/delete for non-plugin agents */}
            {!isPluginAgent(agent) && (
              <>
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
              </>
            )}
          </div>
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

      {/* Agent Details Dialog */}
      <Dialog open={detailsOpen} onOpenChange={setDetailsOpen}>
        <DialogContent className="sm:max-w-[600px] max-h-[80vh]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Bot className="h-5 w-5" />
              {selectedAgent?.name}
            </DialogTitle>
            <DialogDescription>
              {selectedAgent?.description || "No description"}
            </DialogDescription>
          </DialogHeader>

          {selectedAgent && (
            <ScrollArea className="max-h-[55vh]">
              <div className="space-y-4 pr-4">
                {/* Scope & Model */}
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline" className="flex items-center gap-1">
                    {selectedAgent.scope === "user" ? (
                      <><User className="h-3 w-3" /> User</>
                    ) : selectedAgent.scope === "project" ? (
                      <><FolderOpen className="h-3 w-3" /> Project</>
                    ) : (
                      <><Puzzle className="h-3 w-3" /> Plugin</>
                    )}
                  </Badge>
                  {selectedAgent.model && (
                    <Badge variant="secondary" className="flex items-center gap-1">
                      <Cpu className="h-3 w-3" />
                      {selectedAgent.model}
                    </Badge>
                  )}
                </div>

                {/* Prompt */}
                <div>
                  <h4 className="text-sm font-medium flex items-center gap-2 mb-2">
                    <FileText className="h-4 w-4" />
                    System Prompt
                  </h4>
                  <div className="bg-muted/50 rounded-lg p-3 text-sm whitespace-pre-wrap font-mono text-xs max-h-[150px] overflow-auto">
                    {selectedAgent.prompt || "No prompt defined"}
                  </div>
                </div>

                {/* Tools */}
                {selectedAgent.tools && selectedAgent.tools.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium flex items-center gap-2 mb-2">
                      <Wrench className="h-4 w-4" />
                      Allowed Tools ({selectedAgent.tools.length})
                    </h4>
                    <div className="flex flex-wrap gap-1">
                      {selectedAgent.tools.map((tool) => (
                        <Badge key={tool} variant="secondary" className="text-xs">
                          {tool}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                {/* Disallowed Tools */}
                {selectedAgent.disallowed_tools && selectedAgent.disallowed_tools.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium flex items-center gap-2 mb-2">
                      <Wrench className="h-4 w-4 text-destructive" />
                      Disallowed Tools ({selectedAgent.disallowed_tools.length})
                    </h4>
                    <div className="flex flex-wrap gap-1">
                      {selectedAgent.disallowed_tools.map((tool) => (
                        <Badge key={tool} variant="destructive" className="text-xs">
                          {tool}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                {/* Skills */}
                {selectedAgent.skills && selectedAgent.skills.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium flex items-center gap-2 mb-2">
                      <Zap className="h-4 w-4" />
                      Skills ({selectedAgent.skills.length})
                    </h4>
                    <div className="flex flex-wrap gap-1">
                      {selectedAgent.skills.map((skill) => (
                        <Badge key={skill} variant="outline" className="text-xs">
                          {skill}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                {/* Permission Mode */}
                {selectedAgent.permission_mode && selectedAgent.permission_mode !== "default" && (
                  <div>
                    <h4 className="text-sm font-medium flex items-center gap-2 mb-2">
                      <Shield className="h-4 w-4" />
                      Permission Mode
                    </h4>
                    <Badge variant="outline">
                      {PERMISSION_MODES.find(m => m.value === selectedAgent.permission_mode)?.label || selectedAgent.permission_mode}
                    </Badge>
                    <p className="text-xs text-muted-foreground mt-1">
                      {PERMISSION_MODES.find(m => m.value === selectedAgent.permission_mode)?.description}
                    </p>
                  </div>
                )}

                {/* Memory */}
                {selectedAgent.memory && selectedAgent.memory !== "none" && (
                  <div>
                    <h4 className="text-sm font-medium flex items-center gap-2 mb-2">
                      <Brain className="h-4 w-4" />
                      Memory Scope
                    </h4>
                    <Badge variant="outline">
                      {MEMORY_SCOPES.find(m => m.value === selectedAgent.memory)?.label || selectedAgent.memory}
                    </Badge>
                    <p className="text-xs text-muted-foreground mt-1">
                      {MEMORY_SCOPES.find(m => m.value === selectedAgent.memory)?.description}
                    </p>
                  </div>
                )}

                {/* Hooks */}
                {selectedAgent.hooks && Object.keys(selectedAgent.hooks).length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium flex items-center gap-2 mb-2">
                      <Zap className="h-4 w-4" />
                      Hooks
                    </h4>
                    <div className="space-y-2">
                      {Object.entries(selectedAgent.hooks).map(([event, hooks]) => (
                        <div key={event} className="bg-muted/50 rounded p-2">
                          <span className="text-xs font-medium">{event}</span>
                          <span className="text-xs text-muted-foreground ml-2">
                            ({Array.isArray(hooks) ? hooks.length : 1} hook{Array.isArray(hooks) && hooks.length !== 1 ? "s" : ""})
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </ScrollArea>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
