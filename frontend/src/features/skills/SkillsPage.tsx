import { useState, useEffect, useCallback } from "react";
import { Sparkles, MapPin } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { RefreshButton } from "@/components/shared/RefreshButton";
import { SkillDetailDialog } from "./SkillDetailDialog";
import { apiClient, buildEndpoint } from "@/lib/api";
import { useProjectContext } from "@/contexts/ProjectContext";
import { toast } from "sonner";
import { type Skill, type SkillListResponse } from "@/types/agents";

export function SkillsPage() {
  const { activeProject } = useProjectContext();
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

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

  const renderSkillCard = (skill: Skill) => (
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
      <CardContent>{getLocationBadge(skill.location)}</CardContent>
    </Card>
  );

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
            Skills extend Claude's capabilities with specialized knowledge and workflows
          </p>
        </div>
        <RefreshButton onClick={fetchSkills} loading={loading} />
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
            <CardTitle className="text-3xl">{userSkills.length}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription className="flex items-center gap-2">
              <MapPin className="h-4 w-4 text-secondary-foreground" />
              Plugin Skills
            </CardDescription>
            <CardTitle className="text-3xl">{pluginSkills.length}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      {loading ? (
        <div className="text-center py-8 text-muted-foreground">Loading...</div>
      ) : skills.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            No skills found. Skills are provided by plugins or defined in your
            ~/.claude/skills directory.
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
          {Object.entries(pluginGroups).map(([pluginName, pluginSkillList]) => (
            <Card key={pluginName}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Sparkles className="h-5 w-5 text-amber-500" />
                  {pluginName}
                </CardTitle>
                <CardDescription>
                  {pluginSkillList.length} skill
                  {pluginSkillList.length !== 1 ? "s" : ""} from this plugin
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {pluginSkillList.map(renderSkillCard)}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

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
