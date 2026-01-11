/**
 * Hook for managing project state and operations
 */
import { useState, useCallback } from 'react';
import { apiClient } from '@/lib/api';
import type {
  ProjectResponse,
  ProjectListResponse,
  ProjectDiscoveryResponse,
  ProjectCreate,
} from '@/types/projects';

export function useProjects() {
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchProjects = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient<ProjectListResponse>('projects');
      setProjects(response.projects);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch projects');
    } finally {
      setLoading(false);
    }
  }, []);

  const addProject = useCallback(async (projectData: ProjectCreate) => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient<ProjectResponse>('projects', {
        method: 'POST',
        body: JSON.stringify(projectData),
      });
      await fetchProjects(); // Refresh the list
      return response;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add project');
      throw err;
    } finally {
      setLoading(false);
    }
  }, [fetchProjects]);

  const removeProject = useCallback(async (projectId: number) => {
    setLoading(true);
    setError(null);
    try {
      await apiClient(`projects/${projectId}`, {
        method: 'DELETE',
      });
      await fetchProjects(); // Refresh the list
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove project');
      throw err;
    } finally {
      setLoading(false);
    }
  }, [fetchProjects]);

  const discoverProjects = useCallback(async (basePath: string) => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient<ProjectDiscoveryResponse>('projects/discover', {
        method: 'POST',
        body: JSON.stringify({ base_path: basePath }),
      });
      return response.discovered;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to discover projects');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const setActiveProject = useCallback(async (projectId: number) => {
    setLoading(true);
    setError(null);
    try {
      await apiClient('projects/active', {
        method: 'PUT',
        body: JSON.stringify({ project_id: projectId }),
      });
      await fetchProjects(); // Refresh to update active status
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to set active project');
      throw err;
    } finally {
      setLoading(false);
    }
  }, [fetchProjects]);

  const getActiveProject = useCallback(() => {
    return projects.find(p => p.is_active) || null;
  }, [projects]);

  return {
    projects,
    loading,
    error,
    fetchProjects,
    addProject,
    removeProject,
    discoverProjects,
    setActiveProject,
    getActiveProject,
  };
}
