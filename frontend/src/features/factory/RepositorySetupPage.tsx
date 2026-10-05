import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ApiHttpError, apiClient } from "@/lib/api";
import {
  createAgentTeamPreset,
  createTeamGithubScope,
  fetchAgentTeamPresets,
  fetchTeamGithubScopes,
  launchAgentTeam,
  planAgentTeamLaunch,
  updateAgentTeamLeader,
  updateAgentTeamPreset,
  updateTeamGithubScope,
} from "@/features/agent-teams/api";
import { getOperatorToken } from "@/features/agent-teams/operatorAuth";
import type { AgentTeamPreset, AgentTeamPresetInput, AgentTeamLaunchPlan, TeamGithubScope } from "@/types/agentTeams";

type Check = { status: "ready" | "blocked" | "unknown"; code: string };
type Preflight = { status: "ready" | "blocked" | "unknown"; checked_at: string; checks: Record<string, Check> };
type Draft = {
  owner: string; repo: string; path: string; dispatch: string; design: string; baseRef: string;
  authMode: "token" | "github_app"; teamMode: "existing" | "new"; teamId: number | "";
  teamName: string; leaderName: string; workerNames: string; provider: string; areaLabels: string; expertise: string;
};
type Recovery = { kind: "team" | "scope"; candidates: Array<{ label: string; id: number }> } | null;
const initial: Draft = {
  owner: "", repo: "", path: "", dispatch: "claude-deck-ready", design: "claude-deck-design", baseRef: "origin/HEAD",
  authMode: "token", teamMode: "new", teamId: "", teamName: "", leaderName: "Leader", workerNames: "Worker",
  provider: "codex-cli", areaLabels: "", expertise: "",
};
const labelClass = "block text-sm font-medium";
const inputClass = "mt-1 w-full rounded-md border bg-background px-3 py-2";
const panelClass = "space-y-4 rounded-lg border bg-card p-4";
const overlapWarning = "This can dispatch the same issue more than once";

function normalized(value: Draft) {
  return JSON.stringify({
    owner: value.owner.trim().toLowerCase(), repo: value.repo.trim().toLowerCase(), path: value.path.trim(),
    dispatch: value.dispatch.trim(), design: value.design.trim(), baseRef: value.baseRef.trim(), authMode: value.authMode,
  });
}

