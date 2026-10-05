import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ApiHttpError, apiClient } from "@/lib/api";
import {
  createAgentTeamPreset,
  createTeamGithubScope,
  fetchAgentTeamPresets,
  fetchTeamGithubScopes,
  updateAgentTeamLeader,
} from "@/features/agent-teams/api";
import { getOperatorToken } from "@/features/agent-teams/operatorAuth";
import type { AgentTeamPreset, AgentTeamPresetInput, TeamGithubScope } from "@/types/agentTeams";

type Check = { status: "ready" | "blocked" | "unknown"; code: string };
type Preflight = { status: "ready" | "blocked" | "unknown"; checked_at: string; checks: Record<string, Check> };
type Draft = {
  owner: string; repo: string; path: string; dispatch: string; design: string;
  authMode: "token" | "github_app"; teamMode: "existing" | "new"; teamId: number | "";
  teamName: string; leaderName: string; provider: string; areaLabels: string;
  expertise: string;
};
const initial: Draft = {
  owner: "", repo: "", path: "", dispatch: "claude-deck-ready", design: "claude-deck-design",
  authMode: "token", teamMode: "new", teamId: "", teamName: "", leaderName: "Leader",
  provider: "codex-cli", areaLabels: "", expertise: "",
};
const labelClass = "block text-sm font-medium";
const inputClass = "mt-1 w-full rounded-md border bg-background px-3 py-2";
const panelClass = "space-y-4 rounded-lg border bg-card p-4";

