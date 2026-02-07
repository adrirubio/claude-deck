import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { MarkdownRenderer } from "@/components/shared/MarkdownRenderer";
import { MODAL_SIZES } from "@/lib/constants";
import { Terminal, MessageSquare, Bot, Clock, Repeat, Loader2, Pencil } from "lucide-react";
import type { Hook } from "@/types/hooks";
import { AGENT_MODELS } from "@/types/hooks";

interface HookDetailDialogProps {
  hook: Hook | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onEdit: (hook: Hook) => void;
}

export function HookDetailDialog({ hook, open, onOpenChange, onEdit }: HookDetailDialogProps) {
  if (!hook) return null;

  const getTypeIcon = () => {
    switch (hook.type) {
      case "command":
        return <Terminal className="h-5 w-5" />;
      case "prompt":
        return <MessageSquare className="h-5 w-5" />;
      case "agent":
        return <Bot className="h-5 w-5" />;
    }
  };

  const getTypeLabel = () => {
    switch (hook.type) {
      case "command":
        return "Command";
      case "prompt":
        return "Prompt";
      case "agent":
        return "Agent";
    }
  };

  const getModelLabel = (modelValue: string) => {
    const model = AGENT_MODELS.find((m) => m.value === modelValue);
    return model?.label || modelValue;
  };

  const handleEdit = () => {
    onOpenChange(false);
    onEdit(hook);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={MODAL_SIZES.SM}>
        <DialogHeader>
          <div className="flex items-center gap-3">
            {getTypeIcon()}
            <DialogTitle className="text-xl">{hook.event}</DialogTitle>
            <Badge variant={hook.scope === "user" ? "default" : "secondary"}>
              {hook.scope}
            </Badge>
          </div>
          <DialogDescription>
            {getTypeLabel()} hook
            {hook.type === "agent" && hook.model && (
              <> using {getModelLabel(hook.model)}</>
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Matcher Pattern */}
          {hook.matcher && (
            <div className="space-y-1">
              <div className="text-sm font-medium text-muted-foreground">Matcher Pattern</div>
              <code className="block text-sm bg-muted px-3 py-2 rounded-md">
                {hook.matcher}
              </code>
            </div>
          )}

          {/* Command Content */}
          {hook.type === "command" && hook.command && (
            <div className="space-y-1">
              <div className="text-sm font-medium text-muted-foreground">Command</div>
              <pre className="bg-muted rounded-md p-3 font-mono text-sm overflow-x-auto">
                {hook.command}
              </pre>
            </div>
          )}

          {/* Prompt/Agent Content */}
          {(hook.type === "prompt" || hook.type === "agent") && hook.prompt && (
            <div className="space-y-1">
              <div className="text-sm font-medium text-muted-foreground">
                {hook.type === "agent" ? "Agent Prompt" : "Prompt"}
              </div>
              <div className="border rounded-md p-3 bg-muted/30">
                <MarkdownRenderer content={hook.prompt} />
              </div>
            </div>
          )}

          {/* Metadata */}
          <div className="flex flex-wrap gap-2">
            {hook.async_ && (
              <Badge variant="outline" className="flex items-center gap-1">
                <Loader2 className="h-3 w-3" />
                Async
              </Badge>
            )}
            {hook.once && (
              <Badge variant="outline" className="flex items-center gap-1">
                <Repeat className="h-3 w-3" />
                Once
              </Badge>
            )}
            {hook.timeout && (
              <Badge variant="outline" className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {hook.timeout}s timeout
              </Badge>
            )}
          </div>

          {/* Status Message */}
          {hook.statusMessage && (
            <div className="space-y-1">
              <div className="text-sm font-medium text-muted-foreground">Status Message</div>
              <span className="text-sm italic">"{hook.statusMessage}"</span>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button onClick={handleEdit}>
            <Pencil className="h-4 w-4 mr-2" />
            Edit
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
