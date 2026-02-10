import { useState, useEffect, useMemo } from "react";
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
import { ChevronDown, HelpCircle, Lightbulb } from "lucide-react";
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

  // Get the selected tool info for hints
  const selectedTool = useMemo(
    () => PERMISSION_TOOLS.find((t) => t.name === tool),
    [tool]
  );

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
          // Try Tool:subcommand format
          const subMatch = editingRule.pattern.match(/^(\w+):(.+)$/);
          if (subMatch) {
            setTool(subMatch[1]);
            setArgument(`:${subMatch[2]}`);
          } else {
            setTool(editingRule.pattern);
            setArgument("");
          }
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
    // Handle :subcommand syntax
    if (argument.startsWith(":")) {
      return `${tool}${argument}`;
    }
    return `${tool}(${argument})`;
  };

  const handleSave = async () => {
    const pattern = buildPattern();
    if (!pattern) return;

    setSaving(true);
    try {
      await onSave({ type, pattern, scope });
      onOpenChange(false);
    } catch {
      // Error handled by parent
    } finally {
      setSaving(false);
    }
  };

  // Get relevant examples for the selected tool
  const relevantExamples = useMemo(() => {
    if (!tool) return PATTERN_EXAMPLES;
    return PATTERN_EXAMPLES.filter((ex) => ex.pattern.startsWith(tool));
  }, [tool]);

  const pattern = buildPattern();

  const getTypeBadgeClass = (ruleType: PermissionType) => {
    switch (ruleType) {
      case "allow":
        return "bg-success text-success-foreground";
      case "ask":
        return "bg-warning text-warning-foreground";
      case "deny":
        return "bg-destructive text-destructive-foreground";
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[550px]">
        <DialogHeader>
          <DialogTitle>
            {editingRule ? "Edit Permission Rule" : "Create Permission Rule"}
          </DialogTitle>
          <DialogDescription>
            Define a permission rule to allow, ask, or deny specific tool operations
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
                    <Badge className="bg-success text-success-foreground">Allow</Badge>
                    Permit automatically
                  </span>
                </SelectItem>
                <SelectItem value="ask">
                  <span className="flex items-center gap-2">
                    <Badge className="bg-warning text-warning-foreground">Ask</Badge>
                    Prompt for confirmation
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

          {/* Pattern Argument with Hint */}
          <div className="space-y-2">
            <Label>Pattern (optional)</Label>
            <Input
              value={argument}
              onChange={(e) => setArgument(e.target.value)}
              placeholder={selectedTool?.hint || "e.g., npm run *, *.py, /etc/*"}
            />
            <div className="flex items-start gap-2 text-xs text-muted-foreground">
              <Lightbulb className="h-3 w-3 mt-0.5 flex-shrink-0" />
              <div>
                {selectedTool ? (
                  <span>
                    {selectedTool.hint ? (
                      <>
                        <strong>Hint:</strong> {selectedTool.name}({selectedTool.hint})
                      </>
                    ) : (
                      <>Leave empty to match all {selectedTool.name} operations</>
                    )}
                  </span>
                ) : (
                  <span>Select a tool to see pattern hints</span>
                )}
              </div>
            </div>
          </div>

          {/* Quick Pattern Buttons */}
          {tool && (
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Quick Patterns</Label>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setArgument("*")}
                  className="h-7 text-xs"
                >
                  Match All (*)
                </Button>
                {tool === "WebFetch" && (
                  <>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setArgument("domain:github.com")}
                      className="h-7 text-xs"
                    >
                      domain:github.com
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setArgument("domain:*.anthropic.com")}
                      className="h-7 text-xs"
                    >
                      domain:*.anthropic.com
                    </Button>
                  </>
                )}
                {tool === "MCP" && (
                  <>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setArgument("server:*")}
                      className="h-7 text-xs"
                    >
                      server:*
                    </Button>
                  </>
                )}
                {tool === "Bash" && (
                  <>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setArgument("npm run *")}
                      className="h-7 text-xs"
                    >
                      npm run *
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setArgument("git *")}
                      className="h-7 text-xs"
                    >
                      git *
                    </Button>
                  </>
                )}
                {(tool === "Read" || tool === "Write" || tool === "Edit") && (
                  <>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setArgument("*.py")}
                      className="h-7 text-xs"
                    >
                      *.py
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setArgument("*.ts")}
                      className="h-7 text-xs"
                    >
                      *.ts
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setArgument("/tmp/*")}
                      className="h-7 text-xs"
                    >
                      /tmp/*
                    </Button>
                  </>
                )}
                {tool === "Task" && (
                  <>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setArgument(":explore")}
                      className="h-7 text-xs"
                    >
                      :explore
                    </Button>
                  </>
                )}
              </div>
            </div>
          )}

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
                  className={`${getTypeBadgeClass(type)} mr-2`}
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
              <div className="space-y-1 text-sm max-h-48 overflow-y-auto">
                {(relevantExamples.length > 0 ? relevantExamples : PATTERN_EXAMPLES).map((ex) => (
                  <div
                    key={ex.pattern}
                    className="flex items-center gap-2 p-2 hover:bg-muted rounded cursor-pointer"
                    onClick={() => {
                      const match = ex.pattern.match(/^(\w+)(?:\((.+)\))?$/);
                      if (match) {
                        setTool(match[1]);
                        setArgument(match[2] || "");
                      } else {
                        const subMatch = ex.pattern.match(/^(\w+):(.+)$/);
                        if (subMatch) {
                          setTool(subMatch[1]);
                          setArgument(`:${subMatch[2]}`);
                        }
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
