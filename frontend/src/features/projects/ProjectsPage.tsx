/**
 * Projects management page
 */
import { useState } from 'react';
import { FolderOpen } from 'lucide-react';
import { useProjectContext } from '@/contexts/ProjectContext';
import { ProjectList } from './ProjectList';
import { ProjectDiscovery } from './ProjectDiscovery';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { RefreshButton } from '@/components/shared/RefreshButton';

export function ProjectsPage() {
  const { projects, loading, error, fetchProjects } = useProjectContext();
  const [showDiscovery, setShowDiscovery] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <FolderOpen className="h-8 w-8" />
            Projects
          </h1>
          <p className="text-muted-foreground mt-2">
            Manage Claude Code project directories
          </p>
        </div>
        <div className="flex gap-2">
          <RefreshButton onClick={fetchProjects} loading={loading} />
          <Button onClick={() => setShowDiscovery(!showDiscovery)}>
            {showDiscovery ? 'Hide Discovery' : 'Discover Projects'}
          </Button>
        </div>
      </div>

      {showDiscovery && (
        <ProjectDiscovery onProjectsDiscovered={() => {
          setShowDiscovery(false);
        }} />
      )}

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

      <Card>
        <CardHeader>
          <CardTitle>Tracked Projects</CardTitle>
          <CardDescription>
            {projects.length} project{projects.length !== 1 ? 's' : ''} tracked
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ProjectList projects={projects} loading={loading} />
        </CardContent>
      </Card>
    </div>
  );
}
