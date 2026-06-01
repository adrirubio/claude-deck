# Agent Bridge Bedrock Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users pick Anthropic (default) or Amazon Bedrock as the platform when starting an Agent Bridge session, injecting the right Bedrock environment variables into the spawned `claude` process.

**Architecture:** A `platform` enum plus a provider-side env builder. The new-session dialog gains a Platform selector (Claude Code provider only); selecting Bedrock reveals optional Region/Profile/Model fields. On spawn, the backend converts the platform choice into a `dict[str, str]` of env vars and injects them into the tmux session via `tmux new-session -e KEY=VALUE`. Anthropic yields an empty env map, so its tmux command is byte-for-byte identical to today. Credentials are never collected or stored — they resolve from the server's AWS SDK credential chain.

**Tech Stack:** Python 3.11 / FastAPI / Pydantic / pytest (backend); React 19 / TypeScript / Vite / shadcn-ui (frontend); tmux for session spawning.

**Spec:** `docs/superpowers/specs/2026-05-29-agent-bridge-bedrock-platform-design.md`

**Branch:** `feat/agent-bridge-bedrock-platform` (already created; the design doc is the first commit).

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/services/providers/platform_env.py` | **New.** Platform constants + `build_platform_env()` — the single place platform→env mapping lives. |
| `backend/app/services/providers/base.py` | Add 4 platform fields to the `SpawnCommandOptions` dataclass. |
| `backend/app/services/agent_bridge/spawn.py` | Build the env map and inject `-e KEY=VALUE` flags into the tmux argv; record `platform` in session metadata. |
| `backend/app/api/v1/agent_bridge/router.py` | Add 4 platform fields to `SpawnRequest` and forward them into `SpawnCommandOptions`. |
| `backend/tests/test_platform_env.py` | **New.** Unit tests for `build_platform_env()`. |
| `backend/tests/test_agent_bridge_spawn.py` | Add tests asserting `-e` flags land in the tmux argv (Bedrock) and are absent (Anthropic). |
| `frontend/src/features/cc-bridge/types.ts` | Add 4 platform fields to `SpawnSessionRequest`. |
| `frontend/src/features/cc-bridge/NewSessionDialog.tsx` | Platform `<Select>` + conditional Bedrock inputs + localStorage remember/prefill. |

---

## Task 1: Platform env builder (backend, pure function)

**Files:**
- Create: `backend/app/services/providers/platform_env.py`
- Test: `backend/tests/test_platform_env.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_platform_env.py`:

```python
"""Tests for platform -> environment-variable mapping."""
import pytest


def test_anthropic_returns_empty_env():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_ANTHROPIC

    assert build_platform_env(PLATFORM_ANTHROPIC) == {}


def test_unknown_platform_returns_empty_env():
    from app.services.providers.platform_env import build_platform_env

    assert build_platform_env("vertex") == {}


def test_bedrock_minimal_sets_use_bedrock_flag():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_BEDROCK

    assert build_platform_env(PLATFORM_BEDROCK) == {"CLAUDE_CODE_USE_BEDROCK": "1"}


def test_bedrock_with_all_fields():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_BEDROCK

    env = build_platform_env(
        PLATFORM_BEDROCK,
        region="us-east-1",
        aws_profile="bedrock-prod",
        model="arn:aws:bedrock:us-east-1:123:inference-profile/x",
    )
    assert env == {
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "AWS_REGION": "us-east-1",
        "AWS_PROFILE": "bedrock-prod",
        "ANTHROPIC_MODEL": "arn:aws:bedrock:us-east-1:123:inference-profile/x",
    }


def test_bedrock_skips_blank_and_whitespace_values():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_BEDROCK

    env = build_platform_env(PLATFORM_BEDROCK, region="  ", aws_profile="", model=None)
    assert env == {"CLAUDE_CODE_USE_BEDROCK": "1"}