export function RepositorySetupPage() {
  const navigate = useNavigate();
  const [draft, setDraft] = useState<Draft>(initial);
  const [step, setStep] = useState(0);
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [presets, setPresets] = useState<AgentTeamPreset[]>([]);
  const [scopes, setScopes] = useState<TeamGithubScope[]>([]);
  const [createdTeam, setCreatedTeam] = useState<AgentTeamPreset | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [overlapAck, setOverlapAck] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const token = getOperatorToken();

  useEffect(() => {
    fetchAgentTeamPresets().then(async (result) => {
      setPresets(result.presets);
      const lists = await Promise.all(result.presets.map((preset) => fetchTeamGithubScopes(preset.id)));
      setScopes(lists.flatMap((list) => list.scopes));
    }).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "Could not load teams."));
  }, []);

  const matching = useMemo(() => scopes.filter((scope) =>
    scope.repo_owner.toLowerCase() === draft.owner.trim().toLowerCase() &&
    scope.repo_name.toLowerCase() === draft.repo.trim().toLowerCase() &&
    scope.dispatch_label === draft.dispatch.trim()
  ), [scopes, draft.owner, draft.repo, draft.dispatch]);
  const overlap = matching.some((scope) => scope.enabled);
  const update = (patch: Partial<Draft>) => setDraft((current) => ({ ...current, ...patch }));

  async function checkPrerequisites() {
    setBusy(true); setError(""); setPreflight(null);
    try {
      const result = await apiClient<Preflight>("factory/setup-preflight", {
        method: "POST", headers: { "X-Deck-Operator-Token": getOperatorToken() ?? "" },
        body: JSON.stringify({ repo_owner: draft.owner.trim(), repo_name: draft.repo.trim(), repo_path: draft.path.trim(), dispatch_label: draft.dispatch.trim(), design_label: draft.design.trim(), dispatch_auth_mode: draft.authMode }),
      });
      setPreflight(result);
      if (result.status === "ready") setStep(1);
    } catch (cause) {
      setError(cause instanceof ApiHttpError ? cause.message : cause instanceof Error ? cause.message : "The check failed.");
    } finally { setBusy(false); }
  }

  async function saveSetup() {
    if (!token) { setError("Enter the operator token in Agent Teams before saving setup."); return; }
    if (!confirm || (overlap && !overlapAck)) return;
    setBusy(true); setError("");
    try {
      const freshPresets = (await fetchAgentTeamPresets()).presets;
      const freshScopes = (await Promise.all(freshPresets.map((preset) => fetchTeamGithubScopes(preset.id)))).flatMap((list) => list.scopes);
      setPresets(freshPresets); setScopes(freshScopes);
      let team = draft.teamMode === "existing"
        ? freshPresets.find((item) => item.id === draft.teamId)
        : createdTeam ? freshPresets.find((item) => item.id === createdTeam!.id) ?? createdTeam : null;
      if (!team && draft.teamMode === "new") {
        const input: AgentTeamPresetInput = { name: draft.teamName.trim(), slots: [{ display_name: draft.leaderName.trim(), provider: draft.provider, repo_path: draft.path.trim(), role: "Leader", area_labels: draft.areaLabels.split(",").map((item) => item.trim()).filter(Boolean), expertise: draft.expertise.trim() || null, enabled: true }] };
        team = await createAgentTeamPreset(input, token);
        setCreatedTeam(team);
      }
      if (!team) throw new Error("Select an existing team or create a new team.");
      if (draft.teamMode === "new" && !team.leader_slot_id && team.slots[0]) {
        team = await updateAgentTeamLeader(team.id, { leader_slot_id: team.slots[0].id, expected_leader_slot_id: null, expected_updated_at: team.updated_at, reason: "Set the Leader during guided repository setup." }, token);
        setCreatedTeam(team);
      }
      const sameScope = freshScopes.find((scope) => scope.preset_id === team!.id &&
        scope.repo_owner.toLowerCase() === draft.owner.trim().toLowerCase() &&
        scope.repo_name.toLowerCase() === draft.repo.trim().toLowerCase() &&
        scope.repo_path === draft.path.trim() && scope.dispatch_label === draft.dispatch.trim() &&
        scope.design_label === draft.design.trim());
      if (!sameScope) {
        const scope = await createTeamGithubScope(team.id, {
          repo_owner: draft.owner.trim(), repo_name: draft.repo.trim(), repo_path: draft.path.trim(),
          dispatch_label: draft.dispatch.trim(), design_label: draft.design.trim(), merge_policy: "human",
          max_approval_rounds: 3, max_concurrent_dispatched: 1, max_verification_retries: 1,
          max_auto_merges_per_day: 0, base_ref: "feature/software-delivery-product-reposition",
          builds_out_of_tree: false, max_build_parallelism: 1, enabled: false,
        }, token);
        navigate(`/repositories/${scope.id}`);
      } else {
        navigate(`/repositories/${sameScope.id}`);
      }
    } catch (cause) {
      if (createdTeam) {
        try {
          const current = (await fetchAgentTeamPresets()).presets.find((item) => item.id === createdTeam.id);
          if (current) setCreatedTeam(current);
        } catch { /* Keep the local team record so the user can retry safely. */ }
      }
      setError(cause instanceof Error ? cause.message : "Setup could not be saved. The draft remains available here.");
    } finally { setBusy(false); }
  }

  return <section className="mx-auto max-w-3xl space-y-5">
    <div><h2 className="text-2xl font-semibold">Set up a repository</h2><p className="text-muted-foreground">Check prerequisites, choose a team, review the policy, then save a disabled scope.</p></div>
    <ol className="flex flex-wrap gap-2 text-sm" aria-label="Setup steps">{["Repository check", "Team", "Routing", "Policy", "Review"].map((name, index) => <li key={name} aria-current={step === index ? "step" : undefined} className={`rounded border px-3 py-1 ${step === index ? "bg-accent font-semibold" : ""}`}>{index + 1}. {name}</li>)}</ol>
    {error && <p role="alert" className="rounded border border-destructive p-3 text-sm">{error}</p>}
    {step === 0 && <div className={panelClass}>
      <label className={labelClass}>Repository owner<input className={inputClass} value={draft.owner} onChange={(e) => update({ owner: e.target.value })} /></label>
      <label className={labelClass}>Repository name<input className={inputClass} value={draft.repo} onChange={(e) => update({ repo: e.target.value })} /></label>
      <label className={labelClass}>Local repository path<input className={inputClass} value={draft.path} onChange={(e) => update({ path: e.target.value })} /></label>
      <label className={labelClass}>Dispatch label<input className={inputClass} value={draft.dispatch} onChange={(e) => update({ dispatch: e.target.value })} /></label>
      <label className={labelClass}>Design label<input className={inputClass} value={draft.design} onChange={(e) => update({ design: e.target.value })} /></label>
      <label className={labelClass}>Polling authentication<select className={inputClass} value={draft.authMode} onChange={(e) => update({ authMode: e.target.value as Draft["authMode"] })}><option value="token">GitHub token</option><option value="github_app">GitHub App</option></select></label>
      <p className="text-sm">This check reads repository access and labels. It does not create or change records.</p>
      <Button disabled={busy || !draft.owner || !draft.repo || !draft.path || !draft.dispatch || !draft.design} onClick={() => void checkPrerequisites()}>{busy ? "Checking…" : "Check access and labels"}</Button>
      {preflight && <div className="rounded border p-3" aria-live="polite"><p>Result: {preflight.status}; checked {new Date(preflight.checked_at).toLocaleString()}.</p>{Object.entries(preflight.checks).map(([name, check]) => <p key={name}>{name}: {check.status} ({check.code})</p>)}</div>}
    </div>}
    {step === 1 && <div className={panelClass}><label className={labelClass}>Team setup<select className={inputClass} value={draft.teamMode} onChange={(e) => update({ teamMode: e.target.value as Draft["teamMode"] })}><option value="new">Create a team</option><option value="existing">Use an existing team</option></select></label>
      {draft.teamMode === "existing" ? <label className={labelClass}>Team<select className={inputClass} value={draft.teamId} onChange={(e) => update({ teamId: Number(e.target.value) || "" })}><option value="">Select a team</option>{presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}</select></label> : <><label className={labelClass}>Team name<input className={inputClass} value={draft.teamName} onChange={(e) => update({ teamName: e.target.value })} /></label><label className={labelClass}>Initial Leader slot name<input className={inputClass} value={draft.leaderName} onChange={(e) => update({ leaderName: e.target.value })} /></label><p className="text-sm">The new team remains inactive. Existing team assignment and policy remain unchanged.</p></>}
      <Button disabled={draft.teamMode === "existing" && !draft.teamId} onClick={() => setStep(2)}>Continue</Button></div>}
    {step === 2 && <div className={panelClass}><p>Routing uses the dispatch and design labels checked in step 1.</p>{draft.teamMode === "new" ? <><label className={labelClass}>Provider<select className={inputClass} value={draft.provider} onChange={(e) => update({ provider: e.target.value })}>{["claude-code", "codex-cli", "copilot-cli", "opencode-cli", "pi-cli"].map((item) => <option key={item}>{item}</option>)}</select></label><label className={labelClass}>Area labels, comma separated<input className={inputClass} value={draft.areaLabels} onChange={(e) => update({ areaLabels: e.target.value })} /></label><label className={labelClass}>Expertise<input className={inputClass} value={draft.expertise} onChange={(e) => update({ expertise: e.target.value })} /></label></> : <p>Existing team routing stays unchanged.</p>}<Button onClick={() => setStep(3)}>Continue</Button></div>}
    {step === 3 && <div className={panelClass}><h3 className="font-semibold">Separate policy gates</h3><p>Merge policy: human approval.</p><p>New scope concurrency: 1; verification retries: 1; automatic merges: 0.</p><p>Repository scope: disabled after save. Team activation and pilot or promotion decisions remain separate.</p><p>Existing team settings stay unchanged.</p><Button onClick={() => setStep(4)}>Review setup</Button></div>}
    {step === 4 && <div className={panelClass}><h3 className="font-semibold">Review</h3><p>Repository: {draft.owner}/{draft.repo}</p><p>Path: {draft.path}</p><p>Preflight: {preflight?.status ?? "not checked"}. {preflight?.checked_at ? `Checked ${new Date(preflight.checked_at).toLocaleString()}.` : ""}</p><p>Team: {draft.teamMode === "existing" ? presets.find((item) => item.id === draft.teamId)?.name ?? "Select a team" : draft.teamName || "New team"}</p><p>Scope saves disabled with human merge policy and concurrency 1.</p><p>Overlapping enabled scope: {overlap ? "yes" : "no"}.</p>{overlap && <label className="flex gap-2 text-sm"><input type="checkbox" checked={overlapAck} onChange={(e) => setOverlapAck(e.target.checked)} />I understand that an enabled scope already uses this repository and dispatch label.</label>}<label className="flex gap-2 text-sm"><input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />Create or resume this setup. Keep all activation and merge decisions separate.</label><div className="flex flex-wrap gap-2"><Button disabled={busy || !confirm || (overlap && !overlapAck) || (draft.teamMode === "existing" && !draft.teamId)} onClick={() => void saveSetup()}>{busy ? "Saving…" : "Save disabled scope"}</Button><Link className="self-center underline" to="/teams">Manage teams</Link></div></div>}
    {step > 0 && <Button variant="outline" onClick={() => setStep((value) => Math.max(0, value - 1))}>Back</Button>}
  </section>;
}
