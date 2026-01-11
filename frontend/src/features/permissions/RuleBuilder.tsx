import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Badge } from "@/components/ui/badge";
import { ChevronDown, HelpCircle } from "lucide-react";
import {
  type PermissionRule,
  type PermissionType,
  type PermissionScope,
  PERMISSION_TOOLS,
  PATTERN_EXAMPLES,
} from "@/types/permissions";

interface RuleBuilderProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (rule: {
    type: PermissionType;
    pattern: string;
    scope: PermissionScope;
  }) => Promise<void>;
  editingRule?: PermissionRule | null;
  defaultType?: PermissionType;
}

export function RuleBuilder({
  open,
  onOpenChange,
  onSave,
  editingRule,
  defaultType = "allow",
}: RuleBuilderProps) {
  const [tool, setTool] = useState("");
  const [argument, setArgument] = useState("");
  const [type, setType] = useState<PermissionType>(defaultType);
  const [scope, setScope] = useState<PermissionScope>("user");
  const [saving, setSaving] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  // Reset form when opening or changing editing rule
  useEffect(() => {
    if (open) {
      if (editingRule) {
        // Parse existing pattern
        const match = editingRule.pattern.match(/^(\w+)(?:\((.+)\))?$/);
        if (match) {
          setTool(match[1]);
          setArgument(match[2] || "");
        } else {
          setTool(editingRule.pattern);
          setArgument("");
        }
        setType(editingRule.type);
        setScope(editingRule.scope);
      } else {
        setTool("");
        setArgument("");
        setType(defaultType);
        setScope("user");
      }
    }
  }, [open, editingRule, defaultType]);

  const buildPattern = () => {
    if (!tool) return "";
    if (!argument) return tool;
    return `${tool}(${argument})`;
  };

  const handleSave = async () => {
    const pattern = buildPattern();
    if (!pattern) return;

    setSaving(true);
    try {
      await onSave({ type, pattern, scope });
      onOpenChange(false);
    } catch (error) {
      // Error handled by parent
    } finally {
      setSaving(false);
    }
  };

  const pattern = buildPattern();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>
            {editingRule ? "Edit Permission Rule" : "Create Permission Rule"}
          </DialogTitle>
          <DialogDescription>
            Define a permission rule to allow or deny specific tool operations
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Type Selection */}
          <div className="space-y-2">
            <Label>Rule Type</Label>
            <Select
              value={type}
              onValueChange={(v) => setType(v as PermissionType)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="allow">
                  <span className="flex items-center gap-2">
                    <Badge variant="default" className="bg-success text-success-foreground">Allow</Badge>
                    Permit this operation
                  </span>
                </SelectItem>
                <SelectItem value="deny">
                  <span className="flex items-center gap-2">
                    <Badge variant="destructive">Deny</Badge>
                    Block this operation
                  </span>
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Tool Selection */}
          <div className="space-y-2">
            <Label>Tool</Label>
            <Select value={tool} onValueChange={setTool}>
              <SelectTrigger>
                <SelectValue placeholder="Select a tool..." />
              </SelectTrigger>
              <SelectContent>
                {PERMISSION_TOOLS.map((t) => (
                  <SelectItem key={t.name} value={t.name}>
                    <span className="flex items-center gap-2">
                      <code className="text-sm bg-muted px-1 rounded">
                        {t.name}
                      </code>
                      <span className="text-muted-foreground text-sm">
                        {t.description}
                      </span>
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Pattern Argument */}
          <div className="space-y-2">
            <Label>Pattern (optional)</Label>
            <Input
              value={argument}
              onChange={(e) => setArgument(e.target.value)}
              placeholder="e.g., npm:*, *.py, /etc/*"
            />
            <p className="text-xs text-muted-foreground">
              Leave empty to match all uses of the tool
            </p>
          </div>

          {/* Scope Selection */}
          <div className="space-y-2">
            <Label>Scope</Label>
            <Select
              value={scope}
              onValueChange={(v) => setScope(v as PermissionScope)}
              disabled={!!editingRule}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="user">
                  User (applies globally)
                </SelectItem>
                <SelectItem value="project">
                  Project (applies to current project only)
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Pattern Preview */}
          {pattern && (
            <div className="space-y-2">
              <Label>Pattern Preview</Label>
              <div className="p-3 bg-muted rounded-md font-mono text-sm">
                <Badge
                  variant={type === "allow" ? "default" : "destructive"}
                  className={type === "allow" ? "bg-success text-success-foreground mr-2" : "mr-2"}
                >
                  {type}
                </Badge>
                {pattern}
              </div>
            </div>
          )}

          {/* Help Section */}
          <Collapsible open={showHelp} onOpenChange={setShowHelp}>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" className="w-full justify-start">
                <HelpCircle className="h-4 w-4 mr-2" />
                Pattern Examples
                <ChevronDown
                  className={`h-4 w-4 ml-auto transition-transform ${
                    showHelp ? "rotate-180" : ""
                  }`}
                />
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-2">
              <div className="space-y-1 text-sm">
                {PATTERN_EXAMPLES.map((ex) => (
                  <div
                    key={ex.pattern}
                    className="flex items-center gap-2 p-2 hover:bg-muted rounded cursor-pointer"
                    onClick={() => {
                      const match = ex.pattern.match(/^(\w+)(?:\((.+)\))?$/);
                      if (match) {
                        setTool(match[1]);
                        setArgument(match[2] || "");
                      }
                    }}
                  >
                    <code className="text-xs bg-muted px-1 rounded">
                      {ex.pattern}
                    </code>
                    <span className="text-muted-foreground">
                      {ex.description}
                    </span>
                  </div>
                ))}
              </div>
            </CollapsibleContent>
          </Collapsible>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={!pattern || saving}>
            {saving ? "Saving..." : editingRule ? "Update Rule" : "Create Rule"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
