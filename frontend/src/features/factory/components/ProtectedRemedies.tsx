import { useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from "@/components/ui/alert-dialog";
import { ApiHttpError } from "@/lib/api";
import { retryGithubWorkItem } from "@/features/agent-teams/api";
import {
  clearOperatorToken,
  getOperatorToken,
  setOperatorToken,
} from "@/features/agent-teams/operatorAuth";
import type { WorkProjection } from "@/types/factory";
import { markWorkListsDirty } from "../reads";
import { panel } from "./styles";

export function ProtectedRemedies({
  work,
  refresh,
}: {
  work: WorkProjection;
  refresh: () => Promise<void>;
}) {
  const [operation, setOperation] = useState<"retry" | null>(null);
  const [confirmRetry, setConfirmRetry] = useState(false);
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const retry = work.actions.find((action) => action.name === "retry");
  const context = useRef({ generation: 0, active: false, work, refresh });
  const retryConfirmed = useRef(false);
  const running = useRef(false);
  useLayoutEffect(() => {
    context.current.work = work;
    context.current.refresh = refresh;
  }, [work, refresh]);
  useLayoutEffect(() => {
    const target = context.current;
    target.active = true;
    return () => {
      target.active = false;
      target.generation += 1;
      retryConfirmed.current = false;
    };
  }, []);

  async function run(action: "retry", credential: string) {
    const target = context.current;
    if (!target.active || running.current) return;
    if (action === "retry") {
      if (!retryConfirmed.current) return;
      // Each confirmation permits exactly one mutation, including a denied one.
      retryConfirmed.current = false;
      if (
        target.work.actions.find((a) => a.name === "retry")?.state !== "eligible"
      ) {
        setError("Retry eligibility changed. Refresh and review this work item.");
        setOperation(null);
        return;
      }
    }
    const generation = target.generation;
    const workItemId = target.work.item.id;
    const current = () =>
      context.current.active &&
      context.current.generation === generation &&
      context.current.work.item.id === workItemId;
    running.current = true;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      if (action === "retry") {
        const response = await retryGithubWorkItem(workItemId, credential);
        // A sent mutation may affect a paused list even after detail navigation.
        markWorkListsDirty();
        if (!current()) return;
        if (response.id !== workItemId) {
          throw new Error(
            "Retry returned a different work item. Refresh to inspect current state.",
          );
        }
        setResult(
          response.retry_requested_at
          ? `Retry requested; re-dispatch is deferred until the current owner releases the workspace. Dispatch status: ${response.dispatch_status}. ${response.status_note ?? ""}`
          : response.dispatch_status === "pending"
            ? "Retry reset this work item to pending. Deck has not yet seen a new dispatch."
            : `Retry response status: ${response.dispatch_status}. Deck has not yet seen a new dispatch. ${response.status_note ?? ""}`,
        );
        await context.current.refresh();
      }
      if (!current()) return;
      setOperation(null);
      setToken("");
    } catch (failure) {
      if (action === "retry") markWorkListsDirty();
      if (!current()) return;
      const message =
        failure instanceof Error ? failure.message : "Action failed";
      if (failure instanceof ApiHttpError && failure.status === 401) {
        clearOperatorToken();
        setToken("");
        setOperation(action);
      }
      setError(message);
      if (action === "retry") await context.current.refresh();
    } finally {
      running.current = false;
      if (current()) setBusy(false);
    }
  }
  const begin = (action: "retry") => {
    if (!context.current.active || running.current) return;
    const credential = getOperatorToken();
    if (credential) void run(action, credential);
    else setOperation(action);
  };
  return (
    <section className={panel}>
      <h3 className="font-semibold">Protected recovery</h3>
      <p>
        Deck checks again on the server that you may do this. Agent decisions
        and human PR review stay separate.
      </p>
      <div className="flex flex-wrap gap-3">
        <Button
          variant="outline"
          disabled={busy || retry?.state !== "eligible"}
          onClick={() => {
            retryConfirmed.current = false;
            setError(null);
            setConfirmRetry(true);
          }}
        >
          Retry issue
        </Button>
      </div>
      <p>
        Retry: {retry?.state ?? "unknown"} · required actor{" "}
        {retry?.required_actor ?? "unknown"} ·{" "}
        {(retry?.reason ?? "Eligibility unavailable").replace(/[.\s]+$/, "")}.
        Retrying may reset attempt markers.
      </p>
      {error && <p role="alert">{error}</p>}
      {result && <p role="status">{result}</p>}
      <AlertDialog
        open={confirmRetry}
        onOpenChange={(open) => {
          setConfirmRetry(open);
          if (!open) retryConfirmed.current = false;
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Retry issue #{work.item.issue_number}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              Retry can discard prior PR, handoff, and attempt markers. If the
              workspace is still leased, Deck defers re-dispatch until the current
              owner releases it. Review this work item before continuing. The
              server rechecks current eligibility and authorization.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={busy || retry?.state !== "eligible"}
              onClick={(event) => {
                event.preventDefault();
                if (!context.current.active || running.current) return;
                retryConfirmed.current = true;
                setConfirmRetry(false);
                begin("retry");
              }}
            >
              Confirm retry
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <Dialog
        open={operation !== null}
        onOpenChange={(open) => {
          if (!open) {
            setOperation(null);
            setToken("");
            retryConfirmed.current = false;
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Director authorization</DialogTitle>
            <DialogDescription>
              Retry this issue using current server eligibility. Attempt markers may
              reset. Uses the Director key that this tab already holds.
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (
                operation && token.trim() && context.current.active &&
                !running.current
              ) {
                setOperatorToken(token);
                if (operation === "retry" && !retryConfirmed.current) {
                  // A 401 consumed the prior confirmation. Review again before retrying.
                  setOperation(null);
                  setToken("");
                  setConfirmRetry(true);
                } else {
                  void run(operation, token.trim());
                }
              }
            }}
          >
            <label className="grid gap-2">
              Director key
              <input
                autoFocus
                type="password"
                autoComplete="off"
                className="rounded border bg-background p-2"
                value={token}
                onChange={(event) => setToken(event.target.value)}
              />
            </label>
            <Button disabled={busy || !token.trim()}>
              Authorize {operation}
            </Button>
            {error && <p role="alert">{error}</p>}
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
