import { useState } from "react";
import type { MarketplaceResponse } from "@/types/plugins";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Store, Plus, Trash2, RefreshCw, RotateCcw } from "lucide-react";
import { toast } from "sonner";

interface MarketplaceManagerProps {
  marketplaces: MarketplaceResponse[];
  onRefresh: () => void;
}

export function MarketplaceManager({ marketplaces, onRefresh }: MarketplaceManagerProps) {
  const [showAddForm, setShowAddForm] = useState(false);
  const [marketplaceInput, setMarketplaceInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [updating, setUpdating] = useState<string | null>(null);
  const [togglingAutoUpdate, setTogglingAutoUpdate] = useState<string | null>(null);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);

    try {
      const response = await fetch("/api/v1/plugins/marketplaces", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input: marketplaceInput }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Failed to add marketplace");
      }

      const result = await response.json();
      toast.success(`Marketplace "${result.name}" added successfully`);
      setMarketplaceInput("");
      setShowAddForm(false);
      onRefresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to add marketplace");
    } finally {
      setSubmitting(false);
    }
  };

  const handleRemove = async (name: string) => {
    if (!confirm(`Remove marketplace "${name}"?`)) {
      return;
    }

    try {
      const response = await fetch(`/api/v1/plugins/marketplaces/${name}`, {
        method: "DELETE",
      });

      if (!response.ok) {
        throw new Error("Failed to remove marketplace");
      }

      toast.success(`Marketplace "${name}" removed`);
      onRefresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to remove marketplace");
    }
  };

  const handleUpdate = async (name: string) => {
    setUpdating(name);

    try {
      const response = await fetch(`/api/v1/plugins/marketplace/${name}/update`, {
        method: "POST",
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Failed to update marketplace");
      }

      toast.success(`Marketplace "${name}" updated successfully`);
      onRefresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to update marketplace");
    } finally {
      setUpdating(null);
    }
  };

  const handleAutoUpdateToggle = async (name: string, enabled: boolean) => {
    setTogglingAutoUpdate(name);

    try {
      const response = await fetch(`/api/v1/plugins/marketplace/${name}/auto-update`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Failed to toggle auto-update");
      }

      toast.success(
        `Auto-update ${enabled ? "enabled" : "disabled"} for "${name}"`
      );
      onRefresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to toggle auto-update");
    } finally {
      setTogglingAutoUpdate(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <Store className="h-5 w-5" />
          Marketplaces
          <Badge variant="outline">{marketplaces.length}</Badge>
        </h2>
        <Button
          size="sm"
          onClick={() => setShowAddForm(!showAddForm)}
          variant={showAddForm ? "outline" : "default"}
        >
          <Plus className="h-4 w-4 mr-2" />
          {showAddForm ? "Cancel" : "Add Marketplace"}
        </Button>
      </div>

      {showAddForm && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Add New Marketplace</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleAdd} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="marketplace-input">Marketplace</Label>
                <Input
                  id="marketplace-input"
                  placeholder="owner/repo or https://example.com/plugins.json"
                  value={marketplaceInput}
                  onChange={(e) => setMarketplaceInput(e.target.value)}
                  required
                />
                <p className="text-xs text-muted-foreground">
                  Enter a GitHub repo (e.g., eyaltoledano/claude-task-master) or full URL to plugins.json
                </p>
              </div>
              <div className="flex gap-2">
                <Button type="submit" disabled={submitting || !marketplaceInput.trim()}>
                  {submitting ? "Adding..." : "Add Marketplace"}
                </Button>
                <Button type="button" variant="outline" onClick={() => setShowAddForm(false)}>
                  Cancel
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {marketplaces.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            No marketplaces configured. Add one to get started.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {marketplaces.map((marketplace) => (
            <Card key={marketplace.name}>
              <CardContent className="py-4">
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="font-semibold">{marketplace.name}</h3>
                      <Badge variant="outline" className="text-xs">
                        {marketplace.plugin_count} plugin{marketplace.plugin_count !== 1 ? "s" : ""}
                      </Badge>
                      {marketplace.last_updated && (
                        <Badge variant="secondary" className="text-xs">
                          Updated {new Date(marketplace.last_updated).toLocaleDateString()}
                        </Badge>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground font-mono">
                      {marketplace.repo}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    {/* Auto-update toggle */}
                    <div className="flex items-center gap-2">
                      <Label
                        htmlFor={`auto-update-${marketplace.name}`}
                        className="text-xs text-muted-foreground cursor-pointer flex items-center gap-1"
                      >
                        <RotateCcw className="h-3 w-3" />
                        Auto-update
                      </Label>
                      <Switch
                        id={`auto-update-${marketplace.name}`}
                        checked={marketplace.auto_update}
                        onCheckedChange={(checked) =>
                          handleAutoUpdateToggle(marketplace.name, checked)
                        }
                        disabled={togglingAutoUpdate === marketplace.name}
                      />
                    </div>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleUpdate(marketplace.name)}
                        disabled={updating === marketplace.name}
                        title="Update marketplace"
                      >
                        <RefreshCw
                          className={`h-4 w-4 ${updating === marketplace.name ? "animate-spin" : ""}`}
                        />
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => handleRemove(marketplace.name)}
                        title="Remove marketplace"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
