#!/usr/bin/env python3
"""Run a reviewed controller upgrade or accepted integration update from data files."""
import argparse
import fcntl
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.services.maintenance_operations import InstallationProfile, IntegrationRequest, Maintenance, UpgradeRequest, read_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['upgrade','integration-update'])
    parser.add_argument('--profile',required=True,type=Path)
    parser.add_argument('--request',required=True,type=Path)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    try:
        profile=InstallationProfile.model_validate(read_json(args.profile,private=True))
        kind=UpgradeRequest if args.operation=='upgrade' else IntegrationRequest
        request=kind.model_validate(read_json(args.request,private=True))
        if not args.execute:
            print(json.dumps({'status':'data_validated_no_execution','operation':args.operation}));return 0
        directory=Path(profile.state_dir)/'maintenance';directory.mkdir(mode=0o700,exist_ok=True)
        with (directory/'operation.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            service=Maintenance(profile)
            record=service.upgrade(request) if args.operation=='upgrade' else service.integration_update(request)
        print(json.dumps({'status':'operation_recorded','record':record}));return 0
    except Exception as error:
        print(json.dumps({'status':'not_confirmed','error':type(error).__name__}),file=sys.stderr);return 1


if __name__=='__main__': raise SystemExit(main())