def test_bedrock_strips_surrounding_whitespace():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_BEDROCK

    env = build_platform_env(PLATFORM_BEDROCK, region="  us-west-2  ")
    assert env["AWS_REGION"] == "us-west-2"


def test_bedrock_rejects_newline_in_value():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_BEDROCK

    with pytest.raises(ValueError):
        build_platform_env(PLATFORM_BEDROCK, region="us-east-1\nFOO=bar")


def test_bedrock_rejects_null_byte_in_value():
    from app.services.providers.platform_env import build_platform_env, PLATFORM_BEDROCK

    with pytest.raises(ValueError):
        build_platform_env(PLATFORM_BEDROCK, model="bad\x00value")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && pytest tests/test_platform_env.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.providers.platform_env'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/providers/platform_env.py`:

```python
"""Map an Agent Bridge platform selection to process environment variables.

Single source of truth for platform -> env mapping. Credentials are never
handled here: only non-secret configuration (region, profile name, model id)
is set, and the AWS SDK credential chain on the host resolves actual creds.
"""
from __future__ import annotations

PLATFORM_ANTHROPIC = "anthropic"
PLATFORM_BEDROCK = "bedrock"


def _clean(value: str | None) -> str | None:
    """Trim a value and reject control characters that break env injection."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if "\n" in stripped or "\r" in stripped or "\x00" in stripped:
        raise ValueError("Environment value must not contain newlines or null bytes")
    return stripped


def build_platform_env(
    platform: str | None,
    region: str | None = None,
    aws_profile: str | None = None,
    model: str | None = None,
) -> dict[str, str]:
    """Return the env vars for a platform selection (empty for Anthropic)."""
    if platform != PLATFORM_BEDROCK:
        return {}

    env: dict[str, str] = {"CLAUDE_CODE_USE_BEDROCK": "1"}
    cleaned_region = _clean(region)
    if cleaned_region:
        env["AWS_REGION"] = cleaned_region
    cleaned_profile = _clean(aws_profile)
    if cleaned_profile:
        env["AWS_PROFILE"] = cleaned_profile
    cleaned_model = _clean(model)
    if cleaned_model:
        env["ANTHROPIC_MODEL"] = cleaned_model
    return env
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && pytest tests/test_platform_env.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/providers/platform_env.py backend/tests/test_platform_env.py
git commit -m "feat(agent-bridge): add platform->env builder for Bedrock"
```

---

## Task 2: Add platform fields to SpawnCommandOptions

**Files:**
- Modify: `backend/app/services/providers/base.py:18-37`

- [ ] **Step 1: Add the fields**

In `backend/app/services/providers/base.py`, the `SpawnCommandOptions` dataclass currently ends with `use_last: bool = False`. Add four fields immediately after it (still inside the dataclass):

```python
    use_last: bool = False
    platform: str = "anthropic"
    aws_region: str | None = None
    aws_profile: str | None = None
    bedrock_model: str | None = None
```

- [ ] **Step 2: Verify it imports**

Run: `cd backend && source venv/bin/activate && python -c "from app.services.providers.base import SpawnCommandOptions; print(SpawnCommandOptions(directory='/tmp').platform)"`
Expected: prints `anthropic`

- [ ] **Step 3: Run the existing spawn tests (must still pass)**

