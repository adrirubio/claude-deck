"""Read-only operating catalog with single-flight local readiness observations.

No launch planning, process discovery, credential reads or model calls belong here.
Legacy install-status probes include synchronous MCP CLI work. One worker per
process shares its result across every card, and each request waits at most 2s.
Cancellation never starts another worker while that observation is in flight.
"""
from __future__ import annotations

import asyncio
import ctypes
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

from app.models import provider_operations_schemas as wire
from app.services.providers import get_providers
from app.services.provider_readiness_service import configuration_readiness

TTL_SECONDS = 60
WAIT_SECONDS = 2
AGGREGATE_SECONDS = 90
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="provider-observation")
_lock = threading.Lock()
_future = None


def now():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Snapshot:
    installed: dict[str, bool]
    install_status: object | None
    started_at: datetime
    observed_at: datetime
    completed_monotonic: float
    failed: bool = False


def _observe_install_status():
    # The isolated supervisor owns/reaps its observer's entire inherited tree.
    # A request timeout never cancels this worker; only the aggregate deadline
    # asks the supervisor to terminate its probes and finish cleanup.
    with subprocess.Popen(
        [sys.executable, "-m", "app.services.provider_operations_service", "--snapshot"],
        cwd=Path(__file__).resolve().parents[2],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
    ) as observer:
        try:
            stdout, _ = observer.communicate(timeout=AGGREGATE_SECONDS)
            if observer.returncode:
                raise subprocess.CalledProcessError(observer.returncode, observer.args)
        except BaseException:
            observer.terminate()
            observer.communicate()  # Wait for supervisor-owned tree cleanup.
            raise
        return stdout


def _supervised_observation(command):
    # Linux-only, in the disposable supervisor process, never the API process.
    # Subreaping adopts only this process's orphaned descendants, allowing us to
    # wait for their exit even if the observer exited first or closed its pipes.
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Observer cleanup unavailable")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise RuntimeError("Observer cleanup unavailable")

    def deadline(*_):
        raise TimeoutError("Observer deadline")

    signal.signal(signal.SIGTERM, deadline)
    # Track the child before a pending deadline can interrupt its creation.
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
    child = None
    try:
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    finally:
        # Unblocking can raise via deadline(); keep cleanup around that too.
        if child is None:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    try:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        stdout, _ = child.communicate()
        if child.returncode:
            raise subprocess.CalledProcessError(child.returncode, command)
        return stdout
    finally:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.communicate()
        while True:
            try:
                os.waitpid(-1, 0)  # Only children of this private supervisor.
            except ChildProcessError:
                break


def _collect_snapshot():
    started = now()
    installed = {}
    status = None
    failed = False
    try:
        # get_status uses the same which predicate; versions are unnecessary here.
        installed = {p.id: shutil.which(p.binary_name) is not None for p in get_providers()}
        # The legacy async helper performs synchronous probes. A fixed local
        # Python observer gives the entire observation a hard aggregate deadline.
        # It executes no provider model/launch command and returns only flags.
        stdout = _observe_install_status()
        if len(stdout) > 8192:
            raise ValueError("Invalid observer payload")
        payload = json.loads(stdout)
        if not isinstance(payload, dict) or set(payload) != set(INSTALL_FIELDS):
            raise ValueError("Invalid observer fields")
        status = SimpleNamespace(**payload)
    except Exception:
        # Never expose exception messages, raw status objects, host paths or output.
        failed = True
    return Snapshot(installed, status, started, now(), time.monotonic(), failed)


INSTALL_FIELDS = {
    "claude_code_mcp_installed": bool, "claude_code_hooks_missing": list,
    "codex_cli_available": bool, "codex_mcp_installed": bool, "codex_hooks_missing": list,
    "copilot_cli_available": bool, "copilot_mcp_installed": bool, "copilot_hooks_missing": list,
    "opencode_cli_available": bool, "opencode_mcp_installed": bool, "opencode_plugin_events_missing": list,
    "pi_mail_ready": bool,
}


async def _snapshot_payload():
    from app.services.agent_mail_install_service import get_install_status
    status = await get_install_status()
    # Legacy negative flags may reflect probe failure; never expose diagnostics,
    # path names, missing hook contents, secrets or wholesale install status.
    return {
        key: (value if kind is bool else ["missing"] if value else [])
        if type(value := getattr(status, key, None)) is kind else None
        for key, kind in INSTALL_FIELDS.items()
    }


