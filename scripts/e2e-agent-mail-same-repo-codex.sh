#!/usr/bin/env bash
# End-to-end probe for two same-repo Codex agents communicating through Agent Mail.
# The planner intentionally stops after requesting review, so success requires Deck
# to wake it before it reads the reviewer feedback.
#
# Requirements:
# - Claude Deck backend running on DECK_URL, default http://127.0.0.1:8000
# - Codex Agent Mail MCP/hooks installed
# - tmux, codex, curl, jq
#
# Usage:
#   scripts/e2e-agent-mail-same-repo-codex.sh [/absolute/repo/path]
#
# Set KEEP_E2E_SESSIONS=1 to preserve tmux sessions and the Agent Team preset.

set -euo pipefail

DECK_URL="${DECK_URL:-http://127.0.0.1:8000}"
REPO_PATH="${1:-$(pwd)}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-420}"
KEEP_E2E_SESSIONS="${KEEP_E2E_SESSIONS:-0}"

RUN_ID="$(date +%Y%m%d%H%M%S)"
PRESET_NAME="E2E same-repo mail ${RUN_ID}"
PLANNER="E2E Planner ${RUN_ID}"
REVIEWER="E2E Reviewer ${RUN_ID}"
SUBJECT="E2E plan review ${RUN_ID}"
SUCCESS_TOKEN="E2E_AGENT_MAIL_ROUNDTRIP_${RUN_ID}"
FEEDBACK_TOKEN="E2E_REVIEW_FEEDBACK_${RUN_ID}"
WAITING_TOKEN="E2E_PLANNER_WAITING_FOR_NUDGE_${RUN_ID}"
INBOX_NUDGE_PREFIX='Claude Deck Agent Mail: please call `deck_check_inbox'
TMP_DIR="${TMPDIR:-/tmp}/claude-deck-agent-mail-e2e-${RUN_ID}"

PRESET_ID=""
PLANNER_ID=""
REVIEWER_ID=""
PASSED=0

mkdir -p "$TMP_DIR"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 2
  fi
}

api() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  if [ -n "$body" ]; then
    curl -fsS -X "$method" "${DECK_URL%/}/api/v1${path}" \
      -H 'Content-Type: application/json' \
      --data-binary "$body"
  else
    curl -fsS -X "$method" "${DECK_URL%/}/api/v1${path}"
  fi
}

cleanup() {
  if [ "$PASSED" -eq 1 ] && [ "$KEEP_E2E_SESSIONS" != "1" ]; then
    if [ -f "$TMP_DIR/launch.json" ]; then
      jq -r '.items[].session_name // empty' "$TMP_DIR/launch.json" | while IFS= read -r session; do
        tmux kill-session -t "$session" 2>/dev/null || true
      done
    fi
    if [ -n "$PRESET_ID" ]; then
      api DELETE "/agent-teams/presets/${PRESET_ID}" >/dev/null 2>&1 || true
    fi
  else
    echo "Preserved E2E artifacts in $TMP_DIR" >&2
    if [ -f "$TMP_DIR/launch.json" ]; then
      jq -r '.items[] | "tmux: " + (.tmux_target // "")' "$TMP_DIR/launch.json" >&2 || true
    fi
  fi
}
trap cleanup EXIT

capture_pane() {
  tmux capture-pane -t "$1" -p -S -260 2>/dev/null || true
}

approve_visible_prompts() {
  local target pane
  jq -r '.items[].tmux_target // empty' "$TMP_DIR/launch.json" | while IFS= read -r target; do
    pane="$(capture_pane "$target")"
    if printf '%s' "$pane" | rg -q 'Allow the claude-deck-mail MCP server to run tool'; then
      tmux send-keys -t "$target" Down Enter
      sleep 0.8
    fi
  done
}

load_member_ids() {
  local team_json
  team_json="$(api GET '/agent-mail/team?sync=true')"
  PLANNER_ID="$(printf '%s' "$team_json" | jq -r --arg name "$PLANNER" '.members[] | select(.display_name == $name) | .id' | head -1)"
  REVIEWER_ID="$(printf '%s' "$team_json" | jq -r --arg name "$REVIEWER" '.members[] | select(.display_name == $name) | .id' | head -1)"
  [ -n "$PLANNER_ID" ] && [ "$PLANNER_ID" != "null" ] && [ -n "$REVIEWER_ID" ] && [ "$REVIEWER_ID" != "null" ]
}

slots_are_wakeable() {
  api GET '/agent-mail/team?sync=true' |
    jq -e --arg planner "$PLANNER" --arg reviewer "$REVIEWER" '
      [.members[]
       | select(.display_name == $planner or .display_name == $reviewer)
       | select(.participant_kind == "team_slot")
       | select(.status == "connected")
       | select(.wake_state == "wakeable")
       | select([.sessions[] | select(.source == "mcp" or .source == "hook" or .source == "observed")] | length >= 3)
      ] | length == 2
    ' >/dev/null
}

