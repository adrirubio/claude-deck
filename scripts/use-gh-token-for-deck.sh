#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend_dir="$repo_root/backend"
env_file="$backend_dir/.env"
python_bin="$backend_dir/venv/bin/python"

if ! command -v gh >/dev/null 2>&1; then
  echo "Error: gh is not installed or is not on PATH." >&2
  exit 1
fi

if [[ ! -x "$python_bin" ]]; then
  echo "Error: backend Python was not found at $python_bin." >&2
  exit 1
fi

if [[ ! -f "$env_file" ]]; then
  echo "Error: backend environment file was not found at $env_file." >&2
  exit 1
fi

echo "Checking the active GitHub CLI account..."
gh auth status -h github.com >/dev/null

ENV_FILE="$env_file" "$python_bin" - <<'PY'
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import os
import re
import subprocess
import tempfile


path = Path(os.environ["ENV_FILE"])
token = subprocess.run(
    ["gh", "auth", "token", "-h", "github.com"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
if not token:
    raise SystemExit("Error: gh returned an empty GitHub token")

content = path.read_text()
updated, count = re.subn(
    r"(?m)^(\s*github_token\s*=\s*).*$",
    lambda match: f"{match.group(1)}{token}",
    content,
    count=1,
)
if count != 1:
    raise SystemExit("Error: expected exactly one github_token setting in backend/.env")

file_descriptor, temporary_name = tempfile.mkstemp(
    dir=path.parent,
    prefix=".env.",
    text=True,
)
try:
    with os.fdopen(file_descriptor, "w") as temporary_file:
        temporary_file.write(updated)
        temporary_file.flush()
        os.fsync(temporary_file.fileno())
    os.chmod(temporary_name, 0o600)
    os.replace(temporary_name, path)
finally:
    if os.path.exists(temporary_name):
        os.unlink(temporary_name)

stored_content = path.read_text()
stored_match = re.search(
    r"(?mi)^\s*github_token\s*=\s*(.*?)\s*$",
    stored_content,
)
if stored_match is None:
    raise SystemExit("Error: github_token disappeared during verification")

stored_token = stored_match.group(1).strip().strip('"').strip("'")
tokens_match = sha256(stored_token.encode()).digest() == sha256(token.encode()).digest()
file_mode = path.stat().st_mode & 0o777

if not tokens_match:
    raise SystemExit("Error: the stored credential does not match the active gh credential")
if file_mode != 0o600:
    raise SystemExit(f"Error: backend/.env mode is {oct(file_mode)}, expected 0o600")

print("GitHub credential updated without printing or exporting it.")
print("same_token = True")
print("env_mode = 0o600")
PY

echo
echo "Credential preparation is complete."
echo "Do not enable autonomy yet; resume the G3 recovery workflow first."