async def readiness_snapshot():
    global _future
    with _lock:
        if _future is None or (_future.done() and time.monotonic() - _future.result().completed_monotonic >= TTL_SECONDS):
            _future = _executor.submit(_collect_snapshot)
        future = _future
    try:
        return await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)), WAIT_SECONDS)
    except asyncio.TimeoutError:
        return None


SURFACES = (
    "summary", "config", "mcp", "plugins", "commands", "hooks", "permissions",
    "agents", "skills", "memory", "backup", "output-styles", "statusline",
    "sessions", "plans", "context", "usage",
)
COMPONENTS = {
    "summary": "DashboardPage", "config": "ConfigViewerPage", "mcp": "MCPServersPage",
    "plugins": "PluginsPage", "commands": "CommandsPage", "hooks": "HooksPage",
    "permissions": "PermissionsPage", "agents": "AgentsPage", "skills": "SkillsPage",
    "memory": "MemoryPage", "backup": "BackupPage", "output-styles": "OutputStylesPage",
    "statusline": "StatusLinePage", "sessions": "SessionsPage", "plans": "PlansPage",
    "context": "ContextPage", "usage": "UsagePage",
}
READ_ONLY = {"summary", "sessions", "plans", "context", "usage"}


def native_surfaces(provider):
    """Only frozen P02 adapters have native pages; capability flags cannot add one."""
    matrix = provider.get_capability_matrix()
    implemented = set(SURFACES) if provider.id == "claude-code" else {"summary", "config", "mcp", "plugins", "plans"} if provider.id == "codex-cli" else set()
    result = {}
    for surface in SURFACES:
        capability = "output_styles" if surface == "output-styles" else surface
        state = matrix.get(capability, {}).get("state")
        if surface not in implemented or state in {"unsupported", "unknown"}:
            result[surface] = wire.NativeSurface(state="unavailable", reason="No available implemented provider-specific native adapter.")
        else:
            read_only = surface in READ_ONLY or state == "read_only"
            result[surface] = wire.NativeSurface(
                state="available", adapter_id=f"{provider.id}:{surface}:{COMPONENTS[surface]}",
                access="read_only" if read_only else "read_write",
                reason="Implemented P02 provider/page adapter; server authorization still applies.",
                conditions=["Matching checked-in adapter", "Intersection with native capability access", "Existing server authorization for writes"],
            )
    return result


def operations(provider_id):
    sources = [f"backend/app/services/providers/{provider_id.replace('-cli', '_cli').replace('-', '_')}.py", "backend/app/services/agent_team_service.py"]
    # Claude's adapter filename differs from its CLI identity.
    if provider_id == "claude-code":
        sources[0] = "backend/app/services/providers/claude_code.py"
    shared = {
        "launch": ("Deck has a validated native launch contract.", ["Binary and Mail prerequisites", "Validated provider launch options", "Existing launch actor authorization"]),
        "observe_session": ("Deck can associate native sessions under identity checks.", ["Provider-specific discovery", "Exact team/slot/member and pane identity", "Fresh observations"]),
        "mail_identity": ("Authenticated Mail identifies a team slot under the server binding contract.", ["Installed provider Mail integration", "Connected MCP session", "Matching team slot and capability"]),
        "receive_work": ("Mail briefs and wake delivery require a verified runnable recipient.", ["Current owned dispatch", "Authenticated Mail identity", "Verified wake target"]),
        "report_work_status": ("Structured status reporting preserves current owner authority.", ["Current owned work item", "Fresh dispatch and workspace lease", "Supported status transition"]),
        "approval_participation": ("Approval participation is constrained to the designated actor.", ["Current designated Leader or owner as required", "Current normalized approval round", "Server principal checks"]),
        "workspace_association": ("Assigned checkout participation requires the existing lease contract.", ["Current work-item lease", "Assigned workspace identity", "No inferred authority from working directory"]),
        "resume_exact": ("Exact resume requires an identified native session and matching project.", ["Exact session selector", "Matching project/workspace", "Current binding and approved recovery authority"]),
        "interactive_terminal": ("The existing Bridge can expose a verified native terminal.", ["Verified session association", "Existing terminal-mode/server authority", "A live pane is not generic provider readiness"]),
        "execution_controls": ("Native launch options expose provider-specific controls; enforcement is not certified by a flag.", ["Supported native launch options", "Explicit operator configuration", "No inferred sandbox or recovery guarantee"]),
    }
    result = {key: wire.Operation(state="conditional", reason=reason, conditions=conditions, evidence=sources + ["backend/tests/test_provider_operations.py::test_contract_matrix"]) for key, (reason, conditions) in shared.items()}
    for key in ("mail_identity", "receive_work", "report_work_status", "approval_participation"):
        result[key].evidence.append("backend/app/services/agent_mail_service.py")
    result["workspace_association"].evidence.append("backend/app/services/github_workspace_service.py")
    result["interactive_terminal"].evidence.append("backend/app/services/agent_bridge/discovery.py")
    if provider_id == "pi-cli":
        result["launch"].conditions += ["Explicit extension opt-in", "Supported Pi/Node/Python integration runtime", "platform=openrouter"]
        result["resume_exact"].conditions += ["Exact full ID or project-local session file and matching header", "No foreign or guessed session"]
        result["execution_controls"] = wire.Operation(state="unsupported", reason="Deck does not provide a Pi sandbox or native permission-enforcement controls.", evidence=sources, conditions=["Pi integration must not imply added isolation"])
    elif provider_id in {"copilot-cli", "opencode-cli"}:
        result["resume_exact"].conditions.append("Latest/continue is not exact resume; same-repository ambiguity blocks launch")
        result["execution_controls"].state = "unknown"
        result["execution_controls"].reason = "Provider integration or CLI flags do not establish a verified execution-isolation guarantee."
    else:
        result["execution_controls"].conditions.append("Explicit native permission/sandbox settings; bypass does not supply isolation")
    return result