request_ids() {
  api GET '/agent-mail/messages' |
    jq -r --arg subject "$SUBJECT" --argjson reviewer_id "$REVIEWER_ID" '
      .[]
      | select(.kind == "context_request")
      | select((.subject // "") | startswith($subject))
      | select(.recipient_member_id == $reviewer_id)
      | .id
    '
}

thread_has_feedback() {
  local request_id="$1"
  api GET "/agent-mail/messages/${request_id}/thread" |
    jq -e --arg feedback "$FEEDBACK_TOKEN" '
      any(.replies[]?; .kind == "answer" and ((.body_markdown // "") | contains($feedback)))
    ' >/dev/null
}

planner_target() {
  jq -r --arg planner "$PLANNER" '.items[] | select(.slot_name == $planner) | .tmux_target' "$TMP_DIR/launch.json"
}

reviewer_target() {
  jq -r --arg reviewer "$REVIEWER" '.items[] | select(.slot_name == $reviewer) | .tmux_target' "$TMP_DIR/launch.json"
}

planner_waiting_for_nudge() {
  capture_pane "$(planner_target)" | rg -q "• ${WAITING_TOKEN}|^${WAITING_TOKEN}$"
}

planner_was_nudged() {
  capture_pane "$(planner_target)" | rg -qF "$INBOX_NUDGE_PREFIX"
}

reviewer_was_nudged() {
  capture_pane "$(reviewer_target)" | rg -qF "$INBOX_NUDGE_PREFIX"
}

planner_read_feedback() {
  api GET "/agent-mail/agent/inbox?member_id=${PLANNER_ID}&unread_only=false&mark_read=false&limit=50" |
    jq -e --arg feedback "$FEEDBACK_TOKEN" '
      any(.messages[]?; .kind == "answer" and ((.body_markdown // "") | contains($feedback)) and .read_at != null)
    ' >/dev/null
}

planner_printed_success() {
  capture_pane "$(planner_target)" | rg -q "• ${SUCCESS_TOKEN}|^${SUCCESS_TOKEN}$"
}

print_status() {
  echo "--- status $(date -Is) ---"
  api GET '/agent-mail/team?sync=true' |
    jq --arg planner "$PLANNER" --arg reviewer "$REVIEWER" '
      [.members[]
       | select(.display_name == $planner or .display_name == $reviewer)
       | {
           id,
           display_name,
           status,
           wake_state,
           wake_methods,
           last_inbox_checked_at,
           unread_count,
           pending_count,
           sessions: [.sessions[] | {source, tmux_target, team_slot_name, mailbox_status, last_seen_at}]
         }]
    '
  if [ -n "$REVIEWER_ID" ] && [ "$REVIEWER_ID" != "null" ]; then
    api GET '/agent-mail/messages' |
      jq --arg subject "$SUBJECT" --argjson reviewer_id "$REVIEWER_ID" '
        [.[] | select(((.subject // "") | startswith($subject)) or .recipient_member_id == $reviewer_id)
         | {id, thread_root_id, kind, sender_name, recipient_member_id, subject, request_status, created_at}]
      '
  fi
}

require_command curl
require_command jq
require_command rg
require_command tmux
require_command codex

if [ ! -d "$REPO_PATH" ]; then
  echo "Repo path does not exist: $REPO_PATH" >&2
  exit 2
fi
REPO_PATH="$(cd "$REPO_PATH" && pwd -P)"

curl -fsS "${DECK_URL%/}/health" >/dev/null

echo "Creating temporary Agent Team: $PRESET_NAME"
payload="$(
  jq -n \
    --arg name "$PRESET_NAME" \
    --arg repo "$REPO_PATH" \
    --arg planner "$PLANNER" \
    --arg reviewer "$REVIEWER" \
    --arg subject "$SUBJECT" \
    --arg success "$SUCCESS_TOKEN" \
    --arg feedback "$FEEDBACK_TOKEN" \
    --arg waiting "$WAITING_TOKEN" \
    '{
      name: $name,
      description: "Temporary automated Agent Mail same-repo Codex E2E test",
      created_by: "codex-e2e",
      slots: [
        {
          display_name: $planner,
          provider: "codex-cli",
          repo_path: $repo,
          role: "Planner",
          charter: "Create a tiny plan, request review from the reviewer slot, then confirm when feedback is received.",
          bootstrap_prompt: (
            "You are the planner in an automated Claude Deck Agent Mail E2E test. " +
            "First call deck_whoami and deck_list_team. Find the teammate named \"" + $reviewer + "\". " +
            "Send deck_request_context to that teammate. The topic must start with \"" + $subject + "\" and include this tiny markdown plan:\n\n" +
            "## Tiny Plan\n\n1. Confirm the planner and reviewer can exchange Agent Mail.\n2. Ask the reviewer to sanity-check this tiny plan.\n3. Report the reviewer feedback once received.\n\n" +
            "Use why_needed \"Automated same-repo Agent Mail test\". " +
            "After sending the request, do not call deck_check_inbox again in this turn. " +
            "Print exactly " + $waiting + " and end your turn. " +
            "When a later Claude Deck Agent Mail nudge prompt arrives in a new turn, call deck_check_inbox(unread_only=false), read the reviewer answer, then print exactly " + $success + " and summarize the feedback. " +
            "Do not edit files."
          ),
          launch_mode: "plain",
          launch_options: {approval_policy: "never", sandbox: "workspace-write", no_alt_screen: true},
          enabled: true,
          position: 0
        },
        {
          display_name: $reviewer,
          provider: "codex-cli",
          repo_path: $repo,
          role: "Reviewer",
          charter: "Review planner requests and reply with concise feedback.",
          bootstrap_prompt: (
            "You are the reviewer in an automated Claude Deck Agent Mail E2E test. " +
            "First call deck_whoami and deck_check_inbox(unread_only=false). " +
            "If you receive a context request from \"" + $planner + "\" whose subject starts with \"" + $subject + "\", " +
            "reply using deck_reply with this exact token in the body: " + $feedback + ". " +
            "Include one concrete review comment. Do not edit files."
          ),
          launch_mode: "plain",
          launch_options: {approval_policy: "never", sandbox: "workspace-write", no_alt_screen: true},
          enabled: true,
          position: 1
        }
      ]
    }'
)"

api POST '/agent-teams/presets' "$payload" > "$TMP_DIR/preset.json"
PRESET_ID="$(jq -r .id "$TMP_DIR/preset.json")"

echo "Planning launch for preset $PRESET_ID"
api POST "/agent-teams/presets/${PRESET_ID}/plan-launch" '{"reuse_existing":false}' > "$TMP_DIR/plan.json"
jq -e '.can_launch == true and .spawn_count == 2 and .blocked_count == 0' "$TMP_DIR/plan.json" >/dev/null
plan_hash="$(jq -r .plan_hash "$TMP_DIR/plan.json")"

echo "Launching two Codex tmux sessions"
launch_body="$(jq -n --arg hash "$plan_hash" '{requested_by:"codex-e2e", reuse_existing:false, confirm_plan_hash:$hash}')"
api POST "/agent-teams/presets/${PRESET_ID}/launch" "$launch_body" > "$TMP_DIR/launch.json"
jq '{launch_id,status,items:[.items[]|{slot_name,status,session_name,tmux_target}]}' "$TMP_DIR/launch.json"

start="$(date +%s)"
last_report=0
while true; do
  elapsed="$(($(date +%s) - start))"
  approve_visible_prompts

  if [ -z "$PLANNER_ID" ] || [ -z "$REVIEWER_ID" ]; then
    load_member_ids || true
  fi

  if [ -n "$PLANNER_ID" ] && [ -n "$REVIEWER_ID" ]; then
    if slots_are_wakeable; then
      while IFS= read -r request_id; do
        [ -n "$request_id" ] || continue
        if thread_has_feedback "$request_id" &&
          planner_waiting_for_nudge &&
          reviewer_was_nudged &&
          planner_was_nudged &&
          planner_read_feedback &&
          planner_printed_success; then
          echo "PASS: same-repo Codex Agent Mail wakeability round-trip succeeded in ${elapsed}s"
          echo "Planner: $PLANNER_ID ($PLANNER)"
          echo "Reviewer: $REVIEWER_ID ($REVIEWER)"
          echo "Planner waiting token: $WAITING_TOKEN"
          echo "Feedback token: $FEEDBACK_TOKEN"
          PASSED=1
          exit 0
        fi
      done < <(request_ids)
    fi
  fi

  if [ $((elapsed - last_report)) -ge 30 ]; then
    print_status
    last_report="$elapsed"
  fi

  if [ "$elapsed" -ge "$TIMEOUT_SECONDS" ]; then
    echo "FAIL: timed out after ${elapsed}s waiting for same-repo Agent Mail round-trip" >&2
    jq -r '.items[].tmux_target // empty' "$TMP_DIR/launch.json" | while IFS= read -r target; do
      echo "--- $target" >&2
      capture_pane "$target" | tail -220 >&2
    done
    exit 1
  fi

  sleep 2
done
