/**
 * Project switcher dropdown component for sidebar
 */
import { useProjectContext } from '@/contexts/ProjectContext';

export function ProjectSwitcher() {
  const { projects, loading, activeProject, setActiveProject, clearActiveProject } = useProjectContext();

  const handleChange = async (projectId: string) => {
    try {
      if (projectId === '') {
        await clearActiveProject();
      } else {
        await setActiveProject(parseInt(projectId));
      }
    } catch (err) {
      console.error('Failed to change project:', err);
    }
  };

  if (loading && projects.length === 0) {
    return (
      <div className="px-4 py-2 text-sm text-muted-foreground">
        Loading projects...
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="px-4 py-2 text-sm text-muted-foreground">
        No projects
      </div>
    );
  }

  return (
    <div className="px-4 py-2">
      <label className="text-xs font-medium text-muted-foreground mb-1 block">
        Active Project
      </label>
      <select
        value={activeProject?.id || ''}
        onChange={(e) => handleChange(e.target.value)}
        className="w-full px-2 py-1 text-sm border rounded-md bg-background"
      >
        <option value="">User (All Projects)</option>
        {projects.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name}
          </option>
        ))}
      </select>
    </div>
  );
}
