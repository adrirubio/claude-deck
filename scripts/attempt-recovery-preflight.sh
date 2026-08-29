#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "usage: $0 <deck-base-url> <preset-id> <scope-id> <work-item-id>" >&2
  exit 64
fi

deck_base_url=${1%/}
preset_id=$2
scope_id=$3
work_item_id=$4

for value in "$preset_id" "$scope_id" "$work_item_id"; do
  [[ $value =~ ^[1-9][0-9]*$ ]] || {
    echo "preset, scope, and work-item ids must be positive integers" >&2
    exit 64
  }
done

command -v curl >/dev/null || { echo "curl is required" >&2; exit 69; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 69; }

MCP_SESSION_FRESHNESS_SECONDS=3600

get_json() {
  curl --silent --show-error --fail --request GET \
    --header 'Accept: application/json' "$1"
}

health=$(get_json "$deck_base_url/health")
preset=$(get_json "$deck_base_url/api/v1/agent-teams/presets/$preset_id")
scopes=$(get_json "$deck_base_url/api/v1/agent-teams/presets/$preset_id/github-scopes")
items=$(get_json "$deck_base_url/api/v1/agent-teams/presets/$preset_id/github-work-items?limit=200")
team=$(get_json "$deck_base_url/api/v1/agent-mail/team?sync=false")

scope=$(jq -ce --argjson id "$scope_id" '.scopes[] | select(.id == $id)' <<<"$scopes") || {
  echo "scope $scope_id is not attached to preset $preset_id" >&2
  exit 1
}
item=$(jq -ce --argjson id "$work_item_id" '.items[] | select(.id == $id)' <<<"$items") || {
  echo "work item $work_item_id is not attached to preset $preset_id" >&2
  exit 1
}

autonomy_enabled=$(jq -r '.autonomy_enabled' <<<"$preset")
continuation_enabled=$(jq -r '.continuation_enabled' <<<"$scope")
[[ $autonomy_enabled == false ]] || { echo "preflight requires autonomy off" >&2; exit 1; }
[[ $continuation_enabled == false ]] || { echo "preflight requires continuation off" >&2; exit 1; }

item_scope_id=$(jq -r '.scope_id' <<<"$item")
[[ $item_scope_id == "$scope_id" ]] || { echo "work item scope identity differs" >&2; exit 1; }

pr_number=$(jq -r '.pr_number // empty' <<<"$item")
owner_slot_id=$(jq -r '.owner_slot_id // empty' <<<"$item")
workspace_present=$(jq -r '(.workspace_path // "") != ""' <<<"$item")
[[ -n $pr_number ]] || { echo "work item has no preserved PR" >&2; exit 1; }
[[ -n $owner_slot_id ]] || { echo "work item has no owner slot" >&2; exit 1; }
[[ $workspace_present == true ]] || { echo "work item has no preserved workspace lease" >&2; exit 1; }

leader_slots=$(jq -c '[.slots[] | select(.enabled == true and (((.role // "") | ascii_downcase | contains("leader")) or ((.display_name // "") | ascii_downcase == "leader")))]' <<<"$preset")
leader_slot_count=$(jq 'length' <<<"$leader_slots")
[[ $leader_slot_count -eq 1 ]] || { echo "expected exactly one enabled Leader slot" >&2; exit 1; }
leader_slot_id=$(jq -r '.[0].id' <<<"$leader_slots")

fresh_mcp_session_count() {
  local slot_id=$1
  local now_epoch
  now_epoch=$(date -u +%s)
  jq \
    --argjson preset "$preset_id" \
    --argjson slot "$slot_id" \
    --argjson now "$now_epoch" \
    --argjson freshness "$MCP_SESSION_FRESHNESS_SECONDS" '
    def session_epoch:
      if type == "string" and length > 0 then
        (sub("\\.[0-9]+$"; "") + "Z" | fromdateiso8601?)
      else
        null
      end;
    [.members[].sessions[]?
      | select(
          .team_preset_id == $preset
          and .team_slot_id == $slot
          and .source == "mcp"
          and .mailbox_status == "connected"
        )
      | (.last_seen_at | session_epoch) as $seen
      | select(
          $seen != null
          and $seen <= $now
          and $seen >= ($now - $freshness)
        )]
    | length
  ' <<<"$team"
}

