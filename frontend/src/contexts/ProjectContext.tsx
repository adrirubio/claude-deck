/**
 * Project Context for shared project state across the application
 */
import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from 'react';
import { apiClient } from '@/lib/api';
import type {
  ProjectResponse,
  ProjectListResponse,
  ProjectDiscoveryResponse,
  ProjectCreate,
} from '@/types/projects';

interface ProjectContextType {
  projects: ProjectResponse[];
  activeProject: ProjectResponse | null;
  loading: boolean;
  error: string | null;
  fetchProjects: () => Promise<void>;
  addProject: (projectData: ProjectCreate) => Promise<ProjectResponse>;
  removeProject: (projectId: number) => Promise<void>;
  discoverProjects: (basePath: string) => Promise<ProjectCreate[]>;
  setActiveProject: (projectId: number) => Promise<void>;
  clearActiveProject: () => Promise<void>;
}

const ProjectContext = createContext<ProjectContextType | undefined>(undefined);

export function ProjectProvider({ children }: { children: ReactNode }) {
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
      await fetchProjects();
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
      await fetchProjects();
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
      await fetchProjects();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to set active project');
      throw err;
    } finally {
      setLoading(false);
    }
  }, [fetchProjects]);

  const clearActiveProject = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await apiClient('projects/active', {
        method: 'DELETE',
      });
      await fetchProjects();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to clear active project');
      throw err;
    } finally {
      setLoading(false);
    }
  }, [fetchProjects]);

  // Get the active project from the projects list
  const activeProject = projects.find((p) => p.is_active) || null;

  // Fetch projects on mount
  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  return (
    <ProjectContext.Provider
      value={{
        projects,
        activeProject,
        loading,
        error,
        fetchProjects,
        addProject,
        removeProject,
        discoverProjects,
        setActiveProject,
        clearActiveProject,
      }}
    >
      {children}
    </ProjectContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useProjectContext() {
  const context = useContext(ProjectContext);
  if (!context) {
    throw new Error('useProjectContext must be used within a ProjectProvider');
  }
  return context;
}
