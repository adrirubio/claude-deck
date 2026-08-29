# Attempt Recovery Tizonia Soak Log

## Run Metadata

- Date/time:
- Operator:
- Independent reviewer:
- Integration merge SHA:
- Deployed Deck SHA:
- PR4 PR/merge SHA:
- Deck version:
- Database backup reference/digest:
- Issue #329 isolation disposition:

## Verified Identity Matrix

| Identity | Expected | Observed | Verified by |
|---|---:|---:|---|
| Preset | `tizonia-v1` / 2 | | |
| Scope | `tizonia/tizonia-openmax-il` / 1 | | |
| Work item | 23 | | |
| Issue | #821 | | |
| PR | #875 | | |
| Owner slot/member | Specialist | | |
| Leader slot/member | Leader, distinct from owner | | |
| Merge policy | human | | |
| Workspace present | yes | | |
| Connected owner sessions | 1 | | |
| Connected Leader sessions | 1 | | |

Never record lease tokens, hashes, capability tokens, GitHub credentials, operator tokens,
commands containing credentials, or environment values.

## Policy and Counters

| Field | Before | Enabled value | Final |
|---|---:|---:|---:|
| Autonomy enabled | false | | |
| Continuation enabled | false | | |
| Max continuation revisions | | | |
| Max total failed heads | | | |
| Max failed heads per revision | | | |
| Max scope paths | | | |
| Max scope commands | | | |
| Product retry count | | | |
| Diagnostic retry count | | | |

## Checkpoint 0 — Deployment Healthy

- Confirmation:
- Health/preflight summary:
- Autonomy off:
- Continuation off:
- PR #875 open/draft/head:
- No live-state mutation observed:
- User approval to continue:

## Checkpoint 1 — Team and Scope

- Confirmation:
- Owner session evidence:
- Leader session evidence:
- Duplicate-session check:
- Preserved attempt identity:
- User approval to continue:

## Checkpoint 2 — Continuation Policy

- Confirmation:
- Atomic policy response:
- Autonomy remained off:
- No proposal/mail/revision transition:
- User approval to continue:

## Checkpoint 3 — Owner Proposal

- Confirmation:
- Recovery nudge event:
- Revision id/phase/status:
- Approval request id/status:
- Request mail id:
- Scope summary and allowed paths/actions:
- Identity preservation evidence:
- User approval to continue:

## Checkpoint 4 — Decision, Delivery, Ack

- Confirmation:
- Leader actor/member/slot:
- Decision/status/message id:
- Delivery message id:
- Owner actor/member/slot:
- Acknowledgement timestamp:
- Duplicate/restart observations:
- User approval to continue:

## Checkpoint 5 — Diagnostic and Restoration

- Confirmation:
- Diagnostic revision id:
- Hosted CI run/check ids:
- Tool fallback used:
- Diagnostic failed heads:
- Baseline head/tree SHA:
- Diagnostic head/tree SHA:
- Restored head/tree SHA:
- Restoration proof/result:
- Product counters unchanged:
- User approval to continue:

## Checkpoint 6 — Implementation and Product CI

- Confirmation:
- Implementation revision/request ids:
- Approved paths/actions:
- Submitted PR head:
- Changed paths:
- Product CI runs/results:
- Revision/product/diagnostic counters:
- User approval to continue:

## Checkpoint 7 — Human Merge and Cleanup

- Confirmation:
- Ready-for-review timestamp/notification:
- Human reviewer/approval:
- PR #875 merge SHA/time:
- Work item merged timestamp:
- Autonomy final state:
- Continuation final state:
- Workspace release evidence:
- Pending authority/mail check:
- Unintended writes check:

## State Transition Timeline

| Time | Work-item status | Phase | Revision | Approval | Mail/event | PR/check state | Notes |
|---|---|---|---:|---|---|---|---|
| | | | | | | | |

## Telemetry and Safety Audit

- Recovery monitor action/block events:
- Continuation monitor events:
- Verification events:
- Secret-redaction check:
- No coordinator impersonation:
- No retry/release of item 23:
- No writes outside PR #875:
- No local Tizonia build/tool installation:
- No auto-merge attempt:

## Findings

| Severity | Finding | Evidence | Issue/PR |
|---|---|---|---|
| | | | |

## Final Gate

- All checkpoints explicitly approved:
- Product CI green:
- Diagnostic tree restored:
- PR #875 human-merged:
- Work item 23 merged:
- Integration branch remains unmerged to `master`:
- Independent review verdict:
