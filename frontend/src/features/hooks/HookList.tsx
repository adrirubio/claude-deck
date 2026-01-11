import { HookCard } from "./HookCard";
import type { Hook } from "@/types/hooks";

interface HookListProps {
  hooks: Hook[];
  onEdit: (hook: Hook) => void;
  onDelete: (hookId: string, scope: "user" | "project") => void;
}

export function HookList({ hooks, onEdit, onDelete }: HookListProps) {
  if (hooks.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <p>No hooks configured for this event type.</p>
        <p className="text-sm mt-1">
          Click "Add Hook" to create your first hook.
        </p>
      </div>
    );
  }

  // Group hooks by scope
  const userHooks = hooks.filter((h) => h.scope === "user");
  const projectHooks = hooks.filter((h) => h.scope === "project");

  return (
    <div className="space-y-6">
      {userHooks.length > 0 && (
        <div>
          <h3 className="text-sm font-medium mb-3 flex items-center gap-2">
            User Hooks
            <span className="text-muted-foreground">({userHooks.length})</span>
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {userHooks.map((hook) => (
              <HookCard
                key={hook.id}
                hook={hook}
                onEdit={onEdit}
                onDelete={onDelete}
              />
            ))}
          </div>
        </div>
      )}

      {projectHooks.length > 0 && (
        <div>
          <h3 className="text-sm font-medium mb-3 flex items-center gap-2">
            Project Hooks
            <span className="text-muted-foreground">
              ({projectHooks.length})
            </span>
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {projectHooks.map((hook) => (
              <HookCard
                key={hook.id}
                hook={hook}
                onEdit={onEdit}
                onDelete={onDelete}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
