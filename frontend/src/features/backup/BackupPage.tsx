import { useState, useEffect, useCallback } from "react";
import { Plus, Archive } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { BackupList } from "./BackupList";
import { BackupWizard } from "./BackupWizard";
import { RestoreWizard } from "./RestoreWizard";
import { RefreshButton } from "@/components/shared/RefreshButton";
import { apiClient, buildEndpoint } from "@/lib/api";
import { useProjectContext } from "@/contexts/ProjectContext";
import { toast } from "sonner";
import { type Backup, type BackupCreate, type BackupListResponse, formatBytes } from "@/types/backup";

export function BackupPage() {
  const { activeProject } = useProjectContext();
  const [backups, setBackups] = useState<Backup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreateWizard, setShowCreateWizard] = useState(false);
  const [showRestoreWizard, setShowRestoreWizard] = useState(false);
  const [selectedBackup, setSelectedBackup] = useState<Backup | null>(null);

  const fetchBackups = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const endpoint = buildEndpoint("backup/list", { project_path: activeProject?.path });
      const response = await apiClient<BackupListResponse>(endpoint);
      setBackups(response.backups);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch backups");
      toast.error("Failed to load backups");
    } finally {
      setLoading(false);
    }
  }, [activeProject?.path]);

  useEffect(() => {
    fetchBackups();
  }, [fetchBackups]);

  const handleCreate = async (backup: BackupCreate) => {
    try {
      const endpoint = buildEndpoint("backup/create");
      await apiClient<Backup>(endpoint, {
        method: "POST",
        body: JSON.stringify(backup),
      });
      toast.success("Backup created successfully");
      await fetchBackups();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create backup");
      throw err;
    }
  };

  const handleRestore = (backup: Backup) => {
    setSelectedBackup(backup);
    setShowRestoreWizard(true);
  };

  const handleRestoreConfirm = async (backup: Backup) => {
    try {
      const endpoint = buildEndpoint(`backup/${backup.id}/restore`, { project_path: activeProject?.path });
      await apiClient(endpoint, {
        method: "POST",
        body: JSON.stringify({}),
      });
      toast.success("Backup restored successfully");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to restore backup");
      throw err;
    }
  };

  const handleDownload = async (backup: Backup) => {
    try {
      // Create a download link
      const link = document.createElement("a");
      link.href = `/api/v1/backup/${backup.id}/download`;  // Keep full path for direct link
      link.download = `${backup.name}.zip`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      toast.success("Download started");
    } catch (err) {
      toast.error("Failed to download backup");
    }
  };

  const handleDelete = async (backup: Backup) => {
    try {
      const endpoint = buildEndpoint(`backup/${backup.id}`, { project_path: activeProject?.path });
      await apiClient(endpoint, { method: "DELETE" });
      toast.success("Backup deleted");
      await fetchBackups();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete backup");
    }
  };

  const totalSize = backups.reduce((acc, b) => acc + b.size_bytes, 0);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Archive className="h-8 w-8" />
            Backup & Restore
          </h1>
          <p className="text-muted-foreground mt-1">
            Create and manage configuration backups
          </p>
        </div>
        <div className="flex gap-2">
          <RefreshButton onClick={fetchBackups} loading={loading} />
          <Button onClick={() => setShowCreateWizard(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Create Backup
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
              <Archive className="h-4 w-4 text-primary" />
              Total Backups
            </CardDescription>
            <CardTitle className="text-3xl">{backups.length}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Total Size</CardDescription>
            <CardTitle className="text-3xl">{formatBytes(totalSize)}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Backup List */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Archive className="h-5 w-5 text-primary" />
            Available Backups
          </CardTitle>
          <CardDescription>
            Your saved configuration backups
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="text-center py-8 text-muted-foreground">
              Loading...
            </div>
          ) : (
            <BackupList
              backups={backups}
              onRestore={handleRestore}
              onDownload={handleDownload}
              onDelete={handleDelete}
            />
          )}
        </CardContent>
      </Card>

      {/* Create Wizard */}
      <BackupWizard
        open={showCreateWizard}
        onOpenChange={setShowCreateWizard}
        onCreate={handleCreate}
        currentProjectPath={activeProject?.path}
      />

      {/* Restore Wizard */}
      <RestoreWizard
        open={showRestoreWizard}
        onOpenChange={(open) => {
          setShowRestoreWizard(open);
          if (!open) setSelectedBackup(null);
        }}
        backup={selectedBackup}
        onRestore={handleRestoreConfirm}
      />
    </div>
  );
}