Run: `cd backend && source venv/bin/activate && pytest tests/test_agent_bridge_spawn.py -v`
Expected: PASS (2 passed) — new optional fields don't change existing behavior.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/providers/base.py
git commit -m "feat(agent-bridge): add platform options to SpawnCommandOptions"
```

---

## Task 3: Inject env vars into the tmux spawn

**Files:**
- Modify: `backend/app/services/agent_bridge/spawn.py:37-79`
- Test: `backend/tests/test_agent_bridge_spawn.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_agent_bridge_spawn.py`:

```python
def test_bedrock_platform_injects_env_flags(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    spawn.spawn_session(
        "claude-code",
        SpawnCommandOptions(
            directory=str(tmp_path),
            mode="plain",
            platform="bedrock",
            aws_region="us-east-1",
            aws_profile="bedrock-prod",
        ),
    )

    argv = calls[0]
    # Fixed prefix stays identical to the no-env command.
    assert argv[:7] == ["tmux", "new-session", "-d", "-s", "repo-abcd", "-c", str(tmp_path)]
    # Env flags are injected as -e KEY=VALUE pairs before the shell command.
    assert "-e" in argv
    assert "CLAUDE_CODE_USE_BEDROCK=1" in argv
    assert "AWS_REGION=us-east-1" in argv
    assert "AWS_PROFILE=bedrock-prod" in argv
    assert spawn.get_spawned_sessions()["repo-abcd"]["platform"] == "bedrock"


def test_anthropic_platform_adds_no_env_flags(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    spawn.spawn_session(
        "claude-code",
        SpawnCommandOptions(directory=str(tmp_path), mode="plain"),
    )

    argv = calls[0]
    assert "-e" not in argv
    # Command is exactly prefix + single shell-command element.
    assert argv[:7] == ["tmux", "new-session", "-d", "-s", "repo-abcd", "-c", str(tmp_path)]
    assert len(argv) == 8
    assert spawn.get_spawned_sessions()["repo-abcd"]["platform"] == "anthropic"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && pytest tests/test_agent_bridge_spawn.py -v`
Expected: FAIL — `test_bedrock_platform_injects_env_flags` (no `-e` in argv) and both `platform` metadata assertions raise `KeyError`.

- [ ] **Step 3: Implement env injection**

In `backend/app/services/agent_bridge/spawn.py`:

(a) Add the import near the existing provider imports (after line 13):

```python
from app.services.providers.claude_code import ClaudeCodeProvider
from app.services.providers.platform_env import build_platform_env
```

(b) Replace the spawn body from the `command = provider.build_spawn_command(options)` line through the `subprocess.run(...)` call (currently lines 49-58) with:

```python
    command = provider.build_spawn_command(options)
    shell_command = " ".join(shlex.quote(part) for part in command)

    platform_env = build_platform_env(
        options.platform,
        region=options.aws_region,
        aws_profile=options.aws_profile,
        model=options.bedrock_model,
    )
    env_flags: list[str] = []
    for key, value in platform_env.items():
        env_flags += ["-e", f"{key}={value}"]

    try:
        result = subprocess.run(
            ["tmux", "new-session", "-d", "-s", name, "-c", directory, *env_flags, shell_command],
            capture_output=True,
            text=True,
            timeout=10,
        )
```

(c) In the `_spawned_sessions[name] = {...}` dict (currently lines 66-71), add a `platform` entry:

```python
    _spawned_sessions[name] = {
        "provider": provider.id,
        "mode": options.mode,
        "directory": directory,
        "worktree_name": options.worktree_name or (name if options.mode == "worktree" else None),
        "platform": options.platform,
    }
```

Note: env flags are placed **after** `-c directory` and **before** `shell_command`, so the fixed `[:7]` prefix the existing tests assert remains unchanged, and the Anthropic (empty-env) command is byte-for-byte identical to today.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && pytest tests/test_agent_bridge_spawn.py -v`
Expected: PASS (4 passed — 2 original + 2 new)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent_bridge/spawn.py backend/tests/test_agent_bridge_spawn.py
git commit -m "feat(agent-bridge): inject platform env vars into tmux spawn"
```

---

## Task 4: Forward platform fields through the API

**Files:**
- Modify: `backend/app/api/v1/agent_bridge/router.py:27-44` and `:119-136`

- [ ] **Step 1: Add fields to SpawnRequest**

In `backend/app/api/v1/agent_bridge/router.py`, the `SpawnRequest` model currently ends with `use_last: bool = False`. Add four fields immediately after it (still inside the class):

```python
    use_last: bool = False
    platform: str = "anthropic"
    aws_region: str | None = None
    aws_profile: str | None = None
    bedrock_model: str | None = None
```

- [ ] **Step 2: Forward them into SpawnCommandOptions**

In the same file, in `spawn_session_endpoint`, the `SpawnCommandOptions(...)` constructor currently ends with `use_last=request.use_last,`. Add four arguments immediately after it:

```python
            use_last=request.use_last,
            platform=request.platform,
            aws_region=request.aws_region,
            aws_profile=request.aws_profile,
            bedrock_model=request.bedrock_model,
        )
```

- [ ] **Step 3: Verify the app imports cleanly**

Run: `cd backend && source venv/bin/activate && python -c "import app.main"`
Expected: no output, exit code 0.

- [ ] **Step 4: Run the full backend test suite**

Run: `cd backend && source venv/bin/activate && pytest tests/ -q`
Expected: PASS (all tests, including the new platform tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/agent_bridge/router.py
git commit -m "feat(agent-bridge): accept platform fields in spawn API"
```

---

## Task 5: Add platform fields to the frontend request type

**Files:**
- Modify: `frontend/src/features/cc-bridge/types.ts:33-51`

- [ ] **Step 1: Add the fields**

In `frontend/src/features/cc-bridge/types.ts`, the `SpawnSessionRequest` interface currently ends with `use_last?: boolean`. Add four fields immediately after it (still inside the interface):

```typescript
  use_last?: boolean
  platform?: 'anthropic' | 'bedrock'
  aws_region?: string
  aws_profile?: string
  bedrock_model?: string
```

- [ ] **Step 2: Verify the type compiles**

Run: `cd frontend && npx tsc -b`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/cc-bridge/types.ts
git commit -m "feat(agent-bridge): add platform fields to spawn request type"
```

---

## Task 6: Platform selector + Bedrock fields in the dialog

**Files:**
- Modify: `frontend/src/features/cc-bridge/NewSessionDialog.tsx`

This task wires UI state, localStorage persistence, request building, and the rendered controls. The dialog already imports `useState`, `useEffect`, `Input`, `Label`, and the `Select*` family — no new imports needed.

- [ ] **Step 1: Add a localStorage constant and helper near the other module constants**

After the `const CUSTOM_PROJECT_VALUE = '__custom__'` line (currently line 53), add:

```typescript
const PLATFORM_STORAGE_KEY = 'cc-bridge.platform'

type Platform = 'anthropic' | 'bedrock'

interface RememberedPlatform {
  platform: Platform
  aws_region: string
  aws_profile: string
  bedrock_model: string
}

function loadRememberedPlatform(): RememberedPlatform {
  const fallback: RememberedPlatform = { platform: 'anthropic', aws_region: '', aws_profile: '', bedrock_model: '' }
  try {
    const raw = localStorage.getItem(PLATFORM_STORAGE_KEY)
    if (!raw) return fallback
    const parsed = JSON.parse(raw) as Partial<RememberedPlatform>
    return {
      platform: parsed.platform === 'bedrock' ? 'bedrock' : 'anthropic',
      aws_region: typeof parsed.aws_region === 'string' ? parsed.aws_region : '',
      aws_profile: typeof parsed.aws_profile === 'string' ? parsed.aws_profile : '',
      bedrock_model: typeof parsed.bedrock_model === 'string' ? parsed.bedrock_model : '',
    }
  } catch {
    return fallback
  }
}
```

- [ ] **Step 2: Add component state**

After the `const [useLast, setUseLast] = useState(true)` line (currently line 72), add:

```typescript
  const [platform, setPlatform] = useState<Platform>('anthropic')
  const [awsRegion, setAwsRegion] = useState('')
  const [awsProfile, setAwsProfile] = useState('')
  const [bedrockModel, setBedrockModel] = useState('')
```

- [ ] **Step 3: Prefill from localStorage when the dialog opens**

After the existing "set directory from active project" effect (currently ends line 96), add a new effect:

```typescript
  // Prefill the remembered platform selection when the dialog opens.
  useEffect(() => {
    if (!open) return
    const remembered = loadRememberedPlatform()
    setPlatform(remembered.platform)
    setAwsRegion(remembered.aws_region)
    setAwsProfile(remembered.aws_profile)
    setBedrockModel(remembered.bedrock_model)
  }, [open])
```

- [ ] **Step 4: Do NOT reset platform on close**

In the "Reset state when dialog closes" effect (currently lines 122-144), do **not** add platform resets — the prefill effect in Step 3 restores the remembered values on next open, which is the desired behavior. Leave that effect as-is.

- [ ] **Step 5: Persist and include platform in the request**

In `handleLaunch`, immediately after `setSubmitting(true)` (currently line 157), add the persistence write:

```typescript
    try {
      const isBedrock = !isCodex && platform === 'bedrock'
      localStorage.setItem(
        PLATFORM_STORAGE_KEY,
        JSON.stringify({
          platform: isCodex ? 'anthropic' : platform,
          aws_region: awsRegion,
          aws_profile: awsProfile,
          bedrock_model: bedrockModel,
        }),
      )
```

Then extend the `request` object literal (currently lines 160-182) by adding these spread entries immediately before the closing `}` of the object (after the Codex `use_last` block on line 181):

```typescript
        ...(isBedrock && { platform: 'bedrock' as const }),
        ...(isBedrock && awsRegion.trim() && { aws_region: awsRegion.trim() }),
        ...(isBedrock && awsProfile.trim() && { aws_profile: awsProfile.trim() }),
        ...(isBedrock && bedrockModel.trim() && { bedrock_model: bedrockModel.trim() }),
```

Note: the original `const request: SpawnSessionRequest = {` declaration stays; we are only adding fields. The `try {` opening shown in this step replaces the existing `try {` on line 159 so `isBedrock` and the `localStorage.setItem` sit at the top of the try block.

- [ ] **Step 6: Render the Platform selector and Bedrock fields**

In the JSX, replace the entire Claude Code "skip permissions" block (currently lines 430-446, the `{!isCodex && ( ... )}` block) with the platform UI followed by the unchanged skip-permissions UI:

```tsx
          {!isCodex && (
            <div className="space-y-1.5">
              <Label>Platform</Label>
              <Select value={platform} onValueChange={(value) => setPlatform(value as Platform)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="anthropic">Anthropic (default)</SelectItem>
                  <SelectItem value="bedrock">Amazon Bedrock</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          {!isCodex && platform === 'bedrock' && (
            <div className="space-y-3 rounded-md border border-border p-3">
              <p className="text-xs text-muted-foreground">
                Uses AWS credentials from the server environment. Region is usually required.
              </p>
              <div className="space-y-1.5">
                <Label htmlFor="aws-region">AWS Region</Label>
                <Input id="aws-region" value={awsRegion} onChange={(e) => setAwsRegion(e.target.value)} placeholder="e.g. us-east-1" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="aws-profile">AWS Profile (optional)</Label>
                <Input id="aws-profile" value={awsProfile} onChange={(e) => setAwsProfile(e.target.value)} placeholder="e.g. bedrock-prod" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="bedrock-model">Model ARN / ID (optional)</Label>
                <Input id="bedrock-model" value={bedrockModel} onChange={(e) => setBedrockModel(e.target.value)} placeholder="arn:aws:bedrock:..." />
              </div>
            </div>
          )}

          {!isCodex && (
            <div className="space-y-1">
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="skip-permissions"
                  checked={skipPermissions}
                  onCheckedChange={(checked) => setSkipPermissions(checked === true)}
                />
                <Label htmlFor="skip-permissions" className="cursor-pointer">
                  Skip permission prompts
                </Label>
              </div>
              <p className="text-xs text-destructive/80 ml-6">
                Allows Claude to run tools without asking for confirmation
              </p>
            </div>
          )}
```

- [ ] **Step 7: Typecheck and lint**

Run: `cd frontend && npx tsc -b && npm run lint`
Expected: `tsc` clean; ESLint reports no errors in `NewSessionDialog.tsx` or `types.ts` (pre-existing errors in `usePresenceWebSocket.ts` / `api.ts` are unrelated and acceptable).

- [ ] **Step 8: Production build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/features/cc-bridge/NewSessionDialog.tsx
git commit -m "feat(agent-bridge): add platform selector with Bedrock fields to new-session dialog"
```

---

## Task 7: Manual verification + PR

**Files:** none (verification + PR).

- [ ] **Step 1: Start dev servers and smoke-test**

Run: `./scripts/dev.sh`
Then in the browser (Agent Bridge → New Session, Claude Code provider):
- Confirm a **Platform** dropdown shows "Anthropic (default)" and "Amazon Bedrock".
- Anthropic selected → launch a session → confirm it starts normally (unchanged behavior).
- Switch to Bedrock → confirm Region/Profile/Model inputs appear.
- Set a region, launch on an AWS-credentialed host → confirm `claude` starts on Bedrock (e.g. check the session uses Bedrock; `tmux show-environment -t <session>` lists `CLAUDE_CODE_USE_BEDROCK=1` and `AWS_REGION`).
- Close and reopen the dialog → confirm the Bedrock selection + field values are pre-filled (localStorage).

- [ ] **Step 2: Push the branch**

```bash
gh auth switch -u juanrubio
git -c credential.helper= \
    -c credential.helper='!f() { echo username=juanrubio; echo "password=$(gh auth token -u juanrubio)"; }; f' \
    push origin feat/agent-bridge-bedrock-platform
```

- [ ] **Step 3: Open the issue and PR against master**

Create a GitHub issue describing the feature, then open a PR with `## Summary` / `## Test plan` sections referencing it with `Closes #N`, base `master`.

---

## Self-Review

**Spec coverage:**
- Platform picker (Anthropic/Bedrock), Claude Code only → Task 6. ✅
- Bedrock fields Region/Profile/Model → Tasks 5 (type), 6 (UI), mapped to env in Task 1. ✅
- Inherit-from-server credentials (no secret collection/storage) → Task 1 only sets non-secret vars; nothing persisted server-side. ✅
- Env mapping table (`CLAUDE_CODE_USE_BEDROCK`/`AWS_REGION`/`AWS_PROFILE`/`ANTHROPIC_MODEL`) → Task 1 tests + impl. ✅
- Injection via `tmux -e`, Anthropic byte-identical → Task 3 (placement after `-c dir`; `test_anthropic_platform_adds_no_env_flags` asserts `len(argv)==8`). ✅
- Remember last selection in localStorage, non-secret only → Task 6 Steps 1,3,5. ✅
- Backward compat (omitted `platform` defaults to anthropic) → Tasks 2 & 4 defaults; existing spawn tests retained. ✅
- Injection safety (reject `\n`/`\0`) → Task 1 `_clean` + tests. ✅
- Vertex out of scope, door open via `build_platform_env` map → Task 1 returns `{}` for non-bedrock. ✅
- Testing strategy (pytest for builder + spawn argv; tsc/lint/manual for FE) → Tasks 1,3,6,7. ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✅

**Type consistency:** `platform`/`aws_region`/`aws_profile`/`bedrock_model` used identically across `SpawnCommandOptions` (Task 2), `SpawnRequest` (Task 4), `SpawnSessionRequest` (Task 5), and dialog request (Task 6). Env var names match between Task 1 impl and Task 3 assertions (`CLAUDE_CODE_USE_BEDROCK`, `AWS_REGION`, `AWS_PROFILE`, `ANTHROPIC_MODEL`). `build_platform_env` signature `(platform, region=, aws_profile=, model=)` matches the call site in Task 3. ✅
