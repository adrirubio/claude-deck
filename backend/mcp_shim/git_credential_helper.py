"""Git credential helper that requests a short-lived token from Albiex Synth City."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _read_credential_input() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in sys.stdin:
        line = raw_line.rstrip("\r\n")
        if not line:
            break
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    return values


def _request_credential(
    synth_city_url: str,
    lease: str,
    values: dict[str, str],
) -> tuple[str, str]:
    payload = json.dumps(
        {
            "workspace_token": lease,
            "protocol": values.get("protocol", ""),
            "host": values.get("host", ""),
            "path": values.get("path"),
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{synth_city_url.rstrip('/')}/api/v1/agent-teams/git-credential",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"Albiex Synth City refused credential request ({response.status})")
        body = json.loads(response.read().decode("utf-8"))
    username = body.get("username")
    password = body.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise RuntimeError("Albiex Synth City returned a malformed credential response")
    return username, password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--synth-city-url", required=True)
    parser.add_argument("--lease", required=True)
    parser.add_argument("operation", nargs="?", default="")
    args = parser.parse_args(argv)
    values = _read_credential_input()
    if args.operation != "get":
        return 0
    try:
        username, password = _request_credential(args.synth_city_url, args.lease, values)
    except (OSError, ValueError, RuntimeError, urllib.error.URLError):
        print("Albiex Synth City could not provide a GitHub credential", file=sys.stderr)
        return 1
    payload = f"username={username}\npassword={password}\n\n".encode("utf-8")
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
