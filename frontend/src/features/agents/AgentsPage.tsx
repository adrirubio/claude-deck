import { useState, useEffect, useCallback } from "react";
import { Plus, Bot } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { AgentList } from "./AgentList";
import { AgentEditor } from "./AgentEditor";
import { AgentWizard } from "./AgentWizard";
import { RefreshButton } from "@/components/shared/RefreshButton";
import { apiClient, buildEndpoint } from "@/lib/api";
import { useProjectContext } from "@/contexts/ProjectContext";
import { toast } from "sonner";
import {
  type Agent,
  type AgentCreate,
  type AgentUpdate,
  type AgentScope,
  type AgentListResponse,
} from "@/types/agents";

export function AgentsPage() {
  const { activeProject } = useProjectContext();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);
  const [showWizard, setShowWizard] = useState(false);

  const fetchAgents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { project_path: activeProject?.path };
      const response = await apiClient<AgentListResponse>(
        buildEndpoint("agents", params)
      );
      setAgents(response.agents);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch agents");
      toast.error("Failed to load agents");
    } finally {
      setLoading(false);
    }
  }, [activeProject?.path]);

  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  const handleCreate = async (agent: AgentCreate) => {
    try {
      const endpoint = buildEndpoint("agents", {
        project_path: activeProject?.path,
      });
      await apiClient<Agent>(endpoint, {
        method: "POST",
        body: JSON.stringify(agent),
      });
      toast.success("Agent created");
      await fetchAgents();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create agent");
      throw err;
    }
  };

  const handleEdit = (agent: Agent) => {
    setEditingAgent(agent);
  };

  const handleUpdate = async (update: AgentUpdate) => {
    if (!editingAgent) return;

    try {
      const endpoint = buildEndpoint(
        `agents/${editingAgent.scope}/${editingAgent.name}`,
        { project_path: activeProject?.path }
      );
      await apiClient<Agent>(endpoint, {
        method: "PUT",
        body: JSON.stringify(update),
      });
      toast.success("Agent updated");
      await fetchAgents();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update agent");
      throw err;
    }
  };

  const handleDelete = async (name: string, scope: AgentScope) => {
    try {
      const endpoint = buildEndpoint(`agents/${scope}/${name}`, {
        project_path: activeProject?.path,
      });
      await apiClient(endpoint, { method: "DELETE" });
      toast.success("Agent deleted");
      await fetchAgents();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete agent");
    }
  };

  // Count agents by scope
  const userAgents = agents.filter((a) => a.scope === "user");
  const pluginAgents = agents.filter((a) => a.scope.startsWith("plugin:"));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Bot className="h-8 w-8" />
            Agents
          </h1>
          <p className="text-muted-foreground mt-1">
            Manage custom agents that can be invoked using the Task tool
          </p>
        </div>
        <div className="flex gap-2">
          <RefreshButton onClick={fetchAgents} loading={loading} />
          <Button onClick={() => setShowWizard(true)}>
            <Plus className="h-4 w-4 mr-2" />
            New Agent
          </Button>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-destructive">Error</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      )}

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardHeader className="pb-3">
            <CardDescription className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-primary" />
              Total Agents
            </CardDescription>
            <CardTitle className="text-3xl">{agents.length}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-blue-500" />
              User Agents
            </CardDescription>
            <CardTitle className="text-3xl">{userAgents.length}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-success" />
              Plugin Agents
            </CardDescription>
            <CardTitle className="text-3xl">{pluginAgents.length}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Agents List */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bot className="h-5 w-5 text-primary" />
            All Agents
          </CardTitle>
          <CardDescription>
            Custom agents grouped by scope (user, project, plugin)
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="text-center py-8 text-muted-foreground">
              Loading...
            </div>
          ) : (
            <AgentList
              agents={agents}
              onEdit={handleEdit}
              onDelete={handleDelete}
            />
          )}
        </CardContent>
      </Card>

      {/* Agent Editor Dialog */}
      <AgentEditor
        open={!!editingAgent}
        onOpenChange={(open) => {
          if (!open) setEditingAgent(null);
        }}
        agent={editingAgent}
        onSave={handleUpdate}
      />

      {/* Agent Wizard Dialog */}
      <AgentWizard
        open={showWizard}
        onOpenChange={setShowWizard}
        onCreate={handleCreate}
      />
    </div>
  );
}