export function RepositorySetupPage() {
  const [draft, setDraft] = useState<Draft>(initial);
  const [step, setStep] = useState(0);
  const [preflight, setPreflight] = useState<{ key: string; value: Preflight } | null>(null);
  const [presets, setPresets] = useState<AgentTeamPreset[]>([]);
  const [scopes, setScopes] = useState<TeamGithubScope[]>([]);
  const [team, setTeam] = useState<AgentTeamPreset | null>(null);
  const [scope, setScope] = useState<TeamGithubScope | null>(null);
  const [recovery, setRecovery] = useState<Recovery>(null);
  const [launchPlan, setLaunchPlan] = useState<AgentTeamLaunchPlan | null>(null);
  const [launchUncertain, setLaunchUncertain] = useState(false);
  const [launchSlots, setLaunchSlots] = useState<number[]>([]);
  const [activationSnapshot, setActivationSnapshot] = useState<string | null>(null);
  const [activationScopes, setActivationScopes] = useState<TeamGithubScope[]>([]);
  const [overlapScopeIds, setOverlapScopeIds] = useState<number[]>([]);
  const [overlapAck, setOverlapAck] = useState(false);
  const [teamActivationAck, setTeamActivationAck] = useState(false);
  const [confirmSave, setConfirmSave] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const token = getOperatorToken();
  const inputKey = useMemo(() => normalized(draft), [draft]);
  const currentPreflight = preflight?.key === inputKey ? preflight.value : null;
  const currentKey = useRef(inputKey);
  currentKey.current = inputKey;

  async function refreshConfiguration() {
    const nextPresets = (await fetchAgentTeamPresets()).presets;
    const nextScopes = (await Promise.all(nextPresets.map((item) => fetchTeamGithubScopes(item.id)))).flatMap((list) => list.scopes);
    setPresets(nextPresets);
    setScopes(nextScopes);
    return { presets: nextPresets, scopes: nextScopes };
  }

  useEffect(() => {
    void refreshConfiguration().catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "Could not load teams."));
  }, []);

  const update = (patch: Partial<Draft>) => {
    currentKey.current = normalized({ ...draft, ...patch });
    setDraft((current) => ({ ...current, ...patch }));
    setLaunchPlan(null);
    setActivationSnapshot(null);
    setOverlapScopeIds([]);
    setOverlapAck(false);
  };
  const matchingOverlap = useMemo(() => scopes.filter((item) =>
    item.enabled && item.repo_owner.toLowerCase() === draft.owner.trim().toLowerCase() &&
    item.repo_name.toLowerCase() === draft.repo.trim().toLowerCase() && item.dispatch_label === draft.dispatch.trim()
  ), [scopes, draft.owner, draft.repo, draft.dispatch]);

  async function checkPrerequisites() {
    setBusy(true); setError("");
    const checkedKey = inputKey;
    try {
      const value = await apiClient<Preflight>("factory/setup-preflight", {
        method: "POST", headers: { "X-Deck-Operator-Token": getOperatorToken() ?? "" },
        body: JSON.stringify({ repo_owner: draft.owner.trim(), repo_name: draft.repo.trim(), repo_path: draft.path.trim(), dispatch_label: draft.dispatch.trim(), design_label: draft.design.trim(), dispatch_auth_mode: draft.authMode, base_ref: draft.baseRef.trim() }),
      });
      if (currentKey.current !== checkedKey) return;
      setPreflight({ key: checkedKey, value });
      if (value.status === "ready") setStep((current) => current === 0 ? 1 : current);
    } catch (cause) {
      if (currentKey.current === checkedKey) setError(cause instanceof ApiHttpError ? cause.message : cause instanceof Error ? cause.message : "The check failed.");
    } finally { setBusy(false); }
  }

  async function reconcileUnknown(kind: "team" | "scope", teamId?: number) {
    setBusy(true); setError("");
    try {
      const fresh = await refreshConfiguration();
      if (kind === "team") {
        const names = [draft.leaderName.trim(), ...draft.workerNames.split("\n").map((name) => name.trim()).filter(Boolean)];
        const candidates = fresh.presets.filter((item) => item.name === draft.teamName.trim() &&
          item.slots.length === names.length && names.every((name) => item.slots.some((slot) => slot.display_name === name)));
        setRecovery({ kind, candidates: candidates.map((item) => ({ label: `${item.name} (#${item.id})`, id: item.id })) });
      } else {
        const candidates = fresh.scopes.filter((item) => item.preset_id === (teamId ?? team?.id) && item.repo_owner.toLowerCase() === draft.owner.trim().toLowerCase() &&
          item.repo_name.toLowerCase() === draft.repo.trim().toLowerCase() && item.repo_path === draft.path.trim() &&
          item.dispatch_label === draft.dispatch.trim() && item.design_label === draft.design.trim());
        setRecovery({ kind, candidates: candidates.map((item) => ({ label: `Scope #${item.id} (${item.enabled ? "enabled" : "disabled"})`, id: item.id })) });
      }
      setError("The create response was uncertain. Review fresh matching records and select one, or stop. Do not repeat the create request.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not reconcile the uncertain create result."); }
    finally { setBusy(false); }
  }

  async function saveSetup() {
    if (!token) { setError("Enter the operator token in Agent Teams before saving setup."); return; }
    if (!confirmSave || (draft.teamMode === "existing" && !draft.teamId)) return;
    setBusy(true); setError(""); setRecovery(null);
    try {
      const fresh = await refreshConfiguration();
      let selected = draft.teamMode === "existing" ? fresh.presets.find((item) => item.id === draft.teamId) ?? null : team ? fresh.presets.find((item) => item.id === team!.id) ?? team : null;
      if (draft.teamMode === "new" && !selected) {
        const names = draft.workerNames.split("\n").map((name) => name.trim()).filter(Boolean);
        const allNames = [draft.leaderName.trim(), ...names];
        if (allNames.some((name) => !name) || new Set(allNames).size !== allNames.length) {
          throw new Error("Enter unique, non-empty names for the Leader and each worker.");
        }
        const input: AgentTeamPresetInput = {
          name: draft.teamName.trim(), autonomy_enabled: false,
          slots: [
            { display_name: draft.leaderName.trim(), provider: draft.provider, repo_path: draft.path.trim(), role: "Leader", area_labels: draft.areaLabels.split(",").map((item) => item.trim()).filter(Boolean), expertise: draft.expertise.trim() || null, enabled: true },
            ...names.map((name) => ({ display_name: name, provider: draft.provider, repo_path: draft.path.trim(), role: "Worker", area_labels: draft.areaLabels.split(",").map((item) => item.trim()).filter(Boolean), expertise: draft.expertise.trim() || null, enabled: true })),
          ],
        };
        try { selected = await createAgentTeamPreset(input, token); }
        catch (cause) { await reconcileUnknown("team"); throw cause; }
        setTeam(selected);
      }
      if (!selected) throw new Error("Select an existing team or create a new team.");
      if (draft.teamMode === "new") {
        const leaderSlot = selected.slots.find((slot) => slot.display_name === draft.leaderName.trim());
        if (!leaderSlot) throw new Error("The saved team has no matching Leader slot. Review the team before setup continues.");
        if (selected.leader_slot_id !== leaderSlot.id) {
          selected = await updateAgentTeamLeader(selected.id, { leader_slot_id: leaderSlot.id, expected_leader_slot_id: selected.leader_slot_id ?? null, expected_updated_at: selected.updated_at, reason: "Set the explicit Leader during guided repository setup." }, token);
        }
      } else if (!selected.leader_slot_id) {
        throw new Error("The existing team has no explicit Leader assignment. Keep its settings unchanged and resolve its authority separately.");
      }
      setTeam(selected);
      const sameScope = fresh.scopes.find((item) => item.preset_id === selected!.id && item.repo_owner.toLowerCase() === draft.owner.trim().toLowerCase() &&
        item.repo_name.toLowerCase() === draft.repo.trim().toLowerCase() && item.repo_path === draft.path.trim() && item.dispatch_label === draft.dispatch.trim() && item.design_label === draft.design.trim());
      let savedScope = sameScope ?? null;
      if (!savedScope) {
        try {
          savedScope = await createTeamGithubScope(selected.id, {
            repo_owner: draft.owner.trim(), repo_name: draft.repo.trim(), repo_path: draft.path.trim(),
            dispatch_label: draft.dispatch.trim(), design_label: draft.design.trim(), merge_policy: "human",
            max_approval_rounds: 3, max_concurrent_dispatched: 1, max_verification_retries: 1,
            max_auto_merges_per_day: 0, base_ref: draft.baseRef.trim(), github_auth_mode: draft.authMode === "github_app" ? "app" : "ambient",
            builds_out_of_tree: false, max_build_parallelism: 1, enabled: false,
          }, token);
        } catch (cause) { await reconcileUnknown("scope", selected.id); throw cause; }
      }
      setScope(savedScope);
      await refreshConfiguration();
      setStep(5);
    } catch (cause) {
      setError((existing) => existing || (cause instanceof Error ? cause.message : "Setup could not be saved. The draft remains available here."));
    } finally { setBusy(false); }
  }

  async function resolveCandidate(id: number) {
    setBusy(true); setError("");
    try {
      const fresh = await refreshConfiguration();
      if (recovery?.kind === "team") {
        const recovered = fresh.presets.find((item) => item.id === id);
        if (!recovered) throw new Error("The selected team is no longer present. Refresh and review the records again.");
        setTeam(recovered); setRecovery(null); setError("Team recovered. Review the saved team, then save the repository scope as a separate step.");
      } else {
        const recovered = fresh.scopes.find((item) => item.id === id);
        if (!recovered) throw new Error("The selected scope is no longer present. Refresh and review the records again.");
        setScope(recovered); setRecovery(null); setStep(5);
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not recover the selected record."); }
    finally { setBusy(false); }
  }

  async function reviewActivation() {
    if (!scope || !team || currentPreflight?.status !== "ready") { setError("Run a current ready access and label check before activation."); return; }
    setBusy(true); setError("");
    try {
      const fresh = await refreshConfiguration();
      const freshTeam = fresh.presets.find((item) => item.id === team.id);
      if (!freshTeam) throw new Error("The selected team is no longer available.");
      setTeam(freshTeam);
      const enabled = fresh.scopes.filter((item) => item.enabled && item.repo_owner.toLowerCase() === scope.repo_owner.toLowerCase() && item.repo_name.toLowerCase() === scope.repo_name.toLowerCase() && item.dispatch_label === scope.dispatch_label);
      const siblings = !freshTeam.autonomy_enabled ? fresh.scopes.filter((item) => item.preset_id === freshTeam.id && item.enabled) : [];
      const visible = [...new Map([...enabled, ...siblings].map((item) => [item.id, item])).values()];
      setActivationScopes(visible);
      setOverlapScopeIds(enabled.filter((item) => item.id !== scope.id).map((item) => item.id));
      setActivationSnapshot(JSON.stringify({ autonomy: freshTeam.autonomy_enabled, scopeId: scope.id, visible: visible.map((item) => [item.id, item.preset_id, item.enabled, item.design_label]).sort((a, b) => Number(a[0]) - Number(b[0])) }));
      setOverlapAck(false); setTeamActivationAck(false);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not refresh activation checks."); }
    finally { setBusy(false); }
  }

  async function activateScope() {
    if (!scope || !team || !token || !activationSnapshot || currentPreflight?.status !== "ready") return;
    setBusy(true); setError("");
    try {
      const checkedKey = inputKey;
      const check = await apiClient<Preflight>("factory/setup-preflight", {
        method: "POST", headers: { "X-Deck-Operator-Token": token },
        body: JSON.stringify({ repo_owner: draft.owner.trim(), repo_name: draft.repo.trim(), repo_path: draft.path.trim(), dispatch_label: draft.dispatch.trim(), design_label: draft.design.trim(), dispatch_auth_mode: draft.authMode, base_ref: draft.baseRef.trim() }),
      });
      if (checkedKey !== currentKey.current || check.status !== "ready") { setPreflight({ key: checkedKey, value: check }); setActivationSnapshot(null); setError("Inputs changed or current checks are not ready. Review the new result before activation."); return; }
      const fresh = await refreshConfiguration();
      const freshTeam = fresh.presets.find((item) => item.id === team.id);
      const freshScope = fresh.scopes.find((item) => item.id === scope.id);
      if (!freshTeam || !freshScope) throw new Error("The selected team or scope is no longer available.");
      if (freshScope.enabled) {
        setTeam(freshTeam); setScope(freshScope); setActivationSnapshot(null);
        setError("Fresh reads confirm that this scope is already enabled. No activation request was repeated.");
        return;
      }
      const conflicts = fresh.scopes.filter((item) => item.enabled && item.repo_owner.toLowerCase() === freshScope.repo_owner.toLowerCase() && item.repo_name.toLowerCase() === freshScope.repo_name.toLowerCase() && item.dispatch_label === freshScope.dispatch_label);
      const siblings = !freshTeam.autonomy_enabled ? fresh.scopes.filter((item) => item.preset_id === freshTeam.id && item.enabled) : [];
      const visible = [...new Map([...conflicts, ...siblings].map((item) => [item.id, item])).values()];
      const snapshot = JSON.stringify({ autonomy: freshTeam.autonomy_enabled, scopeId: scope.id, visible: visible.map((item) => [item.id, item.preset_id, item.enabled, item.design_label]).sort((a, b) => Number(a[0]) - Number(b[0])) });
      if (snapshot !== activationSnapshot) {
        setActivationScopes(visible);
        setOverlapScopeIds(conflicts.filter((item) => item.id !== scope.id).map((item) => item.id));
        setActivationSnapshot(snapshot); setOverlapAck(false); setTeamActivationAck(false);
        throw new Error("The live overlap or activation state changed. Review the refreshed list and confirm again.");
      }
      const conflictsWithOtherScope = conflicts.some((item) => item.id !== freshScope.id);
      if (conflictsWithOtherScope && !overlapAck) throw new Error("Review the listed overlap and acknowledge repeated dispatch before activation.");
      if (!freshTeam.autonomy_enabled && !teamActivationAck) throw new Error("Confirm team activation and review every enabled sibling scope first.");
      if (!freshTeam.autonomy_enabled) {
        const updatedTeam = await updateAgentTeamPreset(freshTeam.id, { autonomy_enabled: true }, token);
        setTeam(updatedTeam);
      }
      const updatedScope = await updateTeamGithubScope(freshScope.id, { enabled: true }, token);
      setScope(updatedScope); await refreshConfiguration();
      setActivationSnapshot(null); setError("Scope activated after current access, label, and overlap checks.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Activation could not be completed."); }
    finally { setBusy(false); }
  }

  async function reviewLaunch() {
    if (!team || !token || launchSlots.length === 0) return;
    setBusy(true); setError("");
    try { setLaunchPlan(await planAgentTeamLaunch(team.id, { slot_ids: launchSlots, reuse_existing: true }, token)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not build a current launch plan."); }
    finally { setBusy(false); }
  }

  async function launchSelected() {
    if (!team || !launchPlan || !token) return;
    setBusy(true); setError("");
    try {
      const result = await launchAgentTeam(team.id, { slot_ids: launchSlots, reuse_existing: true, confirm_plan_hash: launchPlan.plan_hash }, token);
      setError(`Launch completed with status: ${result.status}. Review its result before a separate activation decision.`);
      setLaunchPlan(null);
      setLaunchUncertain(false);
    } catch (cause) { setError(`Launch outcome is uncertain. Do not launch again until an operator reconciles the team sessions. ${cause instanceof Error ? cause.message : "No safe result was returned."}`); setLaunchPlan(null); setLaunchUncertain(true); }
    finally { setBusy(false); }
  }

  return <section className="mx-auto max-w-3xl space-y-5">
    <div><h2 className="text-2xl font-semibold">Set up a repository</h2><p className="text-muted-foreground">Review the repository, team, routing, policy, save, launch, and activation as separate steps.</p></div>
    <ol className="flex flex-wrap gap-2 text-sm" aria-label="Setup steps">{["Repository", "Team and roles", "Routing", "Policy", "Review", "Saved setup"].map((name, index) => <li key={name} aria-current={step === index ? "step" : undefined} className={`rounded border px-3 py-1 ${step === index ? "bg-accent font-semibold" : ""}`}>{index + 1}. {name}</li>)}</ol>
    {error && <p role="alert" className="rounded border border-destructive p-3 text-sm">{error}</p>}
    {recovery && <div className={panelClass}><h3 className="font-semibold">Reconcile uncertain create</h3><p>Fresh reads found {recovery.candidates.length} matching record(s). Select one record to continue. Do not repeat the create request.</p>{recovery.candidates.map((item) => <Button key={item.id} variant="outline" disabled={busy} onClick={() => void resolveCandidate(item.id)}>Use {item.label}</Button>)}</div>}
    {step === 0 && <div className={panelClass}>
      <label className={labelClass}>Repository owner<input className={inputClass} value={draft.owner} onChange={(e) => update({ owner: e.target.value })} /></label>
      <label className={labelClass}>Repository name<input className={inputClass} value={draft.repo} onChange={(e) => update({ repo: e.target.value })} /></label>
      <label className={labelClass}>Primary checkout path<input className={inputClass} value={draft.path} onChange={(e) => update({ path: e.target.value })} /></label>
      <label className={labelClass}>Base branch<input className={inputClass} value={draft.baseRef} onChange={(e) => update({ baseRef: e.target.value })} /><span className="text-xs text-muted-foreground">Use origin/HEAD or origin/&lt;branch&gt;.</span></label>
      <label className={labelClass}>Dispatch label<input className={inputClass} value={draft.dispatch} onChange={(e) => update({ dispatch: e.target.value })} /></label>
      <label className={labelClass}>Design label<input className={inputClass} value={draft.design} onChange={(e) => update({ design: e.target.value })} /></label>
      <label className={labelClass}>Dispatch authentication<select className={inputClass} value={draft.authMode} onChange={(e) => update({ authMode: e.target.value as Draft["authMode"] })}><option value="token">GitHub token</option><option value="github_app">GitHub App</option></select></label>
      <p className="text-sm">The check reads checkout identity, repository access, labels, base branch, and selected authentication presence. It makes no changes.</p>
      <Button disabled={busy || !draft.owner || !draft.repo || !draft.path || !draft.dispatch || !draft.design || !draft.baseRef} onClick={() => void checkPrerequisites()}>{busy ? "Checking…" : "Check access and labels"}</Button>
      {preflight && <div className="rounded border p-3" aria-live="polite"><p>{currentPreflight ? "Current result" : "Stale result"}: {preflight.value.status}; checked {new Date(preflight.value.checked_at).toLocaleString()}.</p>{Object.entries(preflight.value.checks).map(([name, check]) => <p key={name}>{name}: {check.status} ({check.code})</p>)}{preflight.value.status !== "ready" && <p>Remedy: correct the selected value or complete the named host setup step, then run this check again.</p>}</div>}
      <Button variant="outline" disabled={!currentPreflight || currentPreflight.status !== "ready"} onClick={() => setStep(1)}>Continue</Button>
    </div>}
    {step === 1 && <div className={panelClass}><label className={labelClass}>Team setup<select className={inputClass} value={draft.teamMode} onChange={(e) => update({ teamMode: e.target.value as Draft["teamMode"] })}><option value="new">Create an inactive team</option><option value="existing">Use an existing team</option></select></label>
      {draft.teamMode === "existing" ? <label className={labelClass}>Team<select className={inputClass} value={draft.teamId} onChange={(e) => update({ teamId: Number(e.target.value) || "" })}><option value="">Select a team</option>{presets.map((item) => <option key={item.id} value={item.id}>{item.name} ({item.autonomy_enabled ? "active" : "paused"})</option>)}</select></label> : <><label className={labelClass}>Team name<input className={inputClass} value={draft.teamName} onChange={(e) => update({ teamName: e.target.value })} /></label><label className={labelClass}>Explicit Leader slot<input className={inputClass} value={draft.leaderName} onChange={(e) => update({ leaderName: e.target.value })} /></label><label className={labelClass}>Worker slots, one name per line<textarea className={inputClass} value={draft.workerNames} onChange={(e) => update({ workerNames: e.target.value })} /></label><label className={labelClass}>Worker and Leader provider<select className={inputClass} value={draft.provider} onChange={(e) => update({ provider: e.target.value })}>{["claude-code", "codex-cli", "copilot-cli", "opencode-cli"].map((item) => <option key={item}>{item}</option>)}</select></label></>}
      <p className="text-sm">New teams remain inactive. Existing roster, Leader, policy, and activation stay unchanged.</p><Button disabled={draft.teamMode === "existing" && !draft.teamId} onClick={() => setStep(2)}>Continue</Button></div>}
    {step === 2 && <div className={panelClass}><p>Routing uses the selected dispatch and design labels.</p>{draft.teamMode === "new" ? <><label className={labelClass}>Area labels, comma separated<input className={inputClass} value={draft.areaLabels} onChange={(e) => update({ areaLabels: e.target.value })} /></label><label className={labelClass}>Expertise<input className={inputClass} value={draft.expertise} onChange={(e) => update({ expertise: e.target.value })} /></label></> : <p>Existing team routing stays unchanged.</p>}<p>Potential enabled overlaps: {matchingOverlap.map((item) => `team ${item.preset_id}/scope ${item.id}`).join(", ") || "none found in loaded data"}.</p><Button onClick={() => setStep(3)}>Continue</Button></div>}
    {step === 3 && <div className={panelClass}><h3 className="font-semibold">Policy</h3><p>Merge policy: human approval.</p><p>New scope limits: concurrency 1; verification retries 1; automatic merges 0.</p><p>Base branch: {draft.baseRef}. Scope is saved disabled, even when checks have gaps.</p><p>Existing team settings remain unchanged. Launch and activation require separate choices.</p><Button onClick={() => setStep(4)}>Review setup</Button></div>}
    {step === 4 && <div className={panelClass}><h3 className="font-semibold">Review</h3><p>Repository: {draft.owner}/{draft.repo}</p><p>Checkout: {draft.path}</p><p>Base: {draft.baseRef}</p><p>Labels: {draft.dispatch} / {draft.design}</p><p>Authentication: {draft.authMode}; credentials are not stored in this draft.</p><p>Preflight: {currentPreflight?.status ?? "not checked or stale"}. Saving remains disabled and does not need ready checks.</p><p>Team: {draft.teamMode === "existing" ? presets.find((item) => item.id === draft.teamId)?.name ?? "Select a team" : draft.teamName || "New team"}; Leader: {draft.teamMode === "new" ? draft.leaderName : "preserved"}; worker slots: {draft.teamMode === "new" ? draft.workerNames.split("\n").filter((name) => name.trim()).length : "preserved"}.</p><p>Potential overlap: {matchingOverlap.map((item) => `team ${item.preset_id}/scope ${item.id}`).join(", ") || "none found"}.</p><label className="flex gap-2 text-sm"><input type="checkbox" checked={confirmSave} onChange={(e) => setConfirmSave(e.target.checked)} />Save configuration only. Keep launch, team activation, scope activation, and merge decisions separate.</label><div className="flex flex-wrap gap-2"><Button disabled={busy || !confirmSave || (draft.teamMode === "existing" && !draft.teamId)} onClick={() => void saveSetup()}>{busy ? "Saving…" : "Save configuration"}</Button><Link className="self-center underline" to="/teams">Manage teams</Link></div></div>}
    {step === 5 && team && scope && <div className={panelClass}><h3 className="font-semibold">Saved configuration</h3><p>Team {team.name} (#{team.id}) is {team.autonomy_enabled ? "active" : "paused"}. Scope #{scope.id} is {scope.enabled ? "enabled" : "disabled"}.</p><p>Saving did not launch workers or activate this scope.</p>
      <section className="space-y-2 border-t pt-3"><h4 className="font-semibold">Separate worker launch</h4>{team.slots.filter((slot) => slot.enabled && slot.id !== team.leader_slot_id).map((slot) => <label key={slot.id} className="flex gap-2 text-sm"><input type="checkbox" checked={launchSlots.includes(slot.id)} onChange={(event) => setLaunchSlots((current) => event.target.checked ? [...current, slot.id] : current.filter((id) => id !== slot.id))} />{slot.display_name} ({slot.provider})</label>)}<Button disabled={busy || launchUncertain || launchSlots.length === 0} onClick={() => void reviewLaunch()}>Review current launch plan</Button>{launchUncertain && <p role="status">Launch outcome needs operator reconciliation. This flow will not repeat the launch request.</p>}{launchPlan && <div className="rounded border p-3"><p>Plan {launchPlan.can_launch ? "ready" : "blocked"}: spawn {launchPlan.spawn_count}, reuse {launchPlan.reuse_count}, blocked {launchPlan.blocked_count}.</p>{launchPlan.items.map((item) => <p key={item.slot_id}>{item.slot_name}: {item.action}{item.reasons.length ? ` (${item.reasons.join(", ")})` : ""}</p>)}<Button disabled={busy || launchUncertain || !launchPlan.can_launch} onClick={() => void launchSelected()}>Launch reviewed slots</Button></div>}</section>
      <section className="space-y-2 border-t pt-3"><h4 className="font-semibold">Separate activation</h4><p>Run a current ready access and label check before activation.</p><Button disabled={busy} onClick={() => void checkPrerequisites()}>Refresh access and label check</Button><Button disabled={busy || currentPreflight?.status !== "ready"} onClick={() => void reviewActivation()}>Review current activation and overlap</Button>{activationSnapshot && <div className="space-y-2 rounded border p-3"><p>Scopes affected or overlapping: {activationScopes.map((item) => `team ${item.preset_id}/scope ${item.id}`).join(", ") || "none"}.</p>{overlapScopeIds.length > 0 && <label className="flex gap-2 text-sm"><input type="checkbox" checked={overlapAck} onChange={(e) => setOverlapAck(e.target.checked)} />{overlapWarning}</label>}{!team.autonomy_enabled && <label className="flex gap-2 text-sm"><input type="checkbox" checked={teamActivationAck} onChange={(e) => setTeamActivationAck(e.target.checked)} />Activate team automation. This also resumes each listed enabled sibling scope.</label>}<Button disabled={busy || (overlapScopeIds.length > 0 && !overlapAck) || (!team.autonomy_enabled && !teamActivationAck)} onClick={() => void activateScope()}>Enable this scope</Button></div>}</section>
    </div>}
    {step > 0 && step < 5 && <Button variant="outline" onClick={() => setStep((value) => Math.max(0, value - 1))}>Back</Button>}
  </section>;
}
