#!/usr/bin/env python3
"""Generate or check the active factory contract from disposable ASGI requests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend/tests/factory/fixtures/v1-p04"
FRONTEND = ROOT / "frontend/tests/fixtures/factory/v1-p04"


def contract_artifacts(generated: Path, manifest: dict, archive: Path | None = None) -> dict[str, bytes]:
    artifacts = {path.name: path.read_bytes() for path in sorted(generated.glob("*.json"))}
    if not artifacts or "schema.json" not in artifacts:
        raise ValueError("The disposable route generator produced no complete contract.")
    manifest = dict(manifest)
    manifest["artifact_sha256"] = {
        name: hashlib.sha256(data).hexdigest() for name, data in artifacts.items()
    }
    manifest["generator"] = "scripts/factory-fixtures.py"
    manifest["artifact_source"] = "current working tree; historical review fields do not approve regenerated artifacts"
    if archive is not None:
        manifest["changed_from_p01"] = [
            name for name, data in artifacts.items()
            if not (archive / name).exists() or json.loads((archive / name).read_bytes()) != json.loads(data)
        ]
    artifacts["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    return artifacts


def synchronize(artifacts: dict[str, bytes], directories: tuple[Path, ...], *, write: bool) -> list[str]:
    stale = []
    for directory in directories:
        for path in directory.glob("*.json"):
            if path.name not in artifacts:
                stale.append(f"{directory.name}/{path.name} (obsolete)")
                if write:
                    path.unlink()
        for name, data in artifacts.items():
            path = directory / name
            if not path.exists() or path.read_bytes() != data:
                stale.append(f"{directory.parent.name}/{directory.name}/{name}")
                if write:
                    directory.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
    return stale


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="Rebuild both active fixture copies and their manifest.")
    mode.add_argument("--check", action="store_true", help="Check current responses, both copies, and manifest hashes.")
    args = parser.parse_args()
    # Provenance describes the historical contract review. Do not replace that
    # evidence with an unreviewed generator head or regenerate the archived v1.
    manifest = json.loads((BACKEND / "manifest.json").read_text())
    with tempfile.TemporaryDirectory(prefix="deck-factory-fixtures-") as temporary:
        env = dict(os.environ, PYTHONPATH=str(ROOT / "backend"))
        result = subprocess.run([
            sys.executable, "-m", "pytest",
            str(ROOT / "backend/tests/factory/test_factory_fixtures.py") + "::test_frozen_response_contract",
            "-q", "--tb=short", f"--factory-fixture-output={temporary}",
        ], cwd=ROOT, env=env, check=False)
        if result.returncode:
            return result.returncode
        artifacts = contract_artifacts(Path(temporary), manifest, BACKEND.parent / "v1")
        stale = synchronize(artifacts, (BACKEND, FRONTEND), write=args.write)
    if stale and args.check:
        print("Factory fixtures are stale. Run scripts/factory-fixtures.py --write.", file=sys.stderr)
        for name in stale:
            print(f"  {name}", file=sys.stderr)
        return 1
    print("Factory fixtures written." if args.write else "Factory fixtures are current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
