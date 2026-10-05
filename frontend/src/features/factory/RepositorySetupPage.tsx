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
import { clearOperatorToken, getOperatorToken, setOperatorToken } from "@/features/agent-teams/operatorAuth";
import { OperatorTokenDialog } from "@/features/agent-teams/AutonomyPanel";
import type { AgentTeamPreset, AgentTeamPresetInput, AgentTeamLaunchPlan, TeamGithubScope } from "@/types/agentTeams";

type Check = { status: "ready" | "blocked" | "unknown"; code: string; remedy: string };
type Preflight = { status: "ready" | "blocked" | "unknown"; observed_at: string; checked_at?: string; checks: Record<string, Check> };
type Draft = {
  owner: string; repo: string; path: string; dispatch: string; design: string; baseRef: string;
  authMode: "token" | "github_app"; teamMode: "existing" | "new"; teamId: number | "";
  teamName: string; leaderName: string; workerNames: string; provider: string;
};
type Recovery = {
  kind: "team" | "scope";
  candidates: Array<{ label: string; id: number }>;
  requestedDraft?: Draft;
  requestedRouting?: Record<string, { areaLabels: string; expertise: string }>;
} | null;
type MailTeam = { members: Array<{ id: number; status: string; team_preset_id?: number | null; team_slot_id?: number | null; sessions: Array<{ team_preset_id?: number | null; team_slot_id?: number | null; mailbox_status: string }> }> };
type ScopeOverlap = { key: string; first: TeamGithubScope; second: TeamGithubScope; active: boolean };
type UncertainLaunch = { slotIds: number[]; planHash: string } | null;
const initial: Draft = {
  owner: "", repo: "", path: "", dispatch: "claude-deck-ready", design: "claude-deck-design", baseRef: "origin/HEAD",
  authMode: "token", teamMode: "new", teamId: "", teamName: "", leaderName: "Leader", workerNames: "Worker",
  provider: "codex-cli",
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

function scopePreflightInput(scope: TeamGithubScope) {
  return {
    repo_owner: scope.repo_owner,
    repo_name: scope.repo_name,
    repo_path: scope.repo_path,
    dispatch_label: scope.dispatch_label,
    design_label: scope.design_label,
    dispatch_auth_mode: scope.github_auth_mode === "app" ? "github_app" : "token",
    base_ref: scope.base_ref,
  };
}

function scopeMatchesDraft(scope: TeamGithubScope, draft: Draft) {
  return scope.repo_owner.toLowerCase() === draft.owner.trim().toLowerCase() &&
    scope.repo_name.toLowerCase() === draft.repo.trim().toLowerCase() &&
    scope.repo_path === draft.path.trim() &&
    scope.dispatch_label === draft.dispatch.trim() &&
    scope.design_label === draft.design.trim() &&
    scope.base_ref === draft.baseRef.trim() &&
    scope.github_auth_mode === (draft.authMode === "github_app" ? "app" : "ambient");
}

function buildActivationSnapshot(scopes: TeamGithubScope[], teams: AgentTeamPreset[], team: AgentTeamPreset) {
  return JSON.stringify({
    teamId: team.id,
    teamAutonomy: team.autonomy_enabled,
    teams: teams.map((item) => [item.id, item.autonomy_enabled, item.leader_slot_id,
      item.slots.map((slot) => [slot.id, slot.enabled, slot.provider, slot.repo_path, slot.role, slot.area_labels ?? [], slot.expertise ?? null])
        .sort((a, b) => Number(a[0]) - Number(b[0]))])
      .sort((a, b) => Number(a[0]) - Number(b[0])),
    scopes: scopes.map((item) => [
      item.id, item.preset_id, item.enabled, item.repo_owner.toLowerCase(), item.repo_name.toLowerCase(),
      item.repo_path, item.base_ref, item.dispatch_label, item.design_label, item.github_auth_mode,
      item.github_auth_configured, item.github_poll_token_configured,
    ]).sort((a, b) => Number(a[0]) - Number(b[0])),
  });
}

function findActivationOverlaps(
  targets: TeamGithubScope[], scopes: TeamGithubScope[], teams: AgentTeamPreset[],
): ScopeOverlap[] {
  const targetIds = new Set(targets.map((item) => item.id));
  if (!targetIds.size) return [];
  const activeTeamIds = new Set(teams.filter((item) => item.autonomy_enabled).map((item) => item.id));
  const future = new Map<number, TeamGithubScope>();
  for (const item of scopes) if (item.enabled && activeTeamIds.has(item.preset_id)) future.set(item.id, item);
  for (const item of targets) future.set(item.id, item);
  const candidates = [...future.values()].sort((a, b) => a.id - b.id);
  const overlaps: ScopeOverlap[] = [];
  for (let i = 0; i < candidates.length; i += 1) {
    for (let j = i + 1; j < candidates.length; j += 1) {
      const first = candidates[i];
      const second = candidates[j];
      if (!targetIds.has(first.id) && !targetIds.has(second.id)) continue;
      if (first.repo_owner.toLowerCase() !== second.repo_owner.toLowerCase() ||
          first.repo_name.toLowerCase() !== second.repo_name.toLowerCase() ||
          first.dispatch_label !== second.dispatch_label) continue;
      // An active collision exists now. A prospective overlap appears after this action.
      const active = first.enabled && second.enabled &&
        activeTeamIds.has(first.preset_id) && activeTeamIds.has(second.preset_id);
      overlaps.push({ key: `${first.id}:${second.id}`, first, second, active });
    }
  }
  return overlaps;
}

function overlapDescription(overlap: ScopeOverlap) {
  const { first, second } = overlap;
  return `${first.repo_owner}/${first.repo_name} label ${first.dispatch_label}: team ${first.preset_id}/scope ${first.id} and team ${second.preset_id}/scope ${second.id}`;
}

function teamMatchesDraft(
  team: AgentTeamPreset, draft: Draft, routing: Record<string, { areaLabels: string; expertise: string }>,
) {
  const workers = draft.workerNames.split("\n").map((name) => name.trim()).filter(Boolean);
  const names = [draft.leaderName.trim(), ...workers];
  if (team.name !== draft.teamName.trim() || team.autonomy_enabled || team.slots.length !== names.length ||
      new Set(names).size !== names.length) return false;
  const leader = team.slots.find((slot) => slot.display_name === draft.leaderName.trim());
  if (!leader || team.leader_slot_id !== leader.id || !leader.enabled || leader.provider !== draft.provider ||
      leader.repo_path !== draft.path.trim() || (leader.role ?? "").toLowerCase() !== "leader") return false;
  return workers.every((name) => {
    const slot = team.slots.find((item) => item.display_name === name);
    const expected = (routing[name]?.areaLabels ?? "").split(",").map((item) => item.trim()).filter(Boolean);
    return Boolean(slot && slot.enabled && slot.provider === draft.provider && slot.repo_path === draft.path.trim() &&
      (slot.role ?? "").toLowerCase() === "worker" && (slot.expertise ?? "") === (routing[name]?.expertise.trim() ?? "") &&
      JSON.stringify(slot.area_labels ?? []) === JSON.stringify(expected));
  });
}

function isDefiniteCreateNonWrite(cause: unknown) {
  // Only 401 and 422 prove the create was rejected before any write.
  return cause instanceof ApiHttpError && (cause.status === 401 || cause.status === 422);
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
  const [uncertainLaunch, setUncertainLaunch] = useState<UncertainLaunch>(null);
  const [launchReconciliationReady, setLaunchReconciliationReady] = useState(false);
  const [launchSlots, setLaunchSlots] = useState<number[]>([]);
  const [includeLeader, setIncludeLeader] = useState(false);
  const [activationSnapshot, setActivationSnapshot] = useState<string | null>(null);
  const [activationScopes, setActivationScopes] = useState<TeamGithubScope[]>([]);
  const [scopeOverlaps, setScopeOverlaps] = useState<ScopeOverlap[]>([]);
  const [teamOverlaps, setTeamOverlaps] = useState<ScopeOverlap[]>([]);
  const [scopeOverlapAcks, setScopeOverlapAcks] = useState<string[]>([]);
  const [teamOverlapAcks, setTeamOverlapAcks] = useState<string[]>([]);
  const [activationReadiness, setActivationReadiness] = useState<string[]>([]);
  const [teamActivationAck, setTeamActivationAck] = useState(false);
  const [slotRouting, setSlotRouting] = useState<Record<string, { areaLabels: string; expertise: string }>>({});
  const [tokenDialogOpen, setTokenDialogOpen] = useState(false);
  const [tokenInput, setTokenInput] = useState("");
  const [tokenError, setTokenError] = useState<string | null>(null);
  const tokenPromiseRef = useRef<Promise<string | null> | null>(null);
  const tokenResolverRef = useRef<((value: string | null) => void) | null>(null);
  const [confirmSave, setConfirmSave] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const token = getOperatorToken();
  const inputKey = useMemo(() => normalized(draft), [draft]);
  const currentPreflight = preflight?.key === inputKey ? preflight.value : null;
  const currentKey = useRef(inputKey);
  currentKey.current = inputKey;

  async function readTeamActivationBlockers(currentTeam: AgentTeamPreset, operatorToken: string): Promise<string[]> {
    const [roster, plan] = await Promise.all([
      apiClient<MailTeam>("agent-mail/team?sync=false", { cache: "no-store" }),
      planAgentTeamLaunch(currentTeam.id, {
        slot_ids: currentTeam.slots.filter((slot) => slot.enabled).map((slot) => slot.id),
        reuse_existing: true,
      }, operatorToken),
    ]);
    const blockers: string[] = [];
    const leader = currentTeam.slots.find((slot) => slot.id === currentTeam.leader_slot_id && slot.enabled);
    const isConnectedForSlot = (member: MailTeam["members"][number], slotId: number) =>
      member.team_preset_id === currentTeam.id && member.team_slot_id === slotId && member.status === "connected" &&
      member.sessions.some((session) => session.team_preset_id === currentTeam.id && session.team_slot_id === slotId && session.mailbox_status === "connected");
    const leaderMember = leader ? roster.members.find((member) => isConnectedForSlot(member, leader.id)) : undefined;
    if (!leader || !leaderMember) blockers.push("A connected Agent Mail Leader is required.");
    const connectedWorker = currentTeam.slots.filter((slot) => slot.enabled && slot.id !== currentTeam.leader_slot_id)
      .flatMap((slot) => roster.members.filter((member) => member.id !== leaderMember?.id && isConnectedForSlot(member, slot.id)));
    if (!connectedWorker.length) blockers.push("A distinct connected worker is required for owner and approver separation.");
    if (!plan.can_launch) {
      const blocked = plan.items.filter((item) => item.action === "blocked");
      blockers.push(blocked.length
        ? `Provider and Agent Mail readiness is blocked for ${blocked.map((item) => `${item.slot_name} (${item.block_code ?? "not_ready"})`).join(", ")}.`
        : "Provider and Agent Mail readiness is not confirmed.");
    }
    return blockers;
  }

  function applyActivationReview(fresh: { presets: AgentTeamPreset[]; scopes: TeamGithubScope[] }, freshTeam: AgentTeamPreset, freshScope: TeamGithubScope) {
    const scopeTargets = freshTeam.autonomy_enabled || freshScope.enabled ? (freshScope.enabled ? [] : [freshScope]) : [];
    const teamTargets = freshTeam.autonomy_enabled ? [] : fresh.scopes.filter((item) => item.preset_id === freshTeam.id && item.enabled);
    const scopeConflicts = findActivationOverlaps(scopeTargets, fresh.scopes, fresh.presets);
    const teamConflicts = findActivationOverlaps(teamTargets, fresh.scopes, fresh.presets);
    const visibleIds = new Set<number>([freshScope.id, ...teamTargets.map((item) => item.id)]);
    for (const conflict of [...scopeConflicts, ...teamConflicts]) {
      visibleIds.add(conflict.first.id);
      visibleIds.add(conflict.second.id);
    }
    setActivationScopes(fresh.scopes.filter((item) => visibleIds.has(item.id)));
    setScopeOverlaps(scopeConflicts);
    setTeamOverlaps(teamConflicts);
    setScopeOverlapAcks([]);
    setTeamOverlapAcks([]);
    setActivationSnapshot(buildActivationSnapshot(fresh.scopes, fresh.presets, freshTeam));
  }

  function requestOperatorToken(error: string | null = null): Promise<string | null> {
    const stored = getOperatorToken();
    if (stored) return Promise.resolve(stored);
    if (tokenPromiseRef.current) return tokenPromiseRef.current;
    setTokenError(error);
    setTokenDialogOpen(true);
    const pending = new Promise<string | null>((resolve) => { tokenResolverRef.current = resolve; });
    tokenPromiseRef.current = pending;
    return pending;
  }

  function settleOperatorToken(value: string | null) {
    if (value) setOperatorToken(value);
    tokenResolverRef.current?.(value);
    tokenResolverRef.current = null;
    tokenPromiseRef.current = null;
    setTokenDialogOpen(false);
    setTokenInput("");
    setTokenError(null);
  }

  async function withOperatorToken<Result>(action: (value: string) => Promise<Result>): Promise<Result> {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const value = await requestOperatorToken(attempt ? "The operator token was rejected. Enter a valid token to retry." : null);
      if (!value) throw new Error("Operator token is required for this action.");
      try { return await action(value); }
      catch (cause) {
        if (!(cause instanceof ApiHttpError) || cause.status !== 401 || attempt > 0) throw cause;
        clearOperatorToken();
      }
    }
    throw new Error("Operator token was rejected.");
  }

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

  useEffect(() => () => {
    tokenResolverRef.current?.(null);
    tokenResolverRef.current = null;
    tokenPromiseRef.current = null;
  }, []);

  const update = (patch: Partial<Draft>) => {
    currentKey.current = normalized({ ...draft, ...patch });
    setDraft((current) => ({ ...current, ...patch }));
    setLaunchPlan(null);
    setActivationSnapshot(null);
    setScopeOverlaps([]);
    setTeamOverlaps([]);
    setScopeOverlapAcks([]);
    setTeamOverlapAcks([]);
    setActivationReadiness([]);
    setConfirmSave(false);
  };
  const matchingOverlap = useMemo(() => scopes.filter((item) =>
    item.enabled && item.repo_owner.toLowerCase() === draft.owner.trim().toLowerCase() &&
    item.repo_name.toLowerCase() === draft.repo.trim().toLowerCase() && item.dispatch_label === draft.dispatch.trim()
  ), [scopes, draft.owner, draft.repo, draft.dispatch]);

  async function checkPrerequisites() {
    setBusy(true); setError(""); setPreflight(null); setActivationSnapshot(null); setScopeOverlaps([]); setTeamOverlaps([]); setScopeOverlapAcks([]); setTeamOverlapAcks([]); setActivationReadiness([]); setTeamActivationAck(false);
    const checkedKey = inputKey;
    try {
      const value = await withOperatorToken((operatorToken) => apiClient<Preflight>("factory/setup-preflight", {
        method: "POST", headers: { "X-Deck-Operator-Token": operatorToken },
        body: JSON.stringify({ repo_owner: draft.owner.trim(), repo_name: draft.repo.trim(), repo_path: draft.path.trim(), dispatch_label: draft.dispatch.trim(), design_label: draft.design.trim(), dispatch_auth_mode: draft.authMode, base_ref: draft.baseRef.trim() }),
      }));
      if (currentKey.current !== checkedKey) return;
      setPreflight({ key: checkedKey, value });
    } catch (cause) {
      if (currentKey.current === checkedKey) setError(cause instanceof ApiHttpError ? cause.message : cause instanceof Error ? cause.message : "The check failed.");
    } finally { setBusy(false); }
  }

  async function reconcileUnknown(kind: "team" | "scope", teamId?: number, requested?: { draft: Draft; routing: Record<string, { areaLabels: string; expertise: string }> }) {
    setBusy(true); setError("");
    try {
      const fresh = await refreshConfiguration();
      if (kind === "team") {
        const names = [draft.leaderName.trim(), ...draft.workerNames.split("\n").map((name) => name.trim()).filter(Boolean)];
        const candidates = fresh.presets.filter((item) => item.name === draft.teamName.trim() &&
          item.slots.length === names.length && names.every((name) => item.slots.some((slot) => slot.display_name === name)));
        setRecovery({ kind, candidates: candidates.map((item) => ({ label: `${item.name} (#${item.id})`, id: item.id })), requestedDraft: requested?.draft, requestedRouting: requested?.routing });
      } else {
        const candidates = fresh.scopes.filter((item) => item.preset_id === (teamId ?? team?.id) && item.repo_owner.toLowerCase() === draft.owner.trim().toLowerCase() &&
          item.repo_name.toLowerCase() === draft.repo.trim().toLowerCase() && item.repo_path === draft.path.trim() &&
          item.dispatch_label === draft.dispatch.trim() && item.design_label === draft.design.trim() && item.base_ref === draft.baseRef.trim() &&
          item.github_auth_mode === (draft.authMode === "github_app" ? "app" : "ambient"));
        setRecovery({ kind, candidates: candidates.map((item) => ({ label: `Scope #${item.id} (${item.enabled ? "enabled" : "disabled"})`, id: item.id })) });
      }
      setError("The create response was uncertain. Review fresh matching records and select one, or stop. Do not repeat the create request.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not reconcile the uncertain create result."); }
    finally { setBusy(false); }
  }

  async function saveSetup() {
    if (recovery || !confirmSave || (draft.teamMode === "existing" && !draft.teamId)) return;
    const saveToken = await requestOperatorToken();
    if (!saveToken) { setError("The operator token is required. The draft remains available."); return; }
    setBusy(true); setError("");
    try {
      const fresh = await refreshConfiguration();
      let selected: AgentTeamPreset | null;
      if (draft.teamMode === "existing") {
        selected = fresh.presets.find((item) => item.id === draft.teamId) ?? null;
      } else if (team) {
        const confirmed = fresh.presets.find((item) => item.id === team.id) ?? null;
        if (!confirmed) throw new Error("The previously created team is no longer present. Refresh and review the records before saving again.");
        if (!teamMatchesDraft(confirmed, draft, slotRouting)) {
          setTeam(confirmed);
          throw new Error("The draft changed after the team was created. The saved team keeps its confirmed values. Make a separately reviewed edit, or start this setup again with a new team.");
        }
        selected = confirmed;
      } else {
        selected = null;
      }
      if (draft.teamMode === "new" && !selected) {
        const names = draft.workerNames.split("\n").map((name) => name.trim()).filter(Boolean);
        const allNames = [draft.leaderName.trim(), ...names];
        if (allNames.some((name) => !name) || new Set(allNames).size !== allNames.length) {
          throw new Error("Enter unique, non-empty names for the Leader and each worker.");
        }
        const input: AgentTeamPresetInput = {
          name: draft.teamName.trim(), autonomy_enabled: false,
          slots: [
            { display_name: draft.leaderName.trim(), provider: draft.provider, repo_path: draft.path.trim(), role: "Leader", area_labels: [], expertise: null, enabled: true },
            ...names.map((name) => {
              const route = slotRouting[name] ?? { areaLabels: "", expertise: "" };
              return { display_name: name, provider: draft.provider, repo_path: draft.path.trim(), role: "Worker", area_labels: route.areaLabels.split(",").map((item) => item.trim()).filter(Boolean), expertise: route.expertise.trim() || null, enabled: true };
            }),
          ],
        };
        setRecovery({ kind: "team", candidates: [], requestedDraft: { ...draft }, requestedRouting: { ...slotRouting } });
        try {
          selected = await withOperatorToken((operatorToken) => createAgentTeamPreset(input, operatorToken));
          setRecovery(null);
        } catch (cause) {
          if (isDefiniteCreateNonWrite(cause)) {
            // A rejected non-write needs no latch. Safe correction or retry is allowed.
            setRecovery(null);
            throw cause;
          }
          await reconcileUnknown("team", undefined, { draft: { ...draft }, routing: { ...slotRouting } });
          throw cause;
        }
        setTeam(selected);
      }
      if (!selected) throw new Error("Select an existing team or create a new team.");
      if (draft.teamMode === "new") {
        const leaderSlot = selected.slots.find((slot) => slot.display_name === draft.leaderName.trim());
        if (!leaderSlot) throw new Error("The saved team has no matching Leader slot. Review the team before setup continues.");
        if (selected.leader_slot_id !== leaderSlot.id) {
          selected = await updateAgentTeamLeader(selected.id, { leader_slot_id: leaderSlot.id, expected_leader_slot_id: selected.leader_slot_id ?? null, expected_updated_at: selected.updated_at, reason: "Set the explicit Leader during guided repository setup." }, saveToken);
        }
      } else if (!selected.leader_slot_id) {
        throw new Error("The existing team has no explicit Leader assignment. Keep its settings unchanged and resolve its authority separately.");
      }
      setTeam(selected);
      const sameScope = fresh.scopes.find((item) => item.preset_id === selected!.id && item.repo_owner.toLowerCase() === draft.owner.trim().toLowerCase() &&
        item.repo_name.toLowerCase() === draft.repo.trim().toLowerCase());
      let savedScope = sameScope ?? null;
      if (savedScope && !scopeMatchesDraft(savedScope, draft)) {
        setScope(savedScope);
        setStep(5);
        throw new Error("This team already has a scope for the repository with different saved settings. The existing scope remains unchanged. Review it in Agent Teams before making a separate edit.");
      }
      if (!savedScope) {
        setRecovery({ kind: "scope", candidates: [], requestedDraft: { ...draft }, requestedRouting: { ...slotRouting } });
        try {
          savedScope = await withOperatorToken((operatorToken) => createTeamGithubScope(selected.id, {
            repo_owner: draft.owner.trim(), repo_name: draft.repo.trim(), repo_path: draft.path.trim(),
            dispatch_label: draft.dispatch.trim(), design_label: draft.design.trim(), merge_policy: "human",
            max_approval_rounds: 3, max_concurrent_dispatched: 1, max_verification_retries: 1,
            max_auto_merges_per_day: 0, base_ref: draft.baseRef.trim(), github_auth_mode: draft.authMode === "github_app" ? "app" : "ambient",
            builds_out_of_tree: false, max_build_parallelism: 1, enabled: false,
          }, operatorToken));
          setRecovery(null);
        } catch (cause) {
          if (isDefiniteCreateNonWrite(cause)) {
            setRecovery(null);
            throw cause;
          }
          await reconcileUnknown("scope", selected.id, { draft: { ...draft }, routing: { ...slotRouting } });
          throw cause;
        }
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
        const requestedDraft = recovery.requestedDraft ?? draft;
        const requestedRouting = recovery.requestedRouting ?? slotRouting;
        if (!teamMatchesDraft(recovered, requestedDraft, requestedRouting)) {
          throw new Error("The selected team does not match the recorded create request. Keep setup blocked and make a separately reviewed edit or an explicit reviewed selection.");
        }
        setTeam(recovered); setRecovery(null); setError("Team recovered and bound to its confirmed ID. Review the saved team, then save the repository scope as a separate step.");
      } else {
        const recovered = fresh.scopes.find((item) => item.id === id);
        if (!recovered) throw new Error("The selected scope is no longer present. Refresh and review the records again.");
        if (recovered.preset_id !== team?.id || !scopeMatchesDraft(recovered, draft)) throw new Error("The selected scope no longer matches this team and draft. Keep setup blocked and review the records again.");
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
      const freshScope = fresh.scopes.find((item) => item.id === scope.id);
      if (!freshTeam) throw new Error("The selected team is no longer available.");
      if (!freshScope || freshScope.preset_id !== freshTeam.id) throw new Error("The saved scope no longer belongs to the selected team.");
      if (!scopeMatchesDraft(freshScope, draft)) throw new Error("The selected scope changed or no longer matches this draft. Review the saved scope before activation.");
      setTeam(freshTeam);
      setScope(freshScope);
      applyActivationReview(fresh, freshTeam, freshScope);
      setTeamActivationAck(false);
      setActivationReadiness(await withOperatorToken((operatorToken) => readTeamActivationBlockers(freshTeam, operatorToken)));
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
        body: JSON.stringify(scopePreflightInput(scope)),
      });
      if (checkedKey !== currentKey.current || check.status !== "ready") { setPreflight({ key: checkedKey, value: check }); setActivationSnapshot(null); setError("Inputs changed or current checks are not ready. Review the new result before activation."); return; }
      const fresh = await refreshConfiguration();
      const freshTeam = fresh.presets.find((item) => item.id === team.id);
      const freshScope = fresh.scopes.find((item) => item.id === scope.id);
      if (!freshTeam || !freshScope) throw new Error("The selected team or scope is no longer available.");
      if (freshScope.preset_id !== freshTeam.id || !scopeMatchesDraft(freshScope, draft)) throw new Error("The selected saved scope changed. Review it again before activation.");
      if (freshScope.enabled) {
        setTeam(freshTeam); setScope(freshScope); setActivationSnapshot(null);
        setError("Fresh reads confirm that this scope is already enabled. No activation request was repeated.");
        return;
      }
      // Re-read configuration after the GitHub checks and compare the reviewed set.
      const snapshot = buildActivationSnapshot(fresh.scopes, fresh.presets, freshTeam);
      if (snapshot !== activationSnapshot) {
        applyActivationReview(fresh, freshTeam, freshScope);
        setTeamActivationAck(false);
        throw new Error("The reviewed configuration changed after the checks. Review the refreshed state and confirm the acknowledgements again.");
      }
      if (scopeOverlaps.some((item) => !scopeOverlapAcks.includes(item.key))) {
        throw new Error("Acknowledge each listed overlap, active collisions and prospective overlaps, before activation.");
      }
      if (!freshTeam.autonomy_enabled) throw new Error("Enable team automation as a separate reviewed action before enabling this scope.");
      const blockers = await withOperatorToken((operatorToken) => readTeamActivationBlockers(freshTeam, operatorToken));
      setActivationReadiness(blockers);
      if (blockers.length) throw new Error("Shared readiness requirements are not met. Resolve the listed blockers before activation.");
      const updatedScope = await updateTeamGithubScope(freshScope.id, { enabled: true }, token);
      setScope(updatedScope); await refreshConfiguration();
      setActivationSnapshot(null); setError("Scope activated after current access, label, readiness, and overlap checks.");
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

  async function activateTeam() {
    if (!scope || !team || !token || !activationSnapshot || team.autonomy_enabled || currentPreflight?.status !== "ready") return;
    setBusy(true); setError("");
    try {
      const fresh = await refreshConfiguration();
      const freshTeam = fresh.presets.find((item) => item.id === team.id);
      const freshScope = fresh.scopes.find((item) => item.id === scope.id);
      if (!freshTeam || !freshScope || freshScope.preset_id !== freshTeam.id || !scopeMatchesDraft(freshScope, draft)) throw new Error("The selected team or saved scope changed. Review activation again.");
      if (freshTeam.autonomy_enabled) { setTeam(freshTeam); setActivationSnapshot(null); setError("Fresh reads show that team automation is already enabled."); return; }
      const siblings = fresh.scopes.filter((item) => item.preset_id === freshTeam.id && item.enabled);
      const activationTargets = [...new Map([freshScope, ...siblings].map((item) => [item.id, item])).values()];
      // Remote observations run first. Configuration is re-read after these HTTP checks.
      const observations = await Promise.all(activationTargets.map(async (item) => ({
        scopeId: item.id,
        result: await apiClient<Preflight>("factory/setup-preflight", {
          method: "POST", headers: { "X-Deck-Operator-Token": token },
          body: JSON.stringify(scopePreflightInput(item)),
        }),
      })));
      const incomplete = observations.filter(({ result }) => result.status !== "ready");
      if (incomplete.length) {
        throw new Error(`Team activation remains blocked. Recheck scope ${incomplete.map(({ scopeId, result }) => `${scopeId} (${result.status} at ${result.observed_at}: ${Object.values(result.checks).filter((check) => check.status !== "ready").map((check) => `${check.code}: ${check.remedy}`).join("; ")})`).join(", ")}.`);
      }
      const reviewed = await refreshConfiguration();
      const reviewedTeam = reviewed.presets.find((item) => item.id === team.id);
      const reviewedScope = reviewed.scopes.find((item) => item.id === scope.id);
      if (!reviewedTeam || !reviewedScope || reviewedScope.preset_id !== reviewedTeam.id || !scopeMatchesDraft(reviewedScope, draft)) throw new Error("The selected team or saved scope changed after the checks. Review activation again.");
      const snapshot = buildActivationSnapshot(reviewed.scopes, reviewed.presets, reviewedTeam);
      if (snapshot !== activationSnapshot) {
        applyActivationReview(reviewed, reviewedTeam, reviewedScope);
        setTeamActivationAck(false);
        throw new Error("The reviewed configuration changed after the checks. Review the refreshed state and confirm the acknowledgements again.");
      }
      if (teamOverlaps.some((item) => !teamOverlapAcks.includes(item.key))) {
        throw new Error("Acknowledge each listed overlap, active collisions and prospective overlaps, before enabling team automation.");
      }
      if (!teamActivationAck) throw new Error("Confirm team activation and review every enabled sibling scope first.");
      const blockers = await withOperatorToken((operatorToken) => readTeamActivationBlockers(reviewedTeam, operatorToken));
      setActivationReadiness(blockers);
      if (blockers.length) throw new Error("Shared readiness requirements are not met. Resolve the listed blockers before activation.");
      const updatedTeam = await updateAgentTeamPreset(reviewedTeam.id, { autonomy_enabled: true }, token);
      setTeam(updatedTeam); setActivationSnapshot(null); setTeamActivationAck(false);
      setError("Team automation enabled. Review scope activation separately before enabling this scope.");
      await refreshConfiguration();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Team activation could not be completed."); }
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
      setUncertainLaunch(null);
      setLaunchReconciliationReady(false);
    } catch (cause) {
      setError(`Launch outcome is uncertain. Do not launch again until an operator reconciles the team sessions. ${cause instanceof Error ? cause.message : "No safe result was returned."}`);
      setUncertainLaunch({ slotIds: [...launchSlots], planHash: launchPlan.plan_hash });
      setLaunchPlan(null); setLaunchUncertain(true);
    }
    finally { setBusy(false); }
  }

  async function reconcileLaunch() {
    if (!team || !token || !uncertainLaunch || uncertainLaunch.slotIds.length === 0) return;
    setBusy(true); setError(""); setLaunchReconciliationReady(false);
    try {
      const current = await planAgentTeamLaunch(team.id, { slot_ids: uncertainLaunch.slotIds, reuse_existing: true }, token);
      setLaunchPlan(current);
      const selectedItems = current.items.filter((item) => uncertainLaunch.slotIds.includes(item.slot_id));
      const confirmed = selectedItems.length === uncertainLaunch.slotIds.length && selectedItems.every((item) => item.action === "reuse" && Boolean(item.matching_session));
      setLaunchReconciliationReady(confirmed);
      setError(confirmed
        ? `Fresh planning found an existing session for every originally requested slot. Original plan ${uncertainLaunch.planHash}; review the plan, then confirm this reconciliation.`
        : `Fresh planning did not confirm an existing session for every originally requested slot from plan ${uncertainLaunch.planHash}. Keep launch blocked and ask an operator to reconcile the remaining slots.`);
    } catch (cause) {
      setError(`Launch outcome remains uncertain. ${cause instanceof Error ? cause.message : "Fresh session planning failed."}`);
    } finally { setBusy(false); }
  }

  return <section className="mx-auto max-w-3xl space-y-5">
    <div><h2 className="text-2xl font-semibold">Set up a repository</h2><p className="text-muted-foreground">Review the repository, team, routing, policy, save, launch, and activation as separate steps.</p></div>
    <ol className="flex flex-wrap gap-2 text-sm" aria-label="Setup steps">{["Repository", "Team and roles", "Routing", "Policy", "Review", "Saved setup"].map((name, index) => <li key={name} aria-current={step === index ? "step" : undefined} className={`rounded border px-3 py-1 ${step === index ? "bg-accent font-semibold" : ""}`}>{index + 1}. {name}</li>)}</ol>
    {error && <p role="alert" className="rounded border border-destructive p-3 text-sm">{error}</p>}
    {recovery && <div className={panelClass}><h3 className="font-semibold">Reconcile uncertain create</h3><p>Fresh reads found {recovery.candidates.length} matching record(s). Select one record to continue. Do not repeat the create request.</p>{recovery.candidates.length === 0 && <p role="status">No unique record is ready for selection. Keep this setup blocked and contact an operator.</p>}{recovery.candidates.map((item) => <Button key={item.id} variant="outline" disabled={busy} onClick={() => void resolveCandidate(item.id)}>Use {item.label}</Button>)}</div>}
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
      {preflight && <div className="rounded border p-3" aria-live="polite"><p>{currentPreflight ? "Current result" : "Stale result"}: {preflight.value.status}; observed {new Date(preflight.value.observed_at ?? preflight.value.checked_at ?? "").toLocaleString()}.</p>{Object.entries(preflight.value.checks).map(([name, check]) => <p key={name}>{name}: {check.status} ({check.code}). Remedy: {check.remedy}</p>)}</div>}
      <Button variant="outline" disabled={busy || !draft.owner || !draft.repo || !draft.path || !draft.dispatch || !draft.design || !draft.baseRef} onClick={() => setStep(1)}>Continue to configuration</Button>
    </div>}
    {step === 1 && <div className={panelClass}><label className={labelClass}>Team setup<select className={inputClass} value={draft.teamMode} onChange={(e) => update({ teamMode: e.target.value as Draft["teamMode"] })}><option value="new">Create an inactive team</option><option value="existing">Use an existing team</option></select></label>
      {draft.teamMode === "existing" ? <label className={labelClass}>Team<select className={inputClass} value={draft.teamId} onChange={(e) => update({ teamId: Number(e.target.value) || "" })}><option value="">Select a team</option>{presets.map((item) => <option key={item.id} value={item.id}>{item.name} ({item.autonomy_enabled ? "active" : "paused"})</option>)}</select></label> : <><label className={labelClass}>Team name<input className={inputClass} value={draft.teamName} onChange={(e) => update({ teamName: e.target.value })} /></label><label className={labelClass}>Explicit Leader slot<input className={inputClass} value={draft.leaderName} onChange={(e) => update({ leaderName: e.target.value })} /></label><label className={labelClass}>Worker slots, one name per line<textarea className={inputClass} value={draft.workerNames} onChange={(e) => update({ workerNames: e.target.value })} /></label><label className={labelClass}>Worker and Leader provider<select className={inputClass} value={draft.provider} onChange={(e) => update({ provider: e.target.value })}>{["claude-code", "codex-cli", "copilot-cli", "opencode-cli", "pi-cli"].map((item) => <option key={item}>{item}</option>)}</select></label></>}
      <p className="text-sm">New teams remain inactive. Existing roster, Leader, policy, and activation stay unchanged.</p><Button disabled={draft.teamMode === "existing" && !draft.teamId} onClick={() => setStep(2)}>Continue</Button></div>}
    {step === 2 && <div className={panelClass}><p>Repository dispatch and design labels apply to the scope. Worker routes are separate for each slot. The Leader has no worker route.</p>{draft.teamMode === "new" ? draft.workerNames.split("\n").map((rawName) => rawName.trim()).filter(Boolean).map((name) => <fieldset key={name} className="space-y-2 rounded border p-3"><legend className="font-medium">{name}</legend><label className={labelClass}>Area labels, comma separated<input className={inputClass} value={slotRouting[name]?.areaLabels ?? ""} onChange={(e) => { setConfirmSave(false); setSlotRouting((current) => ({ ...current, [name]: { areaLabels: e.target.value, expertise: current[name]?.expertise ?? "" } })); }} /></label><label className={labelClass}>Expertise<input className={inputClass} value={slotRouting[name]?.expertise ?? ""} onChange={(e) => { setConfirmSave(false); setSlotRouting((current) => ({ ...current, [name]: { areaLabels: current[name]?.areaLabels ?? "", expertise: e.target.value } })); }} /></label></fieldset>) : <p>Existing team routing stays unchanged.</p>}<p>Potential enabled overlaps: {matchingOverlap.map((item) => `team ${item.preset_id}/scope ${item.id}`).join(", ") || "none found in loaded data"}.</p><Button onClick={() => setStep(3)}>Continue</Button></div>}
    {step === 3 && <div className={panelClass}><h3 className="font-semibold">Policy</h3><p>Merge policy: human approval.</p><p>New scope limits: concurrency 1; verification retries 1; automatic merges 0.</p><p>Base branch: {draft.baseRef}. Scope is saved disabled, even when checks have gaps.</p><p>Existing team settings remain unchanged. Launch and activation require separate choices.</p><Button onClick={() => setStep(4)}>Review setup</Button></div>}
    {step === 4 && <div className={panelClass}><h3 className="font-semibold">Review</h3><p>Repository: {draft.owner}/{draft.repo}</p><p>Checkout: {draft.path}</p><p>Base: {draft.baseRef}</p><p>Labels: {draft.dispatch} / {draft.design}</p><p>Authentication: {draft.authMode}; credentials are not stored in this draft.</p><p>Preflight: {currentPreflight?.status ?? "not checked or stale"}. Saving remains disabled and does not need ready checks.</p><p>Team: {draft.teamMode === "existing" ? presets.find((item) => item.id === draft.teamId)?.name ?? "Select a team" : draft.teamName || "New team"}; Leader: {draft.teamMode === "new" ? draft.leaderName : "preserved"}; worker slots: {draft.teamMode === "new" ? draft.workerNames.split("\n").filter((name) => name.trim()).length : "preserved"}.</p><p>Potential overlap: {matchingOverlap.map((item) => `team ${item.preset_id}/scope ${item.id}`).join(", ") || "none found"}.</p><label className="flex gap-2 text-sm"><input type="checkbox" checked={confirmSave} onChange={(e) => setConfirmSave(e.target.checked)} />Save configuration only. Keep launch, team activation, scope activation, and merge decisions separate.</label><div className="flex flex-wrap gap-2"><Button disabled={busy || Boolean(recovery) || !confirmSave || (draft.teamMode === "existing" && !draft.teamId)} onClick={() => void saveSetup()}>{busy ? "Saving…" : "Save configuration"}</Button><Link className="self-center underline" to="/teams">Manage teams</Link></div></div>}
    {step === 5 && team && scope && <div className={panelClass}><h3 className="font-semibold">Saved configuration</h3><p>Team {team.name} (#{team.id}) is {team.autonomy_enabled ? "active" : "paused"}. Scope #{scope.id} is {scope.enabled ? "enabled" : "disabled"}.</p><p>Saving did not launch workers or activate this scope.</p>
      <section className="space-y-2 border-t pt-3"><h4 className="font-semibold">Separate worker launch</h4>{team.slots.filter((slot) => slot.id === team.leader_slot_id && slot.enabled).map((slot) => <label key={slot.id} className="flex gap-2 text-sm"><input type="checkbox" checked={includeLeader} onChange={(event) => { if (launchUncertain) return; setIncludeLeader(event.target.checked); setLaunchPlan(null); setLaunchReconciliationReady(false); setLaunchSlots((current) => event.target.checked ? [...new Set([...current, slot.id])] : current.filter((id) => id !== slot.id)); }} />Include Leader {slot.display_name} in this reviewed launch plan</label>)}{team.slots.filter((slot) => slot.enabled && slot.id !== team.leader_slot_id).map((slot) => <label key={slot.id} className="flex gap-2 text-sm"><input type="checkbox" checked={launchSlots.includes(slot.id)} onChange={(event) => { if (launchUncertain) return; setLaunchPlan(null); setLaunchReconciliationReady(false); setLaunchSlots((current) => event.target.checked ? [...new Set([...current, slot.id])] : current.filter((id) => id !== slot.id)); }} />{slot.display_name} ({slot.provider})</label>)}<Button disabled={busy || launchUncertain || launchSlots.length === 0} onClick={() => void reviewLaunch()}>Review current launch plan</Button>{launchUncertain && <><p role="status">Launch outcome needs operator reconciliation. This flow will not repeat the launch request.</p><Button disabled={busy || !uncertainLaunch} onClick={() => void reconcileLaunch()}>Reconcile current sessions</Button>{launchReconciliationReady && <Button disabled={busy} onClick={() => { setLaunchUncertain(false); setUncertainLaunch(null); setLaunchReconciliationReady(false); setLaunchPlan(null); setError("Current sessions were reconciled. Review a new launch plan before any further launch action."); }}>Confirm reconciled sessions</Button>}</>}{launchPlan && <div className="rounded border p-3"><p>Plan {launchPlan.can_launch ? "ready" : "blocked"}: spawn {launchPlan.spawn_count}, reuse {launchPlan.reuse_count}, blocked {launchPlan.blocked_count}.</p>{launchPlan.items.map((item) => <p key={item.slot_id}>{item.slot_name}: {item.action}{item.reasons.length ? ` (${item.reasons.join(", ")})` : ""}</p>)}<Button disabled={busy || launchUncertain || !launchPlan.can_launch} onClick={() => void launchSelected()}>Launch reviewed slots</Button></div>}</section>
      <section className="space-y-2 border-t pt-3"><h4 className="font-semibold">Separate activation</h4><p>Run a current ready access and label check before activation. Overlap detection is advisory. It is not an atomic cross-scope ownership guarantee.</p><Button disabled={busy} onClick={() => void checkPrerequisites()}>Refresh access and label check</Button><Button disabled={busy || currentPreflight?.status !== "ready"} onClick={() => void reviewActivation()}>Review current activation and overlap</Button>{activationSnapshot && <div className="space-y-2 rounded border p-3"><p>Scopes affected or overlapping: {activationScopes.map((item) => `team ${item.preset_id}/scope ${item.id} (${item.repo_owner}/${item.repo_name}, ${item.dispatch_label})`).join(", ") || "none"}.</p>
      {activationReadiness.length > 0 && <div className="rounded border p-2" role="status"><p className="font-medium">Shared readiness blockers</p>{activationReadiness.map((item) => <p key={item} className="text-sm">{item}</p>)}</div>}
      {scopeOverlaps.length > 0 && <div className="space-y-1"><p className="font-medium">Scope activation overlaps</p>{scopeOverlaps.map((overlap) => <label key={overlap.key} className="flex gap-2 text-sm"><input type="checkbox" checked={scopeOverlapAcks.includes(overlap.key)} onChange={(e) => setScopeOverlapAcks((current) => e.target.checked ? [...current, overlap.key] : current.filter((key) => key !== overlap.key))} /><span>{overlap.active ? "Active collision" : "Prospective overlap"}: {overlapDescription(overlap)}. {overlapWarning}.</span></label>)}</div>}
      {teamOverlaps.length > 0 && <div className="space-y-1"><p className="font-medium">Team activation overlaps</p>{teamOverlaps.map((overlap) => <label key={overlap.key} className="flex gap-2 text-sm"><input type="checkbox" checked={teamOverlapAcks.includes(overlap.key)} onChange={(e) => setTeamOverlapAcks((current) => e.target.checked ? [...current, overlap.key] : current.filter((key) => key !== overlap.key))} /><span>{overlap.active ? "Active collision" : "Prospective overlap"}: {overlapDescription(overlap)}. {overlapWarning}.</span></label>)}</div>}
      {!team.autonomy_enabled && <><label className="flex gap-2 text-sm"><input type="checkbox" checked={teamActivationAck} onChange={(e) => setTeamActivationAck(e.target.checked)} />Enable team automation. This also resumes each listed enabled sibling scope.</label><Button disabled={busy || !teamActivationAck || teamOverlaps.some((item) => !teamOverlapAcks.includes(item.key)) || activationReadiness.length > 0} onClick={() => void activateTeam()}>Enable team automation</Button></>}<Button disabled={busy || !team.autonomy_enabled || scopeOverlaps.some((item) => !scopeOverlapAcks.includes(item.key)) || activationReadiness.length > 0} onClick={() => void activateScope()}>Enable this scope</Button></div>}</section>
    </div>}
    {step > 0 && step < 5 && <Button variant="outline" onClick={() => setStep((value) => Math.max(0, value - 1))}>Back</Button>}
    <OperatorTokenDialog
      open={tokenDialogOpen}
      value={tokenInput}
      error={tokenError}
      onValueChange={setTokenInput}
      onSubmit={() => settleOperatorToken(tokenInput)}
      onCancel={() => settleOperatorToken(null)}
    />
  </section>;
}
