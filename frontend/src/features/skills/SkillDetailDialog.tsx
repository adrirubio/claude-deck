import { useEffect, useState } from "react";
import { Sparkles, MapPin, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { apiClient, buildEndpoint } from "@/lib/api";
import { type Skill } from "@/types/agents";

interface SkillDetailDialogProps {
  skill: Skill | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectPath?: string;
}

export function SkillDetailDialog({
  skill,
  open,
  onOpenChange,
  projectPath,
}: SkillDetailDialogProps) {
  const [fullSkill, setFullSkill] = useState<Skill | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open && skill) {
      fetchSkillDetails();
    } else {
      setFullSkill(null);
      setError(null);
    }
  }, [open, skill?.name, skill?.location]);

  const fetchSkillDetails = async () => {
    if (!skill) return;

    setLoading(true);
    setError(null);
    try {
      const params = projectPath ? { project_path: projectPath } : {};
      const response = await apiClient<Skill>(
        buildEndpoint(`agents/skills/${encodeURIComponent(skill.location)}/${encodeURIComponent(skill.name)}`, params)
      );
      setFullSkill(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load skill details");
    } finally {
      setLoading(false);
    }
  };

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
    const pluginName = location.replace("plugin:", "");
    return (
      <Badge variant="secondary" className="flex items-center gap-1">
        <Sparkles className="h-3 w-3" />
        {pluginName}
      </Badge>
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <Sparkles className="h-6 w-6 text-amber-500 flex-shrink-0" />
            <DialogTitle className="text-xl">{skill?.name}</DialogTitle>
            {skill && getLocationBadge(skill.location)}
          </div>
          {skill?.description && (
            <DialogDescription className="text-base mt-2">
              {skill.description}
            </DialogDescription>
          )}
        </DialogHeader>

        <div className="flex-1 overflow-auto mt-4">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : error ? (
            <div className="text-center py-8 text-destructive">
              <p>{error}</p>
            </div>
          ) : fullSkill?.content ? (
            <div className="rounded-lg border bg-muted/50 p-4">
              <pre className="whitespace-pre-wrap font-mono text-sm leading-relaxed text-foreground">
                {fullSkill.content}
              </pre>
            </div>
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              <p>No content available for this skill.</p>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
