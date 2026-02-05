import { useState, useEffect, useCallback } from "react";
import {
  Sparkles,
  MapPin,
  CheckCircle2,
  AlertTriangle,
  Store,
  FolderOpen,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { RefreshButton } from "@/components/shared/RefreshButton";
import { SkillDetailDialog } from "./SkillDetailDialog";
import { SkillRegistryBrowser } from "./SkillRegistryBrowser";
import { apiClient, buildEndpoint } from "@/lib/api";
import { useProjectContext } from "@/contexts/ProjectContext";
import { toast } from "sonner";
import {
  type Skill,
  type SkillListResponse,
  type SkillDependencyStatus,
} from "@/types/agents";

type SkillsTab = "installed" | "discover";

export function SkillsPage() {
  const { activeProject } = useProjectContext();
  const [activeTab, setActiveTab] = useState<SkillsTab>("installed");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [depStatuses, setDepStatuses] = useState<
    Record<string, SkillDependencyStatus>
  >({});

  const fetchSkills = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { project_path: activeProject?.path };
      const response = await apiClient<SkillListResponse>(
        buildEndpoint("agents/skills", params)
      );
      setSkills(response.skills);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch skills");
      toast.error("Failed to load skills");
    } finally {
      setLoading(false);
    }
  }, [activeProject?.path]);

  useEffect(() => {
    fetchSkills();
  }, [fetchSkills]);

  // Fetch dependency status for all skills (in parallel, non-blocking)
  useEffect(() => {
    if (skills.length === 0) return;

    const fetchDeps = async () => {
      const statuses: Record<string, SkillDependencyStatus> = {};
      await Promise.allSettled(
        skills.map(async (skill) => {
          try {
            const params = { project_path: activeProject?.path };
            const status = await apiClient<SkillDependencyStatus>(
              buildEndpoint(
                `agents/skills/${encodeURIComponent(skill.location)}/${encodeURIComponent(skill.name)}/dependencies`,
                params
              )
            );
            statuses[`${skill.location}:${skill.name}`] = status;
          } catch {
            // Silently ignore — dep check is best-effort
          }
        })
      );
      setDepStatuses(statuses);
    };

    fetchDeps();
  }, [skills, activeProject?.path]);

  // Group skills by location
  const userSkills = skills.filter((s) => s.location === "user");
  const projectSkills = skills.filter((s) => s.location === "project");
  const pluginSkills = skills.filter((s) => s.location.startsWith("plugin:"));

  // Group plugin skills by plugin name
  const pluginGroups: Record<string, Skill[]> = {};
  pluginSkills.forEach((skill) => {
    const pluginName = skill.location.replace("plugin:", "");
    if (!pluginGroups[pluginName]) {
      pluginGroups[pluginName] = [];
    }
    pluginGroups[pluginName].push(skill);
  });

  const getLocationBadge = (location: string) => {
    if (location === "user") {
      return (
        <Badge variant="outline" className="flex items-center gap-1">
          <MapPin className="h-3 w-3" />
          User
        </Badge>
      );
    }
    if (location === "project") {
      return (
        <Badge variant="outline" className="flex items-center gap-1">
          <MapPin className="h-3 w-3" />
          Project
        </Badge>
      );
    }
    return (
      <Badge variant="secondary" className="flex items-center gap-1">
        <MapPin className="h-3 w-3" />
        Plugin
      </Badge>
    );
  };

  const handleSkillClick = (skill: Skill) => {
    setSelectedSkill(skill);
    setDialogOpen(true);
  };

  const renderSkillCard = (skill: Skill) => {
    const depKey = `${skill.location}:${skill.name}`;
    const depStatus = depStatuses[depKey];
    const hasDeps = depStatus && depStatus.dependencies.length > 0;
    const hasMissing = hasDeps && !depStatus.all_satisfied;
    const missingCount = hasDeps
      ? depStatus.dependencies.filter((d) => !d.installed).length
      : 0;

    return (
      <Card
        key={`${skill.location}-${skill.name}`}
        className="hover:bg-muted/50 transition-colors cursor-pointer"
        onClick={() => handleSkillClick(skill)}
      >
        <CardHeader className="pb-2">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-amber-500" />
            <CardTitle className="text-lg">{skill.name}</CardTitle>
          </div>
          {skill.description && (
            <CardDescription className="line-clamp-2">
              {skill.description}
            </CardDescription>
          )}
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 flex-wrap">
            {getLocationBadge(skill.location)}
            {hasDeps && !hasMissing && (
              <Badge
                variant="outline"
                className="text-green-600 border-green-200 bg-green-50 flex items-center gap-1"
              >
                <CheckCircle2 className="h-3 w-3" />
                Deps OK
              </Badge>
            )}
            {hasMissing && (
              <Badge
                variant="outline"
                className="text-amber-600 border-amber-200 bg-amber-50 flex items-center gap-1"
              >
                <AlertTriangle className="h-3 w-3" />
                {missingCount} missing
              </Badge>
            )}
          </div>
        </CardContent>
      </Card>
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Sparkles className="h-8 w-8" />
            Skills
          </h1>
          <p className="text-muted-foreground mt-1">
            Skills extend Claude's capabilities with specialized knowledge and
            workflows
          </p>
        </div>
        {activeTab === "installed" && (
          <RefreshButton onClick={fetchSkills} loading={loading} />
        )}
      </div>

      {/* Error Display */}
      {error && activeTab === "installed" && (
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-destructive">Error</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      )}

      {/* Tabs */}
      <Tabs
        value={activeTab}
        onValueChange={(v) => setActiveTab(v as SkillsTab)}
      >
        <TabsList>
          <TabsTrigger value="installed" className="flex items-center gap-2">
            <FolderOpen className="h-4 w-4" />
            Installed ({skills.length})
          </TabsTrigger>
          <TabsTrigger value="discover" className="flex items-center gap-2">
            <Store className="h-4 w-4" />
            Discover
          </TabsTrigger>
        </TabsList>

        {/* Installed Tab */}
        <TabsContent value="installed">
          <div className="space-y-6">
            {/* Stats */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Card>
                <CardHeader className="pb-3">
                  <CardDescription className="flex items-center gap-2">
                    <Sparkles className="h-4 w-4 text-amber-500" />
                    Total Skills
                  </CardDescription>
                  <CardTitle className="text-3xl">{skills.length}</CardTitle>
                </CardHeader>
              </Card>
              <Card>
                <CardHeader className="pb-3">
                  <CardDescription className="flex items-center gap-2">
                    <MapPin className="h-4 w-4 text-primary" />
                    User Skills
                  </CardDescription>
                  <CardTitle className="text-3xl">
                    {userSkills.length}
                  </CardTitle>
                </CardHeader>
              </Card>
              <Card>
                <CardHeader className="pb-3">
                  <CardDescription className="flex items-center gap-2">
                    <MapPin className="h-4 w-4 text-secondary-foreground" />
                    Plugin Skills
                  </CardDescription>
                  <CardTitle className="text-3xl">
                    {pluginSkills.length}
                  </CardTitle>
                </CardHeader>
              </Card>
            </div>

            {loading ? (
              <div className="text-center py-8 text-muted-foreground">
                Loading...
              </div>
            ) : skills.length === 0 ? (
              <Card>
                <CardContent className="py-8 text-center text-muted-foreground">
                  <p>No skills found.</p>
                  <p className="mt-2">
                    Check the{" "}
                    <button
                      className="underline hover:text-foreground transition-colors"
                      onClick={() => setActiveTab("discover")}
                    >
                      Discover
                    </button>{" "}
                    tab to browse and install skills from skills.sh.
                  </p>
                </CardContent>
              </Card>
            ) : (
              <div className="space-y-6">
                {/* User Skills */}
                {userSkills.length > 0 && (
                  <Card>
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2">
                        <MapPin className="h-5 w-5 text-primary" />
                        User Skills
                      </CardTitle>
                      <CardDescription>
                        Skills defined in ~/.claude/skills/
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        {userSkills.map(renderSkillCard)}
                      </div>
                    </CardContent>
                  </Card>
                )}

                {/* Project Skills */}
                {projectSkills.length > 0 && (
                  <Card>
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2">
                        <MapPin className="h-5 w-5 text-primary" />
                        Project Skills
                      </CardTitle>
                      <CardDescription>
                        Skills defined in .claude/skills/
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        {projectSkills.map(renderSkillCard)}
                      </div>
                    </CardContent>
                  </Card>
                )}

                {/* Plugin Skills - Grouped by plugin */}
                {Object.entries(pluginGroups).map(
                  ([pluginName, pluginSkillList]) => (
                    <Card key={pluginName}>
                      <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                          <Sparkles className="h-5 w-5 text-amber-500" />
                          {pluginName}
                        </CardTitle>
                        <CardDescription>
                          {pluginSkillList.length} skill
                          {pluginSkillList.length !== 1 ? "s" : ""} from this
                          plugin
                        </CardDescription>
                      </CardHeader>
                      <CardContent>
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                          {pluginSkillList.map(renderSkillCard)}
                        </div>
                      </CardContent>
                    </Card>
                  )
                )}
              </div>
            )}
          </div>
        </TabsContent>

        {/* Discover Tab */}
        <TabsContent value="discover">
          <SkillRegistryBrowser onInstallComplete={fetchSkills} />
        </TabsContent>
      </Tabs>

      {/* Skill Detail Dialog */}
      <SkillDetailDialog
        skill={selectedSkill}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        projectPath={activeProject?.path}
      />
    </div>
  );
}
