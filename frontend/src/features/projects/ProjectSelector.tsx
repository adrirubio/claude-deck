/**
 * Project chooser for the header of a project-scoped Harness page.
 * The choice lives in this page's URL (?project=<path>). It is not shared with other pages or browsers.
 */
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useProjectContext } from '@/contexts/ProjectContext';

const ADD_FOLDER = '__add_folder__';

export function ProjectSelector() {
  const { activeProject, knownFolders, setProjectPath, addProject } = useProjectContext();
  const [adding, setAdding] = useState(false);
  const [path, setPath] = useState('');
  const [error, setError] = useState<string | null>(null);

  const team = knownFolders.filter((folder) => folder.source === 'team');
  const tracked = knownFolders.filter((folder) => folder.source === 'tracked');

  const onChange = (value: string) => {
    if (value === ADD_FOLDER) {
      setAdding(true);
      return;
    }
    setAdding(false);
    setError(null);
    setProjectPath(value || null);
  };

  const onAdd = async (event: FormEvent) => {
    event.preventDefault();
    const folder = path.trim();
    if (!folder) return;
    setError(null);
    try {
      await addProject({ name: folder.split('/').filter(Boolean).pop() ?? folder, path: folder });
      setProjectPath(folder);
      setAdding(false);
      setPath('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Deck could not add this folder.');
    }
  };

  return (
    <div className="flex flex-wrap items-end gap-3 text-sm">
      <div className="grid gap-1">
        <label htmlFor="project-selector" className="font-medium">Project</label>
        <select
          id="project-selector"
          className="min-w-64 rounded border bg-background p-2"
          value={activeProject?.path ?? ''}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">No project (user settings only)</option>
          {team.length > 0 && (
            <optgroup label="Team members' folders">
              {team.map((folder) => (
                <option key={folder.path} value={folder.path}>{folder.name} · {folder.detail}</option>
              ))}
            </optgroup>
          )}
          {tracked.length > 0 && (
            <optgroup label="Other folders Deck knows about">
              {tracked.map((folder) => (
                <option key={folder.path} value={folder.path}>{folder.name} · {folder.path}</option>
              ))}
            </optgroup>
          )}
          <option value={ADD_FOLDER}>Add a folder…</option>
        </select>
      </div>
      {adding && (
        <form className="flex flex-wrap items-end gap-2" onSubmit={onAdd}>
          <label className="grid gap-1">
            <span className="font-medium">Folder path</span>
            <Input className="w-72" value={path} onChange={(event) => setPath(event.target.value)} placeholder="/path/to/project" />
          </label>
          <Button type="submit" size="sm" disabled={!path.trim()}>Add folder</Button>
          <Button type="button" size="sm" variant="outline" onClick={() => { setAdding(false); setError(null); }}>Cancel</Button>
        </form>
      )}
      <p className="text-muted-foreground">
        Scopes project-level native settings on this page only.{' '}
        <Link className="text-primary underline" to="/harnesses/folders">Folders Deck knows about</Link>
      </p>
      {error && <p role="alert" className="w-full text-destructive">{error}</p>}
    </div>
  );
}
