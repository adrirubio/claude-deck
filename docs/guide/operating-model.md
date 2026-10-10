# Factory operating model

This page shows who does what when a Deck team works on a GitHub backlog. Use it with the [Supervised factory playbook](./supervised-factory-playbook.md): this page explains the model, and the playbook gives the procedures.

Select a figure to open it at full size. Parts marked **Planned (v3.1)** come from proposal [#506](https://github.com/adrirubio/claude-deck/issues/506). They are not in Deck 3.0.0. In the figures, green boxes are planned.

::: info Naming
This page calls the human role the **Director**. Agent Mail already uses that name. The Deck 3.0.0 UI and API still say *operator* for the same role, for example the operator token and the operator API. In code, `operator` remains the name of the Director's authority interface. A supervisor uses it only under delegation. A later release will call the token the **Director key** in the UI ([#518](https://github.com/adrirubio/claude-deck/issues/518)).
:::

## Kinds of actor

Each actor is one of three kinds.

| Kind | Actors | Job |
|---|---|---|
| **Human** | The Director | Owns the outcome and the backlog. Makes the retained decisions. |
| **AI agent** | Supervisor, Leader, implementers, verifiers, optional grooming helper | Work that needs judgment: supervision, planning, implementation and review. |
| **Non-agent system** | Deck controller, maintenance script, GitHub | Work that a rule can do: dispatch, leases, Mail, attention signals, the maintenance operation and the record. |

When a rule can do a job, the job belongs in the controller, not in an agent prompt.

## Hierarchy of roles

[![Hierarchy of roles: the Director at the top; the supervisor and the grooming helper as optional staff roles; the Leader; implementers and verifiers; the Deck controller and GitHub as non-agent systems, not ranks](/images/operating-model/hierarchy.svg)](/images/operating-model/hierarchy.svg)

- The line of command is Director → Leader → implementers and verifiers.
- The supervisor and the grooming helper are **staff roles** beside that line. Both are optional. Without a supervisor, the Leader reports directly to the Director.
- The supervisor uses the Director's powers only within the recorded delegation. It does not take the Leader's authority over plans and backlog assessments.
- Each team has one Leader, selected by `leader_slot_id`. The Director chooses the number of implementers and verifiers. Scope limits such as `max_concurrent_dispatched` limit concurrent work, not team size.
- The Deck controller and GitHub are not ranks. The controller enforces the hierarchy with tokens, leases, limits and Mail identity. GitHub holds the backlog and the record.
- An external agent, such as OpenClaw, takes the supervisor role. It is not a second Director.

## The factory

[![The factory: the supervisor, the Deck controller and the team inside the factory boundary; the Director, the grooming helper and GitHub outside it](/images/operating-model/factory.svg)](/images/operating-model/factory.svg)

The **factory** is the supervisor, the Deck controller and the team, working together on the Director's backlog.

Test: if the Director must start, stop, upgrade or repair a part, the part is in the factory.

| Part | In the factory? | Reason |
|---|---|---|
| Supervisor (AI agent) | Yes | The Director starts it and gives it delegation. |
| Deck controller (non-agent) | Yes | Maintenance upgrades and repairs it. |
| Team (AI agents) | Yes | Deck launches its sessions. The Director chooses the roster. |
| GitHub (non-agent) | No | It keeps running when the factory stops. It holds the backlog, and the result goes out there. |
| Director (human) | No | The Director owns the factory and the backlog and keeps the retained decisions. |
| Grooming helper (AI agent) | No | It is optional. It works for the Director, not for the factory. |

### The Director owns the backlog

The Director owns and grooms the GitHub backlog:

- Write and order the issues.
- Set the acceptance conditions.
- Apply the dispatch label. The dispatch label is the Director's "ready" signal.

An optional AI agent can help. It drafts or splits issues for the Director, and the Director decides. The Leader assesses the groomed backlog and selects the next eligible work. The Leader does not own the backlog.

## Two operating modes

[![Two operating modes: in normal running, Deck flags a problem and the Leader or the Director acts; in factory maintenance, the supervisor prepares a fix, the owners hand off, the maintenance script upgrades the controller, and the supervisor checks the state and resumes](/images/operating-model/modes.svg)](/images/operating-model/modes.svg)

**Normal running.** Deck code finds problems: stopped attempts, stalled owners, recovery decisions, review or merge requests and HOLD. The Leader acts on backlog work. The Director makes the retained decisions. A supervisor is optional.

**Factory maintenance.** Maintenance is a Deck feature that the supervisor drives.

- Deck supplies `scripts/factory-maintenance.py` and its checks: owner checkpoints through Mail, pause, backup, proof of termination, deploy and retained-state checks.
- The supervisor decides when to run it, prepares the reviewed fix and the request files, runs the operation and resumes the factory.
- Team sessions keep running through the controller restart. The upgrade is refused if a session binding or generation changes.
- A successful upgrade ends as `deployed_paused`. Resume enables autonomy again and releases the operation's holds. It does not start any agent again.
- While the controller is down, the Deck UI is not available. The parent GitHub issue is the only live status surface.

See the [maintenance runbook](https://github.com/adrirubio/claude-deck/blob/master/docs/deploy/factory-maintenance-operations.md) and the playbook's [maintenance section](./supervised-factory-playbook.md#_9-stop-safely-for-factory-maintenance).

## Why the supervisor runs outside the controller

The supervisor is part of the factory, but it does not run inside the controller process.

- **It cannot upgrade its own host.** An upgrade stops the controller, proves termination and restarts it. An agent inside the controller stops when the controller stops.
- **A watchdog must not fail with the thing it watches.** If the controller stalls or crashes, an internal supervisor stops too, and nobody sees the failure.
- **A controller that repairs itself is unsafe.** An internal agent with permission to change and deploy Deck makes the safety model much harder to understand.

| Duty | Owner | Kind |
|---|---|---|
| Own and groom the backlog | Director, optionally helped by an agent | Human |
| Detect stalls, stopped attempts, holds and required decisions | Deck controller | Non-agent |
| Assess the groomed backlog, approve plans, select the next eligible work | Team Leader | AI agent |
| Repair, upgrade and roll back the factory | Supervisor, with the maintenance script | AI agent and non-agent |
| Retained decisions: publication, budgets, models, security HOLD | Director | Human |

## One campaign, start to finish

| Actor | Groom | Prepare | Run | Decision | Maintenance | Finish |
|---|---|---|---|---|---|---|
| **Director** (human) | Write and order issues; apply the dispatch label | Write the outcome and delegation; authorize the start | Groom at any time; read the summary | Approve or decide on GitHub | Only for a security HOLD | Approve publication |
| **Supervisor** (AI agent, optional) | Draft issues for the Director | Run startup checks | Fix routine blockers within delegation | Prepare the exact request and evidence | Fix, hand off, run the reviewed upgrade | Reconcile records; disable dispatch |
| **Deck controller** (non-agent) | Poll labelled issues | Store scopes, leases and Mail identity | Dispatch; bound attempts; show signals | List the human action | Record the operation; preserve authority and leases | Show the result |
| **Leader and team** (AI agents) | Optional readiness assessment | Mail canary | Assess, plan, implement, verify | Independent work continues | Owner checkpoint, then hold | Close issues |
| **GitHub** (non-agent) | The Director's backlog | Parent issue and backlog | PRs and required CI | Exact instructions in the issue | Only live status surface | Final record |

## Supervisor heartbeat — Planned (v3.1)

<p>
  <a href="/docs/images/operating-model/supervisor-tick.svg"><img src="/images/operating-model/supervisor-tick.svg" alt="Supervisor tick: read, act if delegated, publish if changed, check in" width="48%"></a>
  <a href="/docs/images/operating-model/heartbeat-status.svg"><img src="/images/operating-model/heartbeat-status.svg" alt="The controller derives Healthy, Late or Absent from the last check-in and the clock" width="48%"></a>
</p>

The supervisor keeps no state between ticks. It reads Deck and GitHub again on each tick, so a harness exit or reboot loses nothing. Replay safety comes from the controller's existing `replay_key` and `operation_id` records.

At the end of each tick, the supervisor promises its next check (`next_check_at`). The controller compares that promise with the clock. The supervisor never reports its own health.

| Status | Meaning |
|---|---|
| None | No supervisor is registered. This is not an error. |
| Healthy | The promised check has not passed. |
| Late | The check is overdue. Work can still run. |
| Absent | No check-in, or the check is overdue past the threshold. |

## Director's summary — Planned (v3.1)

One summary at the top of the Overview answers three questions: Do I need to act? Is anyone watching? What work remains? Most lines collect data that Deck 3.0.0 already has. The supervisor line and the team total for remaining work are new. See [#506](https://github.com/adrirubio/claude-deck/issues/506) and [#508](https://github.com/adrirubio/claude-deck/issues/508).

```text
Publish the next release                      Parent issue: #NNN
Outcome:     Release tagged, website live, final record posted
Supervisor:  Healthy. Checked 2 minutes ago. Next check in 8 minutes.
Attention:   None open
Remaining:   Publish the release and the website. Estimate: under 1 active hour.
Next actor:  You
Your action: Review the previews and approve publication on #NNN at SHA <sha>.
```
