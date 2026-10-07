# Factory delivery practices

Use these practices with the existing dispatch, approval, review, and merge rules.
The helpers below grant no authority. Use only commands allowed by the approved task scope.

## Complete a correction batch before review

The Leader assigns one owner and a bounded batch of related findings.
For shared consumers, complete the full actor, replay, state, and failure contracts together.
Request final review when the batch is complete and its checks pass.
Reviewers can give early design advice. They must label this advice as incomplete review.

Publish a useful checkpoint after a coherent substep and before a long pause or handoff.
Use a fast-forward push to the assigned task branch.
If safe publication is delayed for 30 minutes, report the reason and next checkpoint.
Do not create empty commits or request final review to satisfy a timer.

## Check the source early

Install the pinned check dependency from `scripts/factory-check-requirements.txt`.
Run the undefined-name check before each Python checkpoint:

```sh
python3 scripts/factory-static-check.py --base <accepted-base-sha>
```

For a completed shared-service batch, the owner runs the agreed broad backend suite once before publication.
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
