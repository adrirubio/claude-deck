import { useState, useEffect, useCallback } from "react";
import {
  Search,
  Download,
  ExternalLink,
  TrendingUp,
  CheckCircle2,
  Loader2,
  Github,
  RefreshCw,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiClient, buildEndpoint } from "@/lib/api";
import { useProjectContext } from "@/contexts/ProjectContext";
import { toast } from "sonner";
import {
  type RegistrySkill,
  type RegistrySearchResponse,
} from "@/types/agents";
import { SkillRegistryInstallDialog } from "./SkillRegistryInstallDialog";

export function SkillRegistryBrowser({
  onInstallComplete,
}: {
  onInstallComplete?: () => void;
}) {
  const { activeProject } = useProjectContext();
  const [skills, setSkills] = useState<RegistrySkill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");

  // Install dialog state
  const [installSkill, setInstallSkill] = useState<RegistrySkill | null>(null);
  const [installDialogOpen, setInstallDialogOpen] = useState(false);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(searchQuery);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const fetchSkills = useCallback(
    async (forceRefresh = false) => {
      setLoading(true);
      setError(null);
      try {
        const params: Record<string, string | number | boolean | undefined> = {
          project_path: activeProject?.path,
          limit: 50,
        };
        if (debouncedQuery.length >= 2) {
          params.query = debouncedQuery;
        }
        if (forceRefresh) {
          params.force_refresh = true;
        }

        const response = await apiClient<RegistrySearchResponse>(
          buildEndpoint("agents/skills/registry", params)
        );
        setSkills(response.skills);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to fetch registry"
        );
        toast.error("Failed to load skills registry");
      } finally {
        setLoading(false);
      }
    },
    [activeProject?.path, debouncedQuery]
  );

  useEffect(() => {
    fetchSkills();
  }, [fetchSkills]);

  const handleInstallClick = (skill: RegistrySkill) => {
    setInstallSkill(skill);
    setInstallDialogOpen(true);
  };

  const handleInstallComplete = () => {
    fetchSkills();
    onInstallComplete?.();
  };

  const formatInstalls = (count: number): string => {
    if (count >= 1000) {
      return `${(count / 1000).toFixed(count >= 10000 ? 0 : 1)}K`;
    }
    return count.toString();
  };

  return (
    <div className="space-y-4">
      {/* Search + Refresh */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search skills (min 2 characters)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
        <Button
          variant="outline"
          size="icon"
          onClick={() => fetchSkills(true)}
          disabled={loading}
          title="Refresh from skills.sh"
        >
          <RefreshCw
            className={`h-4 w-4 ${loading ? "animate-spin" : ""}`}
          />
        </Button>
      </div>

      {/* Info */}
      {!debouncedQuery && (
        <p className="text-sm text-muted-foreground flex items-center gap-1">
          <TrendingUp className="h-4 w-4" />
          Showing top skills by install count from{" "}
          <a
            href="https://skills.sh"
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-foreground transition-colors"
          >
            skills.sh
          </a>
        </p>
      )}

      {/* Error */}
      {error && (
        <Card className="border-destructive">
          <CardContent className="py-4">
            <p className="text-destructive">{error}</p>
          </CardContent>
        </Card>
      )}

      {/* Loading */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : skills.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            {debouncedQuery
              ? `No skills found for "${debouncedQuery}"`
              : "No skills available"}
          </CardContent>
        </Card>
      ) : (
        /* Skills Grid */
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {skills.map((skill) => (
            <Card
              key={skill.registry_id}
              className="hover:bg-muted/50 transition-colors group"
            >
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <CardTitle className="text-base truncate">
                      {skill.name}
                    </CardTitle>
                    <p className="text-sm text-muted-foreground mt-0.5 truncate font-mono">
                      {skill.source}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 text-sm text-muted-foreground flex-shrink-0">
                    <Download className="h-3.5 w-3.5" />
                    <span>{formatInstalls(skill.installs)}</span>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-2 flex-wrap">
                  {skill.installed ? (
                    <Badge
                      variant="outline"
                      className="text-green-600 border-green-200 bg-green-50 flex items-center gap-1"
                    >
                      <CheckCircle2 className="h-3 w-3" />
                      Installed
                    </Badge>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleInstallClick(skill)}
                      className="h-7 text-xs"
                    >
                      <Download className="h-3 w-3 mr-1" />
                      Install
                    </Button>
                  )}

                  <div className="ml-auto flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7"
                      onClick={() =>
                        window.open(skill.url, "_blank", "noopener")
                      }
                      title="View on skills.sh"
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7"
                      onClick={() =>
                        window.open(skill.github_url, "_blank", "noopener")
                      }
                      title="View on GitHub"
                    >
                      <Github className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Install Dialog */}
      <SkillRegistryInstallDialog
        skill={installSkill}
        open={installDialogOpen}
        onOpenChange={setInstallDialogOpen}
        onComplete={handleInstallComplete}
        projectPath={activeProject?.path}
      />
    </div>
  );
}
