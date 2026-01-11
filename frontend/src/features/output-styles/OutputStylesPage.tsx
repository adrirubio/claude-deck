import { useState, useEffect, useCallback } from "react";
import { Plus, Paintbrush } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { OutputStyleList } from "./OutputStyleList";
import { OutputStyleEditor } from "./OutputStyleEditor";
import { OutputStyleWizard } from "./OutputStyleWizard";
import { RefreshButton } from "@/components/shared/RefreshButton";
import { apiClient, buildEndpoint } from "@/lib/api";
import { useProjectContext } from "@/contexts/ProjectContext";
import { toast } from "sonner";
import {
  type OutputStyle,
  type OutputStyleCreate,
  type OutputStyleUpdate,
  type OutputStyleScope,
  type OutputStyleListResponse,
} from "@/types/output-styles";

export function OutputStylesPage() {
  const { activeProject } = useProjectContext();
  const [styles, setStyles] = useState<OutputStyle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingStyle, setEditingStyle] = useState<OutputStyle | null>(null);
  const [showWizard, setShowWizard] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const endpoint = buildEndpoint("output-styles", { project_path: activeProject?.path });
      const response = await apiClient<OutputStyleListResponse>(endpoint);
      setStyles(response.output_styles);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch data");
      toast.error("Failed to load output styles");
    } finally {
      setLoading(false);
    }
  }, [activeProject?.path]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleCreate = async (style: OutputStyleCreate) => {
    try {
      const endpoint = buildEndpoint("output-styles", { project_path: activeProject?.path });
      await apiClient<OutputStyle>(endpoint, {
        method: "POST",
        body: JSON.stringify(style),
      });
      toast.success("Output style created");
      await fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create output style");
      throw err;
    }
  };

  const handleEdit = (style: OutputStyle) => {
    setEditingStyle(style);
  };

  const handleUpdate = async (update: OutputStyleUpdate) => {
    if (!editingStyle) return;

    try {
      const endpoint = buildEndpoint(
        `output-styles/${editingStyle.scope}/${editingStyle.name}`,
        { project_path: activeProject?.path }
      );
      await apiClient<OutputStyle>(endpoint, { method: "PUT", body: JSON.stringify(update) });
      toast.success("Output style updated");
      await fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update output style");
      throw err;
    }
  };

  const handleDelete = async (name: string, scope: OutputStyleScope) => {
    try {
      const endpoint = buildEndpoint(`output-styles/${scope}/${name}`, { project_path: activeProject?.path });
      await apiClient(endpoint, { method: "DELETE" });
      toast.success("Output style deleted");
      await fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete output style");
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Paintbrush className="h-8 w-8" />
            Output Styles
          </h1>
          <p className="text-muted-foreground mt-1">
            Configure custom output formatting and style instructions
          </p>
        </div>
        <div className="flex gap-2">
          <RefreshButton onClick={fetchData} loading={loading} />
          <Button onClick={() => setShowWizard(true)}>
            <Plus className="h-4 w-4 mr-2" />
            New Style
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
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-3">
            <CardDescription className="flex items-center gap-2">
              <Paintbrush className="h-4 w-4 text-primary" />
              Total Output Styles
            </CardDescription>
            <CardTitle className="text-3xl">{styles.length}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription className="flex items-center gap-2">
              <Paintbrush className="h-4 w-4 text-amber-500" />
              Keep Coding Instructions
            </CardDescription>
            <CardTitle className="text-3xl">
              {styles.filter((s) => s.keep_coding_instructions).length}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Main Content */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Paintbrush className="h-5 w-5 text-primary" />
            Output Styles
          </CardTitle>
          <CardDescription>
            Custom output formatting instructions for Claude Code responses
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="text-center py-8 text-muted-foreground">
              Loading...
            </div>
          ) : (
            <OutputStyleList
              styles={styles}
              onEdit={handleEdit}
              onDelete={handleDelete}
            />
          )}
        </CardContent>
      </Card>

      {/* Output Style Editor Dialog */}
      <OutputStyleEditor
        open={!!editingStyle}
        onOpenChange={(open) => {
          if (!open) setEditingStyle(null);
        }}
        style={editingStyle}
        onSave={handleUpdate}
      />

      {/* Output Style Wizard Dialog */}
      <OutputStyleWizard
        open={showWizard}
        onOpenChange={setShowWizard}
        onCreate={handleCreate}
      />
    </div>
  );
}
