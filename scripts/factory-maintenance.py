#!/usr/bin/env python3
"""Run a reviewed controller upgrade or accepted integration update from data files."""
import argparse
import fcntl
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.services.maintenance_operations import InstallationProfile, IntegrationRequest, Maintenance, UpgradeRequest, read_json


# Only fixed public codes can enter the CLI output.
PUBLIC_REASON_CODES = frozenset({
    'absolute_candidate_required', 'absolute_hold_path_required', 'absolute_path_required',
    'accepted_base_updates_disabled', 'accepted_check_not_successful', 'accepted_pull_changed',
    'accepted_tip_changed', 'active_owner_checkpoint_required', 'active_owner_required',
    'active_workspace_unavailable', 'approved_owner_required', 'approved_scope_required',
    'autonomy_pause_unconfirmed', 'autonomy_remains_active', 'autonomy_unexpectedly_active',
    'checkpoint_context_changed', 'checkpoint_head_changed', 'clean_checkpoint_required',
    'configured_integration_checks_missing', 'controller_checkout_unconfirmed', 'controller_health_unknown',
    'controller_processes_remain', 'controller_termination_unknown', 'controller_version_changed',
    'current_generation_ambiguous', 'current_generation_changed', 'current_generation_unavailable',
    'current_member_unavailable', 'current_slot_changed', 'database_identity_changed',
    'deployed_context_changed', 'duplicate_checkpoint_field', 'duplicate_field',
    'github_identity_unavailable', 'input_too_large', 'integration_branch_changed',
    'integration_repository_changed', 'integration_tip_not_current', 'invalid_check_application',
    'invalid_input_file', 'invalid_version_field', 'loopback_api_required',
    'maintenance_authority_schema_changed', 'maintenance_child_settlement_unknown', 'maintenance_command_failed',
    'maintenance_command_timeout_settled', 'maintenance_identity_unavailable', 'maintenance_output_too_large',
    'maintenance_read_limit', 'maintenance_reservation_deadline', 'maintenance_user_unavailable',
    'native_generation_changed', 'native_process_changed', 'observation_pause_context_changed',
    'observation_pause_not_found', 'observation_pause_not_resumable', 'observation_pause_nudge_missing',
    'observation_resume_replay_conflict', 'operator_token_unconfigured', 'owner_ack_missing',
    'owner_approval_changed', 'owner_binding_ambiguous', 'owner_binding_changed',
    'owner_binding_retired', 'owner_checkpoint_changed', 'owner_checkpoint_not_confirmed',
    'owner_checkpoint_unavailable', 'owner_generation_ambiguous', 'owner_generation_unavailable',
    'owner_identity_changed', 'owner_identity_unavailable', 'owner_member_unavailable',
    'owner_native_identity_changed', 'owner_provider_unsupported', 'owner_revision_changed',
    'owner_slot_unavailable', 'owner_source_changed', 'owner_workspace_changed',
    'pause_context_changed', 'post_update_context_changed', 'private_profile_required',
    'protected_file_changed', 'relative_profile_path_required', 'reserved_checkpoint_changed',
    'reserved_owner_context_changed', 'reserved_upgrade_context_changed', 'reviewed_runtime_file_changed',
    'runtime_change_path_invalid', 'runtime_change_scope_changed', 'runtime_proof_invalid',
    'runtime_review_binding_invalid', 'safety_hold_exists', 'source_import_context_changed',
    'source_import_path_limit', 'source_import_read_limit', 'source_import_replay_conflict',
    'source_import_tree_inconclusive', 'source_import_tree_limit', 'source_operation_in_progress',
    'stopped_context_changed', 'supervisor_not_active', 'supervisor_observation_unknown',
    'supervisor_pause_unconfirmed', 'unmerged_source', 'verification_in_progress',
    'version_record_changed', 'workspace_binding_changed',
})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['upgrade','integration-update'])
    parser.add_argument('--profile',required=True,type=Path)
    parser.add_argument('--request',required=True,type=Path)
    action=parser.add_mutually_exclusive_group()
    action.add_argument('--execute',action='store_true')
    action.add_argument('--checkpoint-template',action='store_true')
    args=parser.parse_args()
    try:
        profile=InstallationProfile.model_validate(read_json(args.profile,private=True))
        kind=UpgradeRequest if args.operation=='upgrade' else IntegrationRequest
        request=kind.model_validate(read_json(args.request,private=True))
        if args.checkpoint_template:
            print(json.dumps(Maintenance(profile).checkpoint_templates(request)));return 0
        if not args.execute:
            print(json.dumps({'status':'data_validated_no_execution','operation':args.operation}));return 0
        directory=Path(profile.state_dir)/'maintenance';directory.mkdir(mode=0o700,exist_ok=True)
        with (directory/'operation.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            service=Maintenance(profile)
            record=service.upgrade(request) if args.operation=='upgrade' else service.integration_update(request)
        print(json.dumps({'status':'operation_recorded','record':record}));return 0
    except Exception as error:
        result = {'status':'not_confirmed','error':type(error).__name__}
        if isinstance(error, ValueError) and str(error) in PUBLIC_REASON_CODES:
            result['reason_code'] = str(error)
        print(json.dumps(result),file=sys.stderr);return 1


if __name__=='__main__': raise SystemExit(main())
