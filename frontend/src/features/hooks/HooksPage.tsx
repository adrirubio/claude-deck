import { useState, useEffect, useCallback } from "react";
import { Plus, Webhook } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { HookList } from "./HookList";
import { HookEditor } from "./HookEditor";
import { HookWizard } from "./HookWizard";
import { RefreshButton } from "@/components/shared/RefreshButton";
import { apiClient, buildEndpoint } from "@/lib/api";
import { useProjectContext } from "@/contexts/ProjectContext";
import { toast } from "sonner";
import {
  HOOK_EVENTS,
  type Hook,
  type HookEvent,
  type HookType,
  type HookListResponse,
} from "@/types/hooks";

export function HooksPage() {
  const { activeProject } = useProjectContext();
  const [hooks, setHooks] = useState<Hook[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<HookEvent>("PreToolUse");
  const [editingHook, setEditingHook] = useState<Hook | null>(null);
  const [showEditor, setShowEditor] = useState(false);
  const [showWizard, setShowWizard] = useState(false);

  const fetchHooks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const endpoint = buildEndpoint("hooks", { project_path: activeProject?.path });
      const response = await apiClient<HookListResponse>(endpoint);
      setHooks(response.hooks);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch hooks");
      toast.error("Failed to load hooks");
    } finally {
      setLoading(false);
    }
  }, [activeProject?.path]);

  useEffect(() => {
    fetchHooks();
  }, [fetchHooks]);

  const handleCreate = async (hook: {
    event: HookEvent;
    matcher?: string;
    type: HookType;
    command?: string;
    prompt?: string;
    timeout?: number;
    scope: "user" | "project";
  }) => {
    try {
      const endpoint = buildEndpoint("hooks", { project_path: activeProject?.path });
      await apiClient<Hook>(endpoint, { method: "POST", body: JSON.stringify(hook) });
      toast.success("Hook created successfully");
      await fetchHooks();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create hook");
      throw err;
    }
  };

  const handleEdit = (hook: Hook) => {
    setEditingHook(hook);
    setShowEditor(true);
  };

  const handleUpdate = async (
    hookId: string,
    scope: "user" | "project",
    updates: {
      event?: HookEvent;
      matcher?: string;
      type?: HookType;
      command?: string;
      prompt?: string;
      timeout?: number;
    }
  ) => {
    try {
      const endpoint = buildEndpoint(`hooks/${hookId}`, { scope, project_path: activeProject?.path });
      await apiClient<Hook>(endpoint, { method: "PUT", body: JSON.stringify(updates) });
      toast.success("Hook updated successfully");
      await fetchHooks();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update hook");
      throw err;
    }
  };

  const handleDelete = async (hookId: string, scope: "user" | "project") => {
    try {
      const endpoint = buildEndpoint(`hooks/${hookId}`, { scope, project_path: activeProject?.path });
      await apiClient(endpoint, { method: "DELETE" });
      toast.success("Hook deleted successfully");
      await fetchHooks();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete hook");
    }
  };

  const getHooksByEvent = (event: HookEvent) => {
    return hooks.filter((h) => h.event === event);
  };

  const getEventHookCount = (event: HookEvent) => {
    return hooks.filter((h) => h.event === event).length;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Webhook className="h-8 w-8" />
            Hooks
          </h1>
          <p className="text-muted-foreground mt-1">
            Customize Claude Code behavior with hooks triggered by events
          </p>
        </div>
        <div className="flex gap-2">
          <RefreshButton onClick={fetchHooks} loading={loading} />
          <Button onClick={() => setShowWizard(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Add Hook
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
            <CardDescription>Total Hooks</CardDescription>
            <CardTitle className="text-3xl">{hooks.length}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>User Hooks</CardDescription>
            <CardTitle className="text-3xl">
              {hooks.filter((h) => h.scope === "user").length}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Project Hooks</CardDescription>
            <CardTitle className="text-3xl">
              {hooks.filter((h) => h.scope === "project").length}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Hooks by Event Type (Tabs) */}
      <Card>
        <CardHeader>
          <CardTitle>Hooks by Event Type</CardTitle>
          <CardDescription>
            Browse and manage hooks organized by when they trigger
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs
            value={selectedEvent}
            onValueChange={(v) => setSelectedEvent(v as HookEvent)}
          >
            <TabsList className="grid w-full grid-cols-3 lg:grid-cols-5 xl:grid-cols-9 gap-2 h-auto">
              {HOOK_EVENTS.map((event) => (
                <TabsTrigger
                  key={event.name}
                  value={event.name}
                  className="flex items-center gap-2 data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
                >
                  <span>{event.icon}</span>
                  <span className="hidden sm:inline">{event.label}</span>
                  {getEventHookCount(event.name) > 0 && (
                    <Badge
                      variant="secondary"
                      className="ml-1 h-5 w-5 rounded-full p-0 flex items-center justify-center text-xs"
                    >
                      {getEventHookCount(event.name)}
                    </Badge>
                  )}
                </TabsTrigger>
              ))}
            </TabsList>

            {HOOK_EVENTS.map((event) => (
              <TabsContent key={event.name} value={event.name} className="mt-6">
                <div className="space-y-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <h3 className="text-lg font-medium flex items-center gap-2">
                        <span className="text-2xl">{event.icon}</span>
                        {event.label}
                      </h3>
                      <p className="text-sm text-muted-foreground mt-1">
                        {event.description}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      onClick={() => {
                        setSelectedEvent(event.name);
                        setShowWizard(true);
                      }}
                    >
                      <Plus className="h-4 w-4 mr-2" />
                      Add {event.label} Hook
                    </Button>
                  </div>

                  {loading ? (
                    <div className="text-center py-12 text-muted-foreground">
                      Loading hooks...
                    </div>
                  ) : (
                    <HookList
                      hooks={getHooksByEvent(event.name)}
                      onEdit={handleEdit}
                      onDelete={handleDelete}
                    />
                  )}
                </div>
              </TabsContent>
            ))}
          </Tabs>
        </CardContent>
      </Card>

      {/* Hook Editor Dialog */}
      <HookEditor
        hook={editingHook}
        open={showEditor}
        onOpenChange={setShowEditor}
        onSave={handleUpdate}
      />

      {/* Hook Wizard Dialog */}
      <HookWizard
        open={showWizard}
        onOpenChange={setShowWizard}
        onCreate={handleCreate}
      />
    </div>
  );
}
