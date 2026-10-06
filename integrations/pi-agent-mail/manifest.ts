export const manifest = [
  {
    "name": "deck_ack_continuation",
    "description": "Acknowledge and activate one delivered continuation revision.",
    "inputSchema": {
      "properties": {
        "work_item_id": {
          "title": "Work Item Id",
          "type": "integer"
        },
        "revision": {
          "title": "Revision",
          "type": "integer"
        },
        "dispatch_nonce": {
          "title": "Dispatch Nonce",
          "type": "string"
        },
        "lease_token": {
          "title": "Lease Token",
          "type": "string"
        }
      },
      "required": [
        "work_item_id",
        "revision",
        "dispatch_nonce",
        "lease_token"
      ],
      "title": "deck_ack_continuationArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_ack_message",
    "description": "Acknowledge a message. Acking an answer to your context request closes it; acking\n    a handoff addressed to you accepts and closes the handoff.",
    "inputSchema": {
      "properties": {
        "message_id": {
          "title": "Message Id",
          "type": "integer"
        }
      },
      "required": [
        "message_id"
      ],
      "title": "deck_ack_messageArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_approve_work_item",
    "description": "Approve or reject a normalized initial-plan request as its designated Leader.\n\n    Pass approval_request_id from deck_request_work_item_approval. A rejection opens\n    the next round automatically when one remains.\n    ",
    "inputSchema": {
      "properties": {
        "work_item_id": {
          "title": "Work Item Id",
          "type": "integer"
        },
        "dispatch_nonce": {
          "title": "Dispatch Nonce",
          "type": "string"
        },
        "decision": {
          "title": "Decision",
          "type": "string"
        },
        "reason": {
          "title": "Reason",
          "type": "string"
        },
        "approval_request_id": {
          "title": "Approval Request Id",
          "type": "integer"
        }
      },
      "required": [
        "work_item_id",
        "dispatch_nonce",
        "decision",
        "reason",
        "approval_request_id"
      ],
      "title": "deck_approve_work_itemArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_attach_image_to_bridge_session",
    "description": "Upload a local image file to an Agent Bridge tmux session, paste the\n    generated image-path prompt, and optionally submit it. target is the\n    tmux target from Agent Bridge, such as \"repo-1234:0.0\". file_path must\n    point to an image readable by this trusted MCP server process.",
    "inputSchema": {
      "properties": {
        "target": {
          "title": "Target",
          "type": "string"
        },
        "file_path": {
          "title": "File Path",
          "type": "string"
        },
        "submit": {
          "default": false,
          "title": "Submit",
          "type": "boolean"
        },
        "prompt": {
          "default": "",
          "title": "Prompt",
          "type": "string"
        }
      },
      "required": [
        "target",
        "file_path"
      ],
      "title": "deck_attach_image_to_bridge_sessionArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_check_inbox",
    "description": "Read your Agent Mail inbox, including messages, context requests, handoffs, and\n    answers. Returned messages are marked read. Check before major work and after\n    finishing a task.",
    "inputSchema": {
      "properties": {
        "unread_only": {
          "default": true,
          "title": "Unread Only",
          "type": "boolean"
        },
        "limit": {
          "default": 20,
          "title": "Limit",
          "type": "integer"
        }
      },
      "title": "deck_check_inboxArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_create_handoff",
    "description": "Hand work over to another Agent Mail participant with a summary, touched files, and next\n    steps. The recipient acknowledges it to accept the handoff.",
    "inputSchema": {
      "properties": {
        "to_member_id": {
          "title": "To Member Id",
          "type": "integer"
        },
        "summary": {
          "title": "Summary",
          "type": "string"
        },
        "files": {
          "anyOf": [
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Files"
        },
        "next_steps": {
          "anyOf": [
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Next Steps"
        }
      },
      "required": [
        "to_member_id",
        "summary"
      ],
      "title": "deck_create_handoffArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_create_team",
    "description": "Create an Agent Team preset.\n\n    Valid providers: claude-code, codex-cli, copilot-cli, opencode-cli.\n    Common slot fields: display_name, provider, repo_path, role, charter,\n    ui_color, launch_mode, launch_options. ui_color values: blue, purple,\n    green, amber, red, cyan, slate. Provider launch modes/options:\n    - claude-code: modes plain/worktree/resume; launch_options\n      skip_permissions, platform, aws_region, aws_profile, bedrock_model,\n      prompt, session_id, project_folder, worktree_name.\n    - codex-cli: modes plain/resume/fork; launch_options model, profile,\n      profile_v2, sandbox, approval_policy, search, no_alt_screen,\n      dangerously_bypass_approvals_and_sandbox, use_last, session_id,\n      platform, aws_region, aws_profile, bedrock_model, reasoning_effort,\n      prompt. reasoning_effort: low/medium/high/xhigh.\n    - copilot-cli: modes plain/resume; launch_options model, agent,\n      context_tier, reasoning_effort, plan, remote, allow_all, no_ask_user,\n      skip_permissions, dangerously_bypass_approvals_and_sandbox, use_last,\n      session_id, prompt. reasoning_effort: none/low/medium/high/xhigh/max;\n      context_tier: default/long_context. Bedrock launch options are not\n      supported for copilot-cli.\n    - opencode-cli: modes plain/resume; launch_options model, agent,\n      use_last, session_id, platform, aws_region, aws_profile, prompt.\n      OpenCode TUI launch does not support reasoning_effort.\n    Use deck_plan_team_launch before launch.\n    ",
    "inputSchema": {
      "properties": {
        "name": {
          "title": "Name",
          "type": "string"
        },
        "description": {
          "default": "",
          "title": "Description",
          "type": "string"
        },
        "slots": {
          "anyOf": [
            {
              "items": {
                "additionalProperties": true,
                "type": "object"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Slots"
        }
      },
      "required": [
        "name"
      ],
      "title": "deck_create_teamArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_decide_continuation",
    "description": "Approve or reject one explicit continuation authority request.",
    "inputSchema": {
      "properties": {
        "approval_request_id": {
          "title": "Approval Request Id",
          "type": "integer"
        },
        "work_item_id": {
          "title": "Work Item Id",
          "type": "integer"
        },
        "dispatch_nonce": {
          "title": "Dispatch Nonce",
          "type": "string"
        },
        "decision": {
          "title": "Decision",
          "type": "string"
        },
        "reason": {
          "title": "Reason",
          "type": "string"
        }
      },
      "required": [
        "approval_request_id",
        "work_item_id",
        "dispatch_nonce",
        "decision",
        "reason"
      ],
      "title": "deck_decide_continuationArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_get_backlog_coordination",
    "description": "Current Leader: read the assigned backlog, observations and request version.\n\n    Reconcile reviewed dependency/milestone gates and already-landed fixes even for\n    issues without a dispatch-ready label. While ON, this read returns a short-lived\n    snapshot_token for publishing a current assessment without another notification.\n    Read again immediately before reporting; keep the token private. OFF/HOLD reads\n    grant no publication challenge. This tool grants no implementation authority.\n    ",
    "inputSchema": {
      "properties": {
        "scope_id": {
          "title": "Scope Id",
          "type": "integer"
        }
      },
      "required": [
        "scope_id"
      ],
      "title": "deck_get_backlog_coordinationArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_get_operator_action_contexts",
    "description": "Read current requests and issue instruction templates. This grants no authority.\n\n    The Leader must publish completed templates near the start of each main\n    GitHub issue. Use the returned section markers. Fill every WRITE_ placeholder.\n    State the reason, responsible person, exact steps, evidence and completion\n    condition. Use a UTC update time. Keep existing content and other scopes.\n    Use existing authorized GitHub access. Never copy tokens, leases, nonces,\n    private paths, prompts or raw logs into GitHub. The read does not write to\n    GitHub, retry work, release a lease, approve a plan or merge a PR.\n    Missing or stale instructions appear as Action details pending in Deck.\n    ",
    "inputSchema": {
      "properties": {
        "preset_id": {
          "title": "Preset Id",
          "type": "integer"
        }
      },
      "required": [
        "preset_id"
      ],
      "title": "deck_get_operator_action_contextsArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_get_work_item_context",
    "description": "Claim the current owner's continuation context, including the persisted\n    branch, approval round, workspace, and lease capability after a handoff or\n    session restart.",
    "inputSchema": {
      "properties": {
        "work_item_id": {
          "title": "Work Item Id",
          "type": "integer"
        }
      },
      "required": [
        "work_item_id"
      ],
      "title": "deck_get_work_item_contextArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_launch_team",
    "description": "Launch an Agent Team preset.\n\n    Call deck_plan_team_launch first and pass its plan_hash as\n    confirm_plan_hash. Forced respawn and force_without_plan require an\n    operator and are not available through this agent tool. Launch behavior\n    uses the per-provider launch_options accepted by deck_create_team;\n    validation errors include machine-readable\n    block_code values when available.\n    ",
    "inputSchema": {
      "properties": {
        "preset_id": {
          "title": "Preset Id",
          "type": "integer"
        },
        "confirm_plan_hash": {
          "default": "",
          "title": "Confirm Plan Hash",
          "type": "string"
        },
        "reuse_existing": {
          "default": true,
          "title": "Reuse Existing",
          "type": "boolean"
        },
        "slot_ids": {
          "anyOf": [
            {
              "items": {
                "type": "integer"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Slot Ids"
        },
        "force_without_plan": {
          "default": false,
          "title": "Force Without Plan",
          "type": "boolean"
        }
      },
      "required": [
        "preset_id"
      ],
      "title": "deck_launch_teamArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_list_bridge_attachments",
    "description": "List recent image attachments for an Agent Bridge tmux target.",
    "inputSchema": {
      "properties": {
        "target": {
          "title": "Target",
          "type": "string"
        }
      },
      "required": [
        "target"
      ],
      "title": "deck_list_bridge_attachmentsArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_list_scope_revisions",
    "description": "List safe continuation authority history for one work item.",
    "inputSchema": {
      "properties": {
        "work_item_id": {
          "title": "Work Item Id",
          "type": "integer"
        }
      },
      "required": [
        "work_item_id"
      ],
      "title": "deck_list_scope_revisionsArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_list_team",
    "description": "List all local Agent Mail participants Claude Deck knows about, including member\n    ids, display names, roles, repos, team slots, charters, and live statuses.",
    "inputSchema": {
      "properties": {},
      "title": "deck_list_teamArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_list_teams",
    "description": "List saved Claude Deck Agent Team presets. Returns preset ids, names,\n    descriptions, and slots with launch options and validation warnings.",
    "inputSchema": {
      "properties": {},
      "title": "deck_list_teamsArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_list_work_items",
    "description": "Leader-only: list this team's GitHub dispatch work items with their\n    work_item_id and issue_number. Defaults to escalated items (pass status=\"\"\n    for all). Use at team start to resolve which escalated dependents are now\n    unblocked (per your dependency map) so you can call deck_retry_work_item\n    with the correct work_item_id.\n    ",
    "inputSchema": {
      "properties": {
        "status": {
          "default": "escalated",
          "title": "Status",
          "type": "string"
        },
        "limit": {
          "default": 100,
          "title": "Limit",
          "type": "integer"
        }
      },
      "title": "deck_list_work_itemsArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_paste_bridge_attachment",
    "description": "Paste an existing Agent Bridge attachment prompt into a tmux session,\n    optionally submitting it with Enter.",
    "inputSchema": {
      "properties": {
        "target": {
          "title": "Target",
          "type": "string"
        },
        "attachment_id": {
          "title": "Attachment Id",
          "type": "integer"
        },
        "submit": {
          "default": false,
          "title": "Submit",
          "type": "boolean"
        }
      },
      "required": [
        "target",
        "attachment_id"
      ],
      "title": "deck_paste_bridge_attachmentArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_plan_team_launch",
    "description": "Plan an Agent Team launch and return the plan_hash required by\n    deck_launch_team. Agent sessions cannot include disabled slots or force\n    replacement of a running session; those options require an operator.",
    "inputSchema": {
      "properties": {
        "preset_id": {
          "title": "Preset Id",
          "type": "integer"
        },
        "reuse_existing": {
          "default": true,
          "title": "Reuse Existing",
          "type": "boolean"
        },
        "slot_ids": {
          "anyOf": [
            {
              "items": {
                "type": "integer"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Slot Ids"
        },
        "include_disabled": {
          "default": false,
          "title": "Include Disabled",
          "type": "boolean"
        }
      },
      "required": [
        "preset_id"
      ],
      "title": "deck_plan_team_launchArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_prepare_operator_action_contexts",
    "description": "Prepare issue records for the current Leader's intended human requests.\n\n    Entries use the backlog assessment schema. Supply only the assigned issues\n    that have intended human_actions. Use required_actor operator. Up to sixteen\n    unique actions and eight PRs are allowed. PRs need their full expected head.\n    Inspection actions require a current stopped attempt.\n\n    Publish the completed templates in the main issue body before requesting\n    input. Preserve other issue facts and other scopes. Clear or supersede old\n    records when the request changes. A PR record must include its target and\n    reviewed head. Do not leave instructions only in Mail or comments.\n    After publication, read fresh backlog coordination and pass its private\n    snapshot_token to the normal assessment tool. This preparation is read-only\n    and grants no approval, lease, retry, merge or milestone authority.\n    ",
    "inputSchema": {
      "properties": {
        "scope_id": {
          "title": "Scope Id",
          "type": "integer"
        },
        "entries": {
          "items": {
            "additionalProperties": true,
            "type": "object"
          },
          "title": "Entries",
          "type": "array"
        }
      },
      "required": [
        "scope_id",
        "entries"
      ],
      "title": "deck_prepare_operator_action_contextsArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_reply",
    "description": "Reply in an existing thread. If the root is a pending context request addressed\n    to you, your reply is recorded as the answer and resolves it.",
    "inputSchema": {
      "properties": {
        "thread_root_id": {
          "title": "Thread Root Id",
          "type": "integer"
        },
        "body": {
          "title": "Body",
          "type": "string"
        }
      },
      "required": [
        "thread_root_id",
        "body"
      ],
      "title": "deck_replyArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_report_backlog_assessment",
    "description": "Current Leader: submit one advisory disposition per assigned issue.\n\n    Each entry: issue_number; disposition (eligible, dependency_blocked,\n    human_decision_blocked, resource_blocked, completed, needs_scope_clarification,\n    standing); reason (admission, dependency, m1a_acceptance, pilot_decision,\n    m1b_acceptance, authority_prerequisite, human_merge, review_evidence, resource,\n    owner, scope_clarification, complete, standing, unknown); required_actor\n    (leader, operator, owner, reviewer, none); evidence_issue_numbers (assigned\n    positive issue numbers, at least one). Unknown/out-of-scope evidence is refused.\n\n    An entry may also include human_actions (at most four per entry,16 overall):\n    kind (review_pr, merge_pr, pilot_decision, milestone_acceptance, provide_evidence,\n    scope_clarification, inspect_attempt, inspect_checkpoint); readiness (requested, waiting_for_prerequisites);\n    prerequisite_issue_numbers (assigned references). PR actions require\n    pull_request_number and expected_head_sha (full40-character lowercase SHA;\n    at most eight distinct PRs). Fresh same-repository/open/head checks are required.\n    Include standing documentation PRs as explicit human requests in their assigned\n    standing issue. Distinguish current review requests from future pilot/acceptance\n    gates; never mark a gated decision requested before its prerequisites permit it.\n    These requests appear above the Roster and Autonomy tabs and grant no authority.\n    Human actions require required_actor operator. Before reporting requested,\n    prepare and publish current issue instructions with\n    deck_prepare_operator_action_contexts. Missing, stale or changed records are\n    refused. Clear or supersede replaced records in the issue body first.\n    Automatic dispatch requests use deck_get_operator_action_contexts templates.\n\n    Pass snapshot_token from a fresh deck_get_backlog_coordination read to publish\n    while already working, even when notification quota is exhausted or no request\n    has been sent (request_sequence may be zero). This spends no notification quota.\n    A changed or expired read requires a fresh read; never reuse it for a correction.\n    Omitting the token retains the legacy one-assessment-per-notification protocol.\n\n    Assessments do not approve implementation, add dispatch labels, release leases,\n    change policy or satisfy human merge/milestone gates. Stale requests, OFF/HOLD\n    and a changed Leader binding are refused. Use the existing authorized admission\n    workflow only after verifying every reviewed gate and resource assignment.\n    ",
    "inputSchema": {
      "properties": {
        "scope_id": {
          "title": "Scope Id",
          "type": "integer"
        },
        "generation": {
          "title": "Generation",
          "type": "integer"
        },
        "request_sequence": {
          "title": "Request Sequence",
          "type": "integer"
        },
        "entries": {
          "items": {
            "additionalProperties": true,
            "type": "object"
          },
          "title": "Entries",
          "type": "array"
        },
        "snapshot_token": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Snapshot Token"
        }
      },
      "required": [
        "scope_id",
        "generation",
        "request_sequence",
        "entries"
      ],
      "title": "deck_report_backlog_assessmentArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_report_dispatch_status",
    "description": "Report progress on a Claude-Deck-dispatched GitHub issue back to the brain.\n\n    status is one of: triaging, ack_received, in_progress, pr_ready (with\n    head_ref), pr_opened (with pr_number), handoff_initiated (with\n    reassign_to_slot_id), handoff_accepted, blocked, continuation_completed,\n    diagnostic_completed, workspace_released. Both completion statuses require\n    revision, dispatch_nonce, current_head_sha, summary, evidence, and lease_token.\n    diagnostic_completed is accepted only after the PR tree is restored exactly to\n    the approved diagnostic baseline. Never send both head_ref and pr_number. Report\n    ack_received only after the designated\n    leader records an explicit approved decision with deck_approve_work_item;\n    prose replies are not approval. Called by the owner slot the brain dispatched\n    the issue to. Include work_item_id and lease_token from your bootstrap prompt.\n    ",
    "inputSchema": {
      "properties": {
        "work_item_id": {
          "title": "Work Item Id",
          "type": "integer"
        },
        "status": {
          "title": "Status",
          "type": "string"
        },
        "pr_number": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Pr Number"
        },
        "head_ref": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Head Ref"
        },
        "reassign_to_slot_id": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Reassign To Slot Id"
        },
        "note": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Note"
        },
        "lease_token": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Lease Token"
        },
        "revision": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Revision"
        },
        "dispatch_nonce": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Dispatch Nonce"
        },
        "current_head_sha": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Current Head Sha"
        },
        "summary": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Summary"
        },
        "evidence": {
          "anyOf": [
            {
              "additionalProperties": true,
              "type": "object"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Evidence"
        }
      },
      "required": [
        "work_item_id",
        "status"
      ],
      "title": "deck_report_dispatch_statusArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_report_owner_followup",
    "description": "Current Leader: persist or resolve a bounded owner settlement watch.\n\n    Read deck_get_backlog_coordination immediately before this call. Select the\n    current owner_followups entry. Keep its followup_token private and use its\n    event_sequence as expected_sequence. Use action watch and reason\n    unfinished_authorized_work before ending a turn with unfinished initial\n    implementation. Watch supports current revision0 work with a tracked PR.\n    Arrange the next authorized action before ending your turn.\n\n    For an observed pending event, use action assess and reason\n    next_action_arranged, blocked, or complete. This records only a coordination\n    disposition. A Mail read or an older backlog assessment does not resolve it.\n    If work remains, read again and register the next watch. Changed authority,\n    event, binding, policy, expired challenges and OFF/HOLD refuse stale writes.\n    A watch never wakes the owner, renews a lease, resets budgets, approves work,\n    merges a PR, or satisfies a review or milestone gate.\n    ",
    "inputSchema": {
      "properties": {
        "scope_id": {
          "title": "Scope Id",
          "type": "integer"
        },
        "work_item_id": {
          "title": "Work Item Id",
          "type": "integer"
        },
        "action": {
          "title": "Action",
          "type": "string"
        },
        "reason": {
          "title": "Reason",
          "type": "string"
        },
        "expected_sequence": {
          "title": "Expected Sequence",
          "type": "integer"
        },
        "followup_token": {
          "title": "Followup Token",
          "type": "string"
        }
      },
      "required": [
        "scope_id",
        "work_item_id",
        "action",
        "reason",
        "expected_sequence",
        "followup_token"
      ],
      "title": "deck_report_owner_followupArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_request_context",
    "description": "Ask another Agent Mail participant a non-authoritative structured question.\n\n    Creates a pending context request they will be nudged to answer. For initial-plan\n    approval, use deck_request_work_item_approval instead; a context answer cannot\n    authorize implementation.\n    ",
    "inputSchema": {
      "properties": {
        "to_member_id": {
          "title": "To Member Id",
          "type": "integer"
        },
        "topic": {
          "title": "Topic",
          "type": "string"
        },
        "why_needed": {
          "default": "",
          "title": "Why Needed",
          "type": "string"
        },
        "files_or_symbols": {
          "anyOf": [
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Files Or Symbols"
        },
        "work_item_id": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Work Item Id"
        },
        "dispatch_nonce": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Dispatch Nonce"
        }
      },
      "required": [
        "to_member_id",
        "topic"
      ],
      "title": "deck_request_contextArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_request_continuation",
    "description": "Request one bounded continuation revision from the designated Leader.",
    "inputSchema": {
      "properties": {
        "work_item_id": {
          "title": "Work Item Id",
          "type": "integer"
        },
        "dispatch_nonce": {
          "title": "Dispatch Nonce",
          "type": "string"
        },
        "phase": {
          "title": "Phase",
          "type": "string"
        },
        "execution_target": {
          "title": "Execution Target",
          "type": "string"
        },
        "summary": {
          "title": "Summary",
          "type": "string"
        },
        "allowed_paths": {
          "items": {
            "type": "string"
          },
          "title": "Allowed Paths",
          "type": "array"
        },
        "allowed_actions": {
          "items": {
            "type": "string"
          },
          "title": "Allowed Actions",
          "type": "array"
        },
        "allowed_commands": {
          "items": {
            "type": "string"
          },
          "title": "Allowed Commands",
          "type": "array"
        },
        "prohibited_actions": {
          "items": {
            "type": "string"
          },
          "title": "Prohibited Actions",
          "type": "array"
        },
        "max_failed_heads": {
          "title": "Max Failed Heads",
          "type": "integer"
        },
        "tool_fallbacks": {
          "additionalProperties": true,
          "title": "Tool Fallbacks",
          "type": "object"
        },
        "lease_token": {
          "title": "Lease Token",
          "type": "string"
        }
      },
      "required": [
        "work_item_id",
        "dispatch_nonce",
        "phase",
        "execution_target",
        "summary",
        "allowed_paths",
        "allowed_actions",
        "allowed_commands",
        "prohibited_actions",
        "max_failed_heads",
        "tool_fallbacks",
        "lease_token"
      ],
      "title": "deck_request_continuationArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_request_work_item_approval",
    "description": "Submit the current work item's initial plan to its designated Leader.\n\n    This creates normalized approval authority and returns its stable request id.\n    Do not use deck_request_context for initial-plan approval; ordinary context\n    questions are non-authoritative.\n    ",
    "inputSchema": {
      "properties": {
        "work_item_id": {
          "title": "Work Item Id",
          "type": "integer"
        },
        "dispatch_nonce": {
          "title": "Dispatch Nonce",
          "type": "string"
        },
        "summary": {
          "title": "Summary",
          "type": "string"
        },
        "plan_metadata": {
          "anyOf": [
            {
              "additionalProperties": true,
              "type": "object"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Plan Metadata"
        }
      },
      "required": [
        "work_item_id",
        "dispatch_nonce",
        "summary"
      ],
      "title": "deck_request_work_item_approvalArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_retry_work_item",
    "description": "Leader-only: request re-dispatch of an ESCALATED GitHub work item whose\n    blockers are now resolved. Pass the work_item_id (from the blocker-merged\n    notification's escalated_items) and a short reason, e.g.\n    'prerequisite #816 merged'. Rejected (409) if the item is not escalated.\n    ",
    "inputSchema": {
      "properties": {
        "work_item_id": {
          "title": "Work Item Id",
          "type": "integer"
        },
        "reason": {
          "default": "",
          "title": "Reason",
          "type": "string"
        }
      },
      "required": [
        "work_item_id"
      ],
      "title": "deck_retry_work_itemArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_send_message",
    "description": "Send a plain message to another team member. For answerable questions use\n    deck_request_context; for handing work over use deck_create_handoff.",
    "inputSchema": {
      "properties": {
        "to_member_id": {
          "title": "To Member Id",
          "type": "integer"
        },
        "body": {
          "title": "Body",
          "type": "string"
        },
        "subject": {
          "default": "",
          "title": "Subject",
          "type": "string"
        }
      },
      "required": [
        "to_member_id",
        "body"
      ],
      "title": "deck_send_messageArguments",
      "type": "object"
    }
  },
  {
    "name": "deck_whoami",
    "description": "Register with Claude Deck Agent Mail and return your participant identity, role,\n    charter, repo, live status, and unread/pending inbox counts. Call this once when\n    starting coordinated work.",
    "inputSchema": {
      "properties": {},
      "title": "deck_whoamiArguments",
      "type": "object"
    }
  }
] as const

export const privateTools = [
  {
    "name": "__deck_mail_close_generation",
    "description": "Private lifecycle control; not a model tool.",
    "inputSchema": {
      "properties": {},
      "title": "__deck_mail_close_generationArguments",
      "type": "object",
      "additionalProperties": false
    }
  }
] as const
