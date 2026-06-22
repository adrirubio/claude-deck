import { useState, useEffect, useMemo } from 'react';
import { useProjectContext } from '@/contexts/ProjectContext';
import type { ProjectBase } from '@/types/projects';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Folder, FolderOpen, ChevronRight, ArrowLeft, Search } from 'lucide-react';
import { apiClient } from '@/lib/api';
import { MODAL_SIZES } from '@/lib/constants';

interface BrowseResult {
  path: string;
  parent: string | null;
  directories: string[];
}

interface ProjectDiscoveryProps {
  onProjectsDiscovered: () => void;
}

export function ProjectDiscovery({ onProjectsDiscovered }: ProjectDiscoveryProps) {
  const { discoverProjects, addProject } = useProjectContext();
  const [searchPath, setSearchPath] = useState('');
  const [discoveredProjects, setDiscoveredProjects] = useState<ProjectBase[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addingProjects, setAddingProjects] = useState<Set<string>>(new Set());

  // Pre-populate with the real home path on mount
  useEffect(() => {
    apiClient<BrowseResult>('projects/browse?path=~')
      .then((r) => setSearchPath(r.path))
      .catch(() => { /* leave empty if backend not ready */ });
  }, []);

  // Directory browser state
  const [browserOpen, setBrowserOpen] = useState(false);
  const [browseResult, setBrowseResult] = useState<BrowseResult | null>(null);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseError, setBrowseError] = useState<string | null>(null);
  const [directoryFilter, setDirectoryFilter] = useState('');

  const filteredDirectories = useMemo(() => {
    if (!browseResult) return [];
    const query = directoryFilter.trim().toLowerCase();
    if (!query) return browseResult.directories;
    return browseResult.directories.filter((dir) => dir.toLowerCase().includes(query));
  }, [browseResult, directoryFilter]);

  const handleDiscover = async () => {
    if (!searchPath.trim()) {
      setError('Please enter a path to search');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const discovered = await discoverProjects(searchPath);
      setDiscoveredProjects(discovered);
      if (discovered.length === 0) {
        setError('No project folders found in this directory');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to discover projects');
    } finally {
      setLoading(false);
    }
  };

  const handleAddProject = async (project: ProjectBase) => {
    setAddingProjects(prev => new Set(prev).add(project.path));
    try {
      await addProject(project);
      setDiscoveredProjects(prev => prev.filter(p => p.path !== project.path));
      if (discoveredProjects.length === 1) {
        onProjectsDiscovered();
      }
    } catch (err) {
      console.error('Failed to add project:', err);
    } finally {
      setAddingProjects(prev => {
        const next = new Set(prev);
        next.delete(project.path);
        return next;
      });
    }
  };

  const browseTo = async (path: string) => {
    setBrowseLoading(true);
    setBrowseError(null);
    try {
      const result = await apiClient<BrowseResult>(
        `projects/browse?path=${encodeURIComponent(path)}`
      );
      setBrowseResult(result);
      setDirectoryFilter('');
    } catch (err) {
      setBrowseError(err instanceof Error ? err.message : 'Failed to read directory');
    } finally {
      setBrowseLoading(false);
    }
  };

  const openBrowser = () => {
    setBrowserOpen(true);
    browseTo(searchPath.trim() || '~');
  };

  const handleSelectDirectory = () => {
    if (browseResult) {
      setSearchPath(browseResult.path);
    }
    setBrowserOpen(false);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Discover Projects</CardTitle>
        <CardDescription>
          Enter a directory path to find project folders
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <Input
            type="text"
            value={searchPath}
            onChange={(e) => setSearchPath(e.target.value)}
            placeholder="~/projects"
            onKeyDown={(e) => { if (e.key === 'Enter') handleDiscover(); }}
          />
          <Button variant="outline" onClick={openBrowser} title="Browse directories">
            <Folder className="h-4 w-4" />
          </Button>
          <Button onClick={handleDiscover} disabled={loading}>
            {loading ? 'Searching...' : 'Search'}
          </Button>
        </div>

        {error && (
          <div className="text-sm text-destructive">{error}</div>
        )}

        {discoveredProjects.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">
                Found {discoveredProjects.length} project{discoveredProjects.length !== 1 ? 's' : ''}
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  for (const project of discoveredProjects) {
                    await handleAddProject(project);
                  }
                }}
              >
                Add All
              </Button>
            </div>
            <div className="space-y-2">
              {discoveredProjects.map((project) => (
                <Card key={project.path}>
                  <CardContent className="pt-4">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <p className="font-medium">{project.name}</p>
                          {project.source === "configured" ? (
                            <Badge variant="outline" className="border-green-500 text-green-600">Configured</Badge>
                          ) : project.source === "session_history" ? (
                            <Badge variant="outline" className="border-blue-500 text-blue-600">Session History</Badge>
                          ) : project.source === "directory" ? (
                            <Badge variant="outline">Folder</Badge>
                          ) : (
                            <Badge variant="outline">Discovered</Badge>
                          )}
                        </div>
                        <p className="text-sm text-muted-foreground mt-1">{project.path}</p>
                      </div>
                      <Button
                        size="sm"
                        onClick={() => handleAddProject(project)}
                        disabled={addingProjects.has(project.path)}
                      >
                        {addingProjects.has(project.path) ? 'Adding...' : 'Add'}
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        )}
      </CardContent>

      {/* Directory browser dialog */}
      <Dialog open={browserOpen} onOpenChange={setBrowserOpen}>
        <DialogContent className={MODAL_SIZES.SM}>
          <DialogHeader>
            <DialogTitle>Browse Directories</DialogTitle>
          </DialogHeader>

          <div className="space-y-3">
            {/* Current path breadcrumb */}
            {browseResult && (
              <div className="flex items-center gap-1 text-sm text-muted-foreground bg-muted px-3 py-2 rounded-md min-w-0">
                <FolderOpen className="h-4 w-4 shrink-0" />
                <span className="truncate">{browseResult.path}</span>
              </div>
            )}

            {/* Up / parent button */}
            {browseResult?.parent && (
              <Button
                variant="ghost"
                size="sm"
                className="w-full justify-start gap-2 text-muted-foreground"
                onClick={() => browseTo(browseResult.parent!)}
              >
                <ArrowLeft className="h-4 w-4" />
                <span className="truncate">.. (up to {browseResult.parent})</span>
              </Button>
            )}

            {browseError && (
              <p className="text-sm text-destructive">{browseError}</p>
            )}

            {browseResult && (
              <div className="space-y-2">
                <Label htmlFor="directory-filter">Filter directories</Label>
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="directory-filter"
                    value={directoryFilter}
                    onChange={(event) => setDirectoryFilter(event.target.value)}
                    placeholder="Type a directory name"
                    className="pl-9"
                  />
                </div>
              </div>
            )}

            {browseLoading && (
              <p className="text-sm text-muted-foreground text-center py-4">Loading…</p>
            )}

            {/* Directory list */}
            {!browseLoading && browseResult && (
              browseResult.directories.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">
                  No subdirectories
                </p>
              ) : filteredDirectories.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">
                  No directories match this filter
                </p>
              ) : (
                <ScrollArea className="h-64 rounded-md border">
                  <div className="p-1">
                    {filteredDirectories.map((dir) => (
                      <button
                        key={dir}
                        type="button"
                        className="w-full flex items-center gap-2 px-3 py-2 rounded text-sm hover:bg-accent hover:text-accent-foreground transition-colors text-left cursor-pointer"
                        onClick={() => browseTo(`${browseResult.path}/${dir}`)}
                      >
                        <Folder className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <span className="truncate">{dir}</span>
                        <ChevronRight className="h-4 w-4 shrink-0 ml-auto text-muted-foreground" />
                      </button>
                    ))}
                  </div>
                </ScrollArea>
              )
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setBrowserOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleSelectDirectory} disabled={!browseResult}>
              Use this directory
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
