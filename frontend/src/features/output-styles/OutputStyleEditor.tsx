import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { type OutputStyle, type OutputStyleUpdate } from "@/types/output-styles";

interface OutputStyleEditorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  style: OutputStyle | null;
  onSave: (update: OutputStyleUpdate) => Promise<void>;
}

export function OutputStyleEditor({
  open,
  onOpenChange,
  style,
  onSave,
}: OutputStyleEditorProps) {
  const [description, setDescription] = useState("");
  const [keepCodingInstructions, setKeepCodingInstructions] = useState(false);
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);

  // Reset form when style changes
  useEffect(() => {
    if (style) {
      setDescription(style.description || "");
      setKeepCodingInstructions(style.keep_coding_instructions);
      setContent(style.content || "");
    }
  }, [style]);

  const handleSave = async () => {
    if (!style) return;

    setSaving(true);
    try {
      await onSave({
        description: description || undefined,
        keep_coding_instructions: keepCodingInstructions,
        content,
      });
      onOpenChange(false);
    } catch {
      // Error handled by parent
    } finally {
      setSaving(false);
    }
  };

  if (!style) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[700px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Edit Output Style: {style.name}</DialogTitle>
          <DialogDescription>
            Modify the output style configuration and instructions
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Description */}
          <div className="space-y-2">
            <Label htmlFor="description">Description</Label>
            <Input
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="A brief description of this output style"
            />
          </div>

          {/* Keep Coding Instructions */}
          <div className="flex items-center justify-between rounded-lg border p-4">
            <div className="space-y-0.5">
              <Label htmlFor="keep-coding-instructions">
                Keep Coding Instructions
              </Label>
              <p className="text-sm text-muted-foreground">
                When enabled, Claude Code will retain its default coding-related
                instructions alongside this style
              </p>
            </div>
            <Switch
              id="keep-coding-instructions"
              checked={keepCodingInstructions}
              onCheckedChange={setKeepCodingInstructions}
            />
          </div>

          {/* Content */}
          <div className="space-y-2">
            <Label htmlFor="content">Style Instructions</Label>
            <Textarea
              id="content"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Write markdown instructions that define this output style..."
              className="min-h-[300px] font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">
              Markdown instructions that tell Claude how to format its responses
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "Saving..." : "Save Changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
