import { useState } from "react";
import type { MarketplacePlugin, PluginInstallResponse } from "@/types/plugins";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Download, Loader2, CheckCircle, XCircle } from "lucide-react";

interface PluginInstallWizardProps {
  plugin: MarketplacePlugin | null;
  marketplaceName: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onComplete: () => void;
}

type WizardStep = "confirm" | "installing" | "result";

export function PluginInstallWizard({
  plugin,
  marketplaceName,
  open,
  onOpenChange,
  onComplete,
}: PluginInstallWizardProps) {
  const [step, setStep] = useState<WizardStep>("confirm");
  const [installResult, setInstallResult] = useState<PluginInstallResponse | null>(null);

  const handleInstall = async () => {
    if (!plugin || marketplaceName === null) return;

    setStep("installing");

    try {
      const response = await fetch("/api/v1/plugins/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: plugin.name,
          marketplace_name: marketplaceName,
        }),
      });

      const data = await response.json();
      setInstallResult(data);
      setStep("result");
    } catch (error) {
      setInstallResult({
        success: false,
        message: error instanceof Error ? error.message : "Installation failed",
        stdout: "",
        stderr: "",
      });
      setStep("result");
    }
  };

  const handleClose = () => {
    if (step === "result" && installResult?.success) {
      onComplete();
    }
    onOpenChange(false);
    // Reset state after closing
    setTimeout(() => {
      setStep("confirm");
      setInstallResult(null);
    }, 300);
  };

  if (!plugin) return null;

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        {/* Step 1: Confirm */}
        {step === "confirm" && (
          <>
            <DialogHeader>
              <DialogTitle>Install Plugin</DialogTitle>
              <DialogDescription>
                Confirm plugin installation details
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-4">
              <div className="border rounded-lg p-4 space-y-3">
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold">{plugin.name}</h3>
                  {plugin.version && <Badge variant="outline">v{plugin.version}</Badge>}
                </div>
                {plugin.description && (
                  <p className="text-sm text-muted-foreground">{plugin.description}</p>
                )}
                <div className="text-xs font-mono text-muted-foreground bg-muted p-2 rounded">
                  {plugin.install_command}
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-4">
              <Button variant="outline" onClick={handleClose}>
                Cancel
              </Button>
              <Button onClick={handleInstall}>
                <Download className="h-4 w-4 mr-2" />
                Install Plugin
              </Button>
            </div>
          </>
        )}

        {/* Step 2: Installing */}
        {step === "installing" && (
          <>
            <DialogHeader>
              <DialogTitle>Installing Plugin</DialogTitle>
              <DialogDescription>
                Please wait while {plugin.name} is being installed...
              </DialogDescription>
            </DialogHeader>

            <div className="py-12 text-center">
              <Loader2 className="h-12 w-12 animate-spin mx-auto mb-4 text-primary" />
              <p className="text-muted-foreground">Running installation command...</p>
              <p className="text-xs font-mono text-muted-foreground mt-2">
                {plugin.install_command}
              </p>
            </div>
          </>
        )}

        {/* Step 3: Result */}
        {step === "result" && installResult && (
          <>
            <DialogHeader>
              <DialogTitle>Installation {installResult.success ? "Complete" : "Failed"}</DialogTitle>
              <DialogDescription>
                {installResult.message}
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-4">
              <div className="flex items-center justify-center py-8">
                {installResult.success ? (
                  <div className="text-center">
                    <CheckCircle className="h-16 w-16 text-green-500 mx-auto mb-4" />
                    <p className="text-lg font-semibold">Plugin installed successfully!</p>
                  </div>
                ) : (
                  <div className="text-center">
                    <XCircle className="h-16 w-16 text-destructive mx-auto mb-4" />
                    <p className="text-lg font-semibold">Installation failed</p>
                  </div>
                )}
              </div>

              {/* stdout output */}
              {installResult.stdout && (
                <div className="space-y-2">
                  <h4 className="text-sm font-semibold">Output:</h4>
                  <pre className="text-xs font-mono bg-muted p-3 rounded overflow-x-auto max-h-48 overflow-y-auto">
                    {installResult.stdout}
                  </pre>
                </div>
              )}

              {/* stderr output */}
              {installResult.stderr && (
                <div className="space-y-2">
                  <h4 className="text-sm font-semibold text-destructive">Errors:</h4>
                  <pre className="text-xs font-mono bg-destructive/10 p-3 rounded overflow-x-auto max-h-48 overflow-y-auto border border-destructive/20">
                    {installResult.stderr}
                  </pre>
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2 mt-4">
              <Button onClick={handleClose}>
                {installResult.success ? "Done" : "Close"}
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