observed_pane_count() {
  local slot_id=$1
  jq --argjson preset "$preset_id" --argjson slot "$slot_id" '
    [.members[].sessions[]?
      | select(
          .team_preset_id == $preset
          and .team_slot_id == $slot
          and .source == "observed"
          and .mailbox_status == "observed"
          and (.tmux_target // "") != ""
        )]
    | unique_by(.tmux_target)
    | length
  ' <<<"$team"
}

owner_mcp_sessions=$(fresh_mcp_session_count "$owner_slot_id")
leader_mcp_sessions=$(fresh_mcp_session_count "$leader_slot_id")
owner_observed_panes=$(observed_pane_count "$owner_slot_id")
leader_observed_panes=$(observed_pane_count "$leader_slot_id")
[[ $owner_mcp_sessions -ge 1 ]] || { echo "owner slot has no fresh authenticated MCP session" >&2; exit 1; }
[[ $leader_mcp_sessions -ge 1 ]] || { echo "Leader slot has no fresh authenticated MCP session" >&2; exit 1; }
[[ $owner_observed_panes -eq 1 ]] || { echo "owner slot must have exactly one observed tmux pane" >&2; exit 1; }
[[ $leader_observed_panes -eq 1 ]] || { echo "Leader slot must have exactly one observed tmux pane" >&2; exit 1; }

jq -n \
  --arg deck_status "$(jq -r '.status' <<<"$health")" \
  --arg deck_version "$(jq -r '.version // "unknown"' <<<"$health")" \
  --argjson preset_id "$preset_id" \
  --argjson scope_id "$scope_id" \
  --argjson work_item_id "$work_item_id" \
  --argjson issue_number "$(jq '.issue_number' <<<"$item")" \
  --argjson pr_number "$pr_number" \
  --arg dispatch_status "$(jq -r '.dispatch_status' <<<"$item")" \
  --arg attempt_phase "$(jq -r '.attempt_phase' <<<"$item")" \
  --argjson active_revision "$(jq '.active_scope_revision' <<<"$item")" \
  --argjson owner_slot_id "$owner_slot_id" \
  --argjson leader_slot_id "$leader_slot_id" \
  --argjson owner_mcp_sessions "$owner_mcp_sessions" \
  --argjson leader_mcp_sessions "$leader_mcp_sessions" \
  --argjson owner_observed_panes "$owner_observed_panes" \
  --argjson leader_observed_panes "$leader_observed_panes" \
  --arg pending_approval "$(jq -r '.pending_approval_request_id // "none"' <<<"$item")" \
  --arg continuation_block "$(jq -r '.continuation_block_code // "none"' <<<"$item")" \
  --arg retry_block "$(jq -r '.retry_block_code // "none"' <<<"$item")" \
  --argjson max_revisions "$(jq '.max_continuation_revisions' <<<"$scope")" \
  --argjson max_failed_heads "$(jq '.max_continuation_failed_heads' <<<"$scope")" \
  --argjson max_failed_heads_per_revision "$(jq '.max_failed_heads_per_revision' <<<"$scope")" \
  --argjson max_paths "$(jq '.max_scope_paths' <<<"$scope")" \
  --argjson max_commands "$(jq '.max_scope_commands' <<<"$scope")" \
  '{
    deck: {status: $deck_status, version: $deck_version},
    preset: {id: $preset_id, autonomy_enabled: false},
    scope: {
      id: $scope_id,
      continuation_enabled: false,
      caps: {
        revisions: $max_revisions,
        failed_heads: $max_failed_heads,
        failed_heads_per_revision: $max_failed_heads_per_revision,
        paths: $max_paths,
        commands: $max_commands
      }
    },
    work_item: {
      id: $work_item_id,
      issue_number: $issue_number,
      pr_number: $pr_number,
      dispatch_status: $dispatch_status,
      attempt_phase: $attempt_phase,
      active_revision: $active_revision,
      owner_slot_id: $owner_slot_id,
      workspace_present: true,
      pending_approval: $pending_approval,
      continuation_block: $continuation_block,
      retry_block: $retry_block
    },
    sessions: {
      owner: {
        slot_id: $owner_slot_id,
        authenticated_mcp: $owner_mcp_sessions,
        observed_panes: $owner_observed_panes
      },
      leader: {
        slot_id: $leader_slot_id,
        authenticated_mcp: $leader_mcp_sessions,
        observed_panes: $leader_observed_panes
      }
    }
  }'
