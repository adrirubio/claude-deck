# Factory delivery practices

Use these practices with the existing dispatch, approval, review, and merge rules.
The helpers below grant no authority. Use only commands allowed by the approved task scope.

## Configure each team and repository

Each team repository scope has a delivery policy and a revision number.
Use the operator API to change scope defaults. New dispatch attempts record those defaults.
An existing attempt keeps its recorded policy. An active attempt from an older runtime keeps the legacy policy.
An operator can apply the current scope policy to an existing attempt through a separate API.
This operation needs the expected nonce, scope revision, policy revision, and a reason.
It cannot change work that is verifying or awaiting review. Policy changes have an append-only history.

Use `PATCH /api/v1/agent-teams/github-scopes/{scope_id}/delivery-policy` with these fields:

```json
{
  "expected_revision": 1,
  "reason": "Use the hosted project checks and native owner contact.",
  "policy": {
    "required_checks": [
      {"name": "Full backend regression tests", "app_slug": "github-actions"},
      {"name": "Changed Python undefined names", "app_slug": "github-actions"}
    ],
    "owner_contact": "native",
    "broad_checks": "hosted",
    "checkpoint_delay_report_seconds": null,
    "caller_inventory_required": true,
    "regression_proof_required": true
  }
}
```

Check scope responses for the current defaults. Check work-item responses for the effective attempt policy.
Read recorded changes through `GET /api/v1/agent-teams/github-scopes/{scope_id}/delivery-policy/history`.
Apply defaults explicitly through `PATCH /api/v1/agent-teams/github-work-items/{item_id}/delivery-policy`.
Supply `expected_dispatch_nonce`, `expected_scope_revision`, `expected_policy_revision`, `target_policy_revision`, and `reason`.

Required jobs must finish with `success` on the candidate commit and come from the configured application.
Missing, pending, cancelled, failed, skipped, and neutral required jobs do not satisfy the gate.
A combined commit status cannot replace a required job. The same rule applies to review readiness and automatic merge.
Projects choose their own check names. Deck does not assume a language, team name, harness, or model.
Ownership, approvals, lease expiry, finite budgets, and host resource locks remain separate factory rules.

Keep effort limits and caller inventories in each work-item plan.
Record active work and waiting intervals. Do not infer active effort from wall time, Mail volume, or native liveness.
At the agreed limit, stop scope work and request the operator's decision. Do not split acceptance criteria automatically.

## Complete a correction batch before review

The Leader assigns one owner and a bounded batch of related findings.
For shared consumers, complete the full actor, replay, state, and failure contracts together.
Request final review when the batch is complete and its checks pass.
Reviewers can give early design advice. They must label this advice as incomplete review.

Publish a useful checkpoint after a coherent substep and before a long pause or handoff.
Use a fast-forward push to the assigned task branch.
If the policy sets a publication delay interval, report the reason and next checkpoint after that interval.
Do not create empty commits or request final review to satisfy a timer.

## Check the source early

Install the pinned check dependency from `scripts/factory-check-requirements.txt`.
Run the undefined-name check before each Python checkpoint:

```sh
python3 scripts/factory-static-check.py --base <accepted-base-sha>
```

With `broad_checks: local`, the owner runs the agreed broad suite once before publication of a completed shared-service batch.
With `broad_checks: hosted`, focused local checks are sufficient before publication. The required hosted jobs supply broad verification.
Select hosted broad checks only after the full-suite workflow and required-job gate are deployed.
The shared backend workflow runs all `backend/tests`. The optional Pi integration test uses a disposable tmux socket and skips when its local tools or dependencies are absent.
Do not replace the full suite with a directory allowlist. Record the reason for any explicit exclusion.
Use the required host resource lock for a heavy local run.
B4 runs independent checks for changed contracts. Root reads the evidence and source.
Reuse valid results for unchanged source and dependencies. Keep required hosted checks on the final PR head.
Do not add a broad type checker until its baseline and useful rules are agreed.

## Record checks automatically

Commit the candidate locally. Store receipts outside its Git worktree:

```sh
python3 scripts/factory-check.py --output-dir /tmp/check-evidence --cwd backend -- python3 -m pytest tests/factory -q
```

