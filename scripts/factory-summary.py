#!/usr/bin/env python3
"""Render a current GitHub summary from files. No GitHub write is performed."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from mcp_shim.github_summary_protocol import CurrentSummary, render_summary


def unique_object(pairs):
    value = {}
    for key, field in pairs:
        if key in value:
            raise ValueError("duplicate_field")
        value[key] = field
    return value


def read_bounded(path, limit=65536):
    with path.open("rb") as stream:
        data = stream.read(limit * 4 + 1)
    if len(data) > limit * 4:
        raise ValueError("input_too_large")
    value = data.decode("utf-8")
    if len(value) > limit:
        raise ValueError("input_too_large")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body-file", required=True, type=Path)
    parser.add_argument("--summary-file", required=True, type=Path)
    parser.add_argument("--output-file", required=True, type=Path)
    parser.add_argument("--expected-body-sha256")
    args = parser.parse_args()
    try:
        body = read_bounded(args.body_file)
        payload = json.loads(read_bounded(args.summary_file, 8192), object_pairs_hook=unique_object)
        summary = CurrentSummary.model_validate_json(json.dumps(payload))
        result = render_summary(body, summary, expected_body_sha256=args.expected_body_sha256)
        # A new output file prevents overwriting the original or a concurrent draft.
        with args.output_file.open("x") as stream:
            stream.write(result.pop("body_markdown"))
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, TypeError) as error:
        # Validation errors can include input text. Report only the class.
        print(type(error).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