def catalog(provider, snapshot: Snapshot | None, session=None):
    return wire.ProviderOperations(
        provider=provider.id, provider_display_name=provider.display_name,
        operations=operations(provider.id), native_capabilities=provider.get_capability_matrix(),
        native_surfaces=native_surfaces(provider), readiness=wire.Readiness(
            configuration=configuration_readiness(provider.id, provider.display_name, snapshot.installed.get(provider.id) if snapshot else None, snapshot.install_status if snapshot else None),
            session=session or wire.SessionReadiness(),
            observed_at=snapshot.observed_at if snapshot else now(),
            observation_started_at=snapshot.started_at if snapshot else None,
            probe_state="pending" if snapshot is None else "failed" if snapshot.failed else "observed",
        ),
    )


async def scoped_session(db, provider_id, team_id, slot_id):
    """Reuse SQL-only P01 observations, with stricter provider/member matching."""
    from app.services.factory_projection_service import actor_evidence, association

    slots, members, sessions, bindings, retired = await actor_evidence(db, {team_id}, {})
    slot = next((s for s in slots if s.id == slot_id and s.preset_id == team_id), None)
    if slot is None or slot.provider != provider_id:
        raise ValueError("slot_context_not_found")
    selected = [m for m in members if m.team_preset_id == team_id and m.team_slot_id == slot_id and m.participant_kind == "team_slot"]
    context = {"team_id": team_id, "slot_id": slot_id}
    if len(selected) != 1:
        return wire.SessionReadiness(state="ambiguous" if len(selected) > 1 else "unknown", reason="A unique authenticated team-slot member was not established.", **context)
    member = selected[0]
    observed = association(slot, member, sessions, bindings, retired, now())
    # Count MCP conflicts before considering provider equality.
    if observed.state == "bound" and observed.observed_provider != provider_id:
        return wire.SessionReadiness(state="unknown", reason="Observed provider does not match the configured slot/provider.", **context)
    target = observed.bridge_target
    return wire.SessionReadiness(
        state=observed.state, reason={"bound": "One fresh authenticated member/session and non-retired pane identity match this slot/provider.", "offline": "Known member session is offline.", "ambiguous": "More than one live matching MCP session was observed.", "unknown": "Current session/pane identity has not been verified."}[observed.state],
        member_id=target.member_id if target else None, session_id=target.session_id if target else None,
        observed_provider=observed.observed_provider if observed.state == "bound" else None, **context,
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["--snapshot"]:
        sys.stdout.buffer.write(_supervised_observation(
            [sys.executable, "-m", "app.services.provider_operations_service", "--snapshot-payload"],
        ))
    elif sys.argv[1:] == ["--snapshot-payload"]:
        print(json.dumps(asyncio.run(_snapshot_payload())))
    else:
        raise SystemExit(2)
