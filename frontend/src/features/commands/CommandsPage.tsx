import { useState, useEffect, useCallback } from 'react';
import { Plus, Terminal, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { RefreshButton } from '@/components/shared/RefreshButton';
import { MODAL_SIZES } from '@/lib/constants';
import { CommandList } from './CommandList';
import { CommandEditor } from './CommandEditor';
import { CommandWizard } from './CommandWizard';
import { CommandDetailDialog } from './CommandDetailDialog';
import type { SlashCommand } from '@/types/commands';
import { apiClient, buildEndpoint } from '@/lib/api';
import { useProjectContext } from '@/contexts/ProjectContext';
import { toast } from 'sonner';

export function CommandsPage() {
  const { activeProject } = useProjectContext();
  const [commands, setCommands] = useState<SlashCommand[]>([]);
  const [selectedCommand, setSelectedCommand] = useState<SlashCommand | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showWizard, setShowWizard] = useState(false);
  const [showEditor, setShowEditor] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [detailCommand, setDetailCommand] = useState<SlashCommand | null>(null);
  const [showDetail, setShowDetail] = useState(false);

  const fetchCommands = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const endpoint = buildEndpoint("commands", { project_path: activeProject?.path });
      const data = await apiClient<{ commands: SlashCommand[] }>(endpoint);
      setCommands(data.commands || []);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to fetch commands';
      setError(message);
      toast.error('Failed to fetch commands');
    } finally {
      setLoading(false);
    }
  }, [activeProject?.path]);

  useEffect(() => {
    fetchCommands();
  }, [fetchCommands]);

  const handleViewDetail = (command: SlashCommand) => {
    setDetailCommand(command);
    setShowDetail(true);
  };

  const handleEditFromDetail = async (command: SlashCommand) => {
    setShowDetail(false);
    // Fetch full content for editor
    try {
      const endpoint = buildEndpoint(
        `commands/${command.scope}/${command.path}`,
        { project_path: activeProject?.path }
      );
      const fullCommand = await apiClient<SlashCommand>(endpoint);
      setSelectedCommand(fullCommand);
      setShowEditor(true);
    } catch {
      toast.error('Failed to load command');
    }
  };

  const handleEdit = async (command: SlashCommand) => {
    try {
      const endpoint = buildEndpoint(
        `commands/${command.scope}/${command.path}`,
        { project_path: activeProject?.path }
      );
      const fullCommand = await apiClient<SlashCommand>(endpoint);
      setSelectedCommand(fullCommand);
      setShowEditor(true);
    } catch {
      toast.error('Failed to load command');
    }
  };

  const handleSaveCommand = async (command: SlashCommand) => {
    try {
      const endpoint = buildEndpoint(
        `commands/${command.scope}/${command.path}`,
        { project_path: activeProject?.path }
      );
      await apiClient(endpoint, {
        method: "PUT",
        body: JSON.stringify({
          description: command.description,
          allowed_tools: command.allowed_tools,
          content: command.content,
        }),
      });
      toast.success('Command saved successfully');
      setShowEditor(false);
      fetchCommands();
    } catch {
      toast.error('Failed to save command');
    }
  };

  const handleDeleteCommand = async (command: SlashCommand) => {
    try {
      const endpoint = buildEndpoint(
        `commands/${command.scope}/${command.path}`,
        { project_path: activeProject?.path }
      );
      await apiClient(endpoint, { method: "DELETE" });
      toast.success('Command deleted successfully');
      setShowEditor(false);
      setShowDetail(false);
      fetchCommands();
    } catch {
      toast.error('Failed to delete command');
    }
  };

  const handleCreateCommand = () => {
    setShowWizard(true);
  };

  const handleWizardComplete = () => {
    setShowWizard(false);
    fetchCommands();
  };

  const userCount = commands.filter((c) => c.scope === "user").length;
  const projectCount = commands.filter((c) => c.scope === "project").length;
  const pluginCount = commands.filter((c) => c.scope.startsWith("plugin:")).length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Terminal className="h-8 w-8" />
            Slash Commands
          </h1>
          <p className="text-muted-foreground">
            Manage custom Claude Code commands
          </p>
        </div>
        <div className="flex gap-2">
          <RefreshButton onClick={fetchCommands} loading={loading} />
          <Button onClick={handleCreateCommand}>
            <Plus className="h-4 w-4 mr-2" />
            Add Command
          </Button>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-destructive">Error</CardTitle>
          </CardHeader>
          <CardContent>
            <p>{error}</p>
          </CardContent>
        </Card>
      )}

      {/* Search Bar */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search commands..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="pl-9"
        />
      </div>

      {/* Stats */}
      {commands.length > 0 && (
        <div className="text-sm text-muted-foreground">
          {commands.length} command{commands.length !== 1 ? "s" : ""}
          {userCount > 0 && ` \u00B7 ${userCount} user`}
          {projectCount > 0 && ` \u00B7 ${projectCount} project`}
          {pluginCount > 0 && ` \u00B7 ${pluginCount} plugin`}
        </div>
      )}

      {/* Commands List */}
      <CommandList
        commands={commands}
        loading={loading}
        searchQuery={searchQuery}
        onViewDetail={handleViewDetail}
        onEdit={handleEdit}
        onDelete={handleDeleteCommand}
      />

      {/* Command Detail Dialog */}
      <CommandDetailDialog
        command={detailCommand}
        open={showDetail}
        onOpenChange={setShowDetail}
        onEdit={handleEditFromDetail}
        onDelete={handleDeleteCommand}
      />

      {/* Command Editor Dialog */}
      <Dialog open={showEditor} onOpenChange={setShowEditor}>
        <DialogContent className={`${MODAL_SIZES.LG} overflow-y-auto`}>
          <DialogHeader>
            <DialogTitle>Edit Command</DialogTitle>
            <DialogDescription>Modify command settings and content</DialogDescription>
          </DialogHeader>
          {selectedCommand && (
            <CommandEditor
              command={selectedCommand}
              onSave={handleSaveCommand}
              onDelete={handleDeleteCommand}
              onCancel={() => setShowEditor(false)}
            />
          )}
        </DialogContent>
      </Dialog>

      {/* Create Command Wizard Dialog */}
      <Dialog open={showWizard} onOpenChange={setShowWizard}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Create New Command</DialogTitle>
            <DialogDescription>Create a new slash command step by step</DialogDescription>
          </DialogHeader>
          <CommandWizard
            onComplete={handleWizardComplete}
            onCancel={() => setShowWizard(false)}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}
