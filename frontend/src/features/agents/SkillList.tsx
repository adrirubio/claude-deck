import { Sparkles, MapPin } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { type Skill } from "@/types/agents";

interface SkillListProps {
  skills: Skill[];
}

export function SkillList({ skills }: SkillListProps) {
  if (skills.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No skills found. Skills are provided by plugins or defined in your
        .claude/skills directory.
      </div>
    );
  }

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
    // Plugin location
    return (
      <Badge variant="secondary" className="flex items-center gap-1">
        <MapPin className="h-3 w-3" />
        {location}
      </Badge>
    );
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {skills.map((skill) => (
        <Card key={`${skill.location}-${skill.name}`} className="hover:bg-muted/50 transition-colors">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-amber-500" />
              <CardTitle className="text-lg">{skill.name}</CardTitle>
            </div>
            {skill.description && (
              <CardDescription>{skill.description}</CardDescription>
            )}
          </CardHeader>
          <CardContent>
            {getLocationBadge(skill.location)}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
