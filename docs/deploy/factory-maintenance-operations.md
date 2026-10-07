# Factory maintenance and current summaries

## Current GitHub summary

The team can select a compact summary for its issue and PR bodies. The summary is a report. It grants no approval or execution authority.

Use `deck_render_github_summary` with the latest body and public summary fields. The renderer updates only `deck:current-summary`. It preserves human requirements, operator-action records, remaining-work records and history outside that section.

The summary states the goal, status, completed work, remaining work, estimate, waiting, next action and human action. Active effort needs a range, confidence and scope. Use Unknown when there is no reliable estimate. State unestimated waiting separately. A source SHA identifies a public checkpoint; it does not prove acceptance.

Use one responsible body publisher for each team. Reconcile concurrent edits before publication. The optional expected body hash checks the input supplied to the renderer. It is not an atomic GitHub write guard. Read back the published body through existing authorized access.

Do not append competing current-status paragraphs. Keep detailed evidence in linked records. Label old estimates and states as history. Clear or supersede operator-action records through their existing process.

The standalone renderer uses the same protocol:

```sh
python scripts/factory-summary.py \
  --body-file /tmp/issue-body.md \
  --summary-file /tmp/current-summary.json \
  --output-file /tmp/rendered-issue-body.md
```

The JSON file contains the required public fields and an aware `reported_at` timestamp. Optional fields are `waiting`, `source_sha`, `effort_low_minutes`, `effort_high_minutes`, `confidence` and `effort_scope`. The output file must not exist. This command performs no GitHub write.

## Recorded observation pause

A repository delivery policy can set `owner_observation_wait_seconds` from 30 to 1800 seconds. The default is disabled. This option requires native owner contact. `owner_observation_resume_seconds` sets the operator recovery window, from 60 to 3600 seconds; its default is 900.

Both owner monitors use the usual idle nudge and grace first. Unknown native evidence does not renew contact. A bound, live owner with actual approval and ACK can enter the extra bounded wait. At its deadline, Deck records an escalation and preserves the active revision. Dead, stale, mismatched or ambiguous owners cannot use this path.

The operator reads `GET /api/v1/agent-teams/presets/{preset}/work-items/{item}/observation-pauses`. The response states the deadlines, required action and completion condition. It excludes the private authority digest, lease and credentials.

The operator calls `POST .../resume-observation` with `pause_id` and a short `reason`. Deck checks the recorded attempt, approval, ACK, scope, counters, owner, current authenticated generation and actual process lifetime. Changed or expired context is refused. An exact repeated request reports its historical result; it performs no second recovery.

Recovery starts one ordinary nudge grace. It does not report agent progress or alter the original effort clock. The owner must then report actual progress. It creates no proposal, ACK, revision or budget. Recovery of a never-approved expired proposal remains outside this operation.

## Reusable maintenance commands

Use the same command with private installation and request JSON files:

```sh
python scripts/factory-maintenance.py upgrade \
  --profile /private/installation.json --request /private/upgrade.json --execute

python scripts/factory-maintenance.py integration-update \
  --profile /private/installation.json --request /private/integration-update.json --execute
```

Omit `--execute` to validate the data shape only. That does not run the operational checks. The files must be regular files owned by the current operator or root, with mode 0600. Duplicate JSON fields and unknown options are refused. The command does not print process output, credentials or native transcripts.

`InstallationProfile` defines the loopback API URL, controller checkout, database, operator environment file, state directory, service and active supervisor unit. It also defines HOLD paths, the arming marker, GitHub and workspace OS users, protected controller files and version-record fields. All paths are explicit. The profile contains no executable hook. Read the exact schema in `backend/app/services/maintenance_operations.py`.

Every active owner supplies a current Mail checkpoint payload:

```json
{
  "kind": "factory_maintenance_checkpoint",
  "operation": "controller_upgrade",
  "work_item_id": 123,
  "source_head": "0123456789abcdef0123456789abcdef01234567",
  "no_inflight_operations": true
}
```

Use `integration_update` for a source update. The operator request names the actual Mail message ID. The operation checks the current owner, authenticated generation, process binding, source head and checkpoint age. A checkpoint is a handoff claim, not approval or proof that a hidden background process cannot exist.

### Controller upgrade

The request binds the old and target heads, clean candidate, accepted PRs and configured successful checks. It names every reviewed changed file and its SHA256. It also binds the runtime review file and a successful clean-source check receipt with its actual log hash. The runtime review must begin with `ACCEPT` and include the target head and canonical reviewed-file-map digest.

The operation pauses autonomy, removes the arming marker and waits for the active supervisor to observe the pause. It backs up the database and proves controller termination before changing its source. It preserves native sessions, owner sources, recorded authority and protected files. It changes only declared version fields. After start, it checks health and retained state. Success reports `deployed_paused`; activation remains a separate operation.

A failure reports `paused_needs_inspection`. The command does not infer success from a live PID or a timeout. It leaves autonomy paused and records the uncertainty. The supervisor stays active. An existing HOLD prevents execution. This source upgrade does not install dependencies or publish a new UI bundle; those changes need their normal accepted artifact procedure.

### Accepted integration update

Each attempt's recorded policy selects `accepted_base_update`: `disabled`, `fast_forward` or `merge`. Disabled is the default. Normal policy adoption rules apply.

The operation requires an approved integration PR, its exact merged tip, successful configured checks, the configured repository and base branch, a clean owner checkpoint and current workspace binding. It reads the actual remote tip. It keeps supervision active and does not disarm autonomy. Checks cover this item's authority and owner; another team's valid work does not invalidate this handoff.

A successful update retains both previous source history and the accepted base history. A conflict preserves commits and conflict files. The operator outcome route records `integration_update_conflict` without superseding approval or resetting counters. Failed notice delivery stays uncertain in the operation record. Resolve the conflict through the existing coordination process; the operation grants no arbitrary Git command, force push or merge-policy bypass.

## Adoption and evidence

Upstream issue #482 owns these generic features. Existing teams retain their recorded policy until explicit adoption. Keep each team's task gates. Deploy at a clean handoff. Do not restart a native member to activate communication guidance during an implementation batch.

Focused tests use disposable databases and real disposable Git repositories. Controller service tests use a mock adapter; they are not a live deployment. Final review, required hosted CI and the installation's concrete version evidence remain necessary.