The helper records the command, working directory, commit, tree, times, exit code, and log hash.
It rejects dirty source and returns failure when source identity changes during the run.
A receipt with `eligible: true` and `exit_code: 0` is a check result.
It does not prove that the command covers every requirement or uses the correct environment.
Record dependency or fixture changes when reusing a result.
Inspect private logs before publishing any evidence. Publish safe summaries and links.
Prefer hosted checks for final verification. Do not repeat a broad local suite to create another receipt.

## Keep one finding list

The Leader keeps the authoritative review list. Give each finding a stable ID.
Each row names its requirement, source location, decisive check, and state.
Use `open`, `claimed_fixed`, or `verified`.
The owner changes a finding to `claimed_fixed` and names the complete candidate SHA.
The independent reviewer changes it to `verified` after checking the evidence.
For regressions, link the failure before the fix and the passing result after it.
Use the source that contains the specific defect. Use the original rejected head when the defect exists there.
For a defect introduced later, name the later defective head. A passing original head alone does not reopen a finding.
The failure must be an assertion about the defect. Import, fixture, helper, and signature errors do not count.
Keep baseline production source intact. Record the test and any compatibility adapter used for both runs.
Store external tests and adapters outside the clean source worktree. Record their hashes with the evidence.
Do not fabricate a baseline failure. Use an existing failing run when it proves the same defect.
For documentation or source inspection, explain why a regression check does not apply.

```json
{
  "version": 1,
  "findings": [{
    "id": "C08.1",
    "location": "backend/app/services/example.py:42",
    "requirement": "Record the authenticated actor.",
    "decisive_check": "test_real_consumer_records_authenticated_actor",
    "state": "open"
  }]
}
```

For a fixed finding, add `fixed_head` with the full commit SHA.
For a verified regression, add `evidence` with `kind: regression`, `reviewer`, `before`, and `after` links.
For verified inspection, use `kind: inspection`, `reviewer`, `reason`, and an `after` evidence link.

```sh
python3 scripts/factory-findings.py findings.json --head <review-sha>
python3 scripts/factory-findings.py findings.json --head <review-sha> --require-verified
```

This validator checks the record format. Existing authenticated reviews decide acceptance.
Reopen a finding when changed source invalidates its evidence.
Do not rewrite unaffected requirements or restart unrelated reviews after a focused fix.

When the policy requires a caller inventory, record every real entry point before shared-consumer edits.
Name the actor source, action, transaction boundary, outcomes, requirement, and decisive check.
Keep inventory rows inside their parent finding or in a separate inventory list. Preserve the number of finding groups.
The independent reviewer checks the inventory once as early design advice. This advice does not accept the implementation.

## Renew owner contact from native work

With `owner_contact: native`, fresh working evidence can renew contact for the bound owner.
The scheduler rechecks the member, authenticated session, conversation, process, workspace acquisition, and active revision.
Only the contact timestamp changes. The event timestamp supplies contact; repeated polls do not extend the same event.
Unknown, idle, stale, mismatched, retired, and expired work cannot renew contact.
An acknowledged active revision does not expire merely because its proposal expiry passed.
The existing owner idle and nudge limits still apply. Each policy can configure these two intervals.
Supported observers replace routine reports while fresh native evidence is available.
When the observer cannot supply that evidence, use the existing owner progress report and nudge flow.
Send Mail when work is blocked, a batch is complete, a decision is needed, or scope is unclear.
Native liveness does not prove progress, satisfy an ACK, grant approval, or measure active effort.

## Keep the human view brief

Keep one current summary near the start of the main issue and PR.
Use three short lines: Remaining, Estimate, Next.
Include explicit current operator actions and a human review summary when needed.
Put the complete requirements and history behind stable links. Do not delete acceptance requirements.
Append historical checkpoints to comments. Do not repeat the current status in several body sections.

## Preserve finite failure budgets

A checkpoint is not a review submission.
For continuation work, keep the revision active until its complete candidate is ready.
Submit the final head through the existing authenticated completion flow.
Ordinary fixes inside an active approved scope need no new Root approval.
An exhausted attempt still needs the supported continuation approval and owner acknowledgement.
Do not reset retry counters, change leases, or give each correction a new budget.
Keep the current P05 scope intact. Split later packages before dispatch when their layers can be reviewed independently.
