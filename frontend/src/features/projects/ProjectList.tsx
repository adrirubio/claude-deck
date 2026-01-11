/**
 * Project list component
 */
import { useState } from 'react';
import { useProjectContext } from '@/contexts/ProjectContext';
import type { ProjectResponse } from '@/types/projects';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

interface ProjectListProps {
  projects: ProjectResponse[];
  loading: boolean;
}

export function ProjectList({ projects, loading }: ProjectListProps) {
  const { setActiveProject, removeProject } = useProjectContext();
  const [actionLoading, setActionLoading] = useState<number | null>(null);

  const handleSetActive = async (projectId: number) => {
    setActionLoading(projectId);
    try {
      await setActiveProject(projectId);
    } catch (err) {
      console.error('Failed to set active project:', err);
    } finally {
      setActionLoading(null);
    }
  };

  const handleRemove = async (projectId: number) => {
    if (!confirm('Are you sure you want to remove this project from tracking?')) {
      return;
    }

    setActionLoading(projectId);
    try {
      await removeProject(projectId);
    } catch (err) {
      console.error('Failed to remove project:', err);
    } finally {
      setActionLoading(null);
    }
  };

  if (loading && projects.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        Loading projects...
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        <p>No projects tracked yet.</p>
        <p className="text-sm mt-2">Use the discovery wizard to find Claude Code projects.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {projects.map((project) => (
        <Card key={project.id} className={project.is_active ? 'border-primary' : ''}>
          <CardHeader>
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <CardTitle>{project.name}</CardTitle>
                  {project.is_active && (
                    <Badge variant="default">Active</Badge>
                  )}
                </div>
                <CardDescription className="mt-1">{project.path}</CardDescription>
              </div>
              <div className="flex gap-2">
                {!project.is_active && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleSetActive(project.id)}
                    disabled={actionLoading === project.id}
                  >
                    {actionLoading === project.id ? 'Setting...' : 'Set Active'}
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleRemove(project.id)}
                  disabled={actionLoading === project.id}
                >
                  {actionLoading === project.id ? 'Removing...' : 'Remove'}
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-sm text-muted-foreground space-y-1">
              <p>Created: {new Date(project.created_at).toLocaleString()}</p>
              <p>Last accessed: {new Date(project.last_accessed).toLocaleString()}</p>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
