"""Companion paths: the files that travel with a changed source file.

The map is a checked-in JSON document of explicit entries, never a guess. A plan that names a source
file is shown its companions so the Leader approves them with the plan.
"""
import json
from pathlib import Path, PurePosixPath

MAP_PATH = Path(__file__).with_name("companion_map.json")
KINDS = frozenset({"test", "fixture", "doc", "contract"})
_GLOB_CHARACTERS = frozenset("*?[]{}")


class CompanionMapError(ValueError):
    """The checked-in companion map is malformed."""


def _concrete(path, what):
    if not isinstance(path, str) or not path or path != path.strip():
        raise CompanionMapError(f"{what} must be a non-empty path")
    parts = path.split("/")
    if (path.startswith("/") or path.endswith("/") or "\\" in path or PurePosixPath(path).as_posix() != path
            or any(part in {"", ".", ".."} for part in parts) or any(character in path for character in _GLOB_CHARACTERS)):
        raise CompanionMapError(f"{what} must be a concrete repository file path: {path!r}")
    return path


def load_map(path=None):
    """Read and validate the map. Returns ``{source: [{"path": ..., "kind": ...}, ...]}``."""
    try:
        document = json.loads(Path(path or MAP_PATH).read_text())
    except (OSError, ValueError) as exc:
        raise CompanionMapError("companion map unreadable") from exc
    if not isinstance(document, dict) or document.get("version") != 1 or not isinstance(document.get("entries"), list):
        raise CompanionMapError("companion map needs version 1 and an entries list")
    mapping = {}
    for item in document["entries"]:
        if not isinstance(item, dict) or set(item) != {"source", "companions"}:
            raise CompanionMapError("each entry needs exactly source and companions")
        source = _concrete(item["source"], "source")
        if source in mapping:
            raise CompanionMapError(f"duplicate source: {source}")
        companions = item["companions"]
        if not isinstance(companions, list) or not companions:
            raise CompanionMapError(f"{source} needs at least one companion")
        seen = set()
        for companion in companions:
            if not isinstance(companion, dict) or set(companion) != {"path", "kind"}:
                raise CompanionMapError(f"{source} companions need exactly path and kind")
            target = _concrete(companion["path"], "companion")
            if companion["kind"] not in KINDS:
                raise CompanionMapError(f"unknown companion kind: {companion['kind']!r}")
            if target == source or target in seen:
                raise CompanionMapError(f"{source} lists {target} twice or as its own companion")
            seen.add(target)
        mapping[source] = [{"path": entry["path"], "kind": entry["kind"]} for entry in companions]
    return mapping


def companions_for(paths, mapping=None):
    """Sorted companions of ``paths`` from the map, without any path already named."""
    mapping = load_map() if mapping is None else mapping
    named = set(paths)
    found = {companion["path"] for source in named for companion in mapping.get(source, ())}
    return sorted(found - named)


def with_companions(plan_metadata, mapping=None):
    """A copy of ``plan_metadata`` with ``companion_paths`` when it names mapped source paths."""
    metadata = dict(plan_metadata or {})
    paths = metadata.get("allowed_paths")
    if not isinstance(paths, list) or not paths or any(not isinstance(path, str) for path in paths):
        return metadata
    companions = companions_for(paths, mapping)
    if companions:
        metadata["companion_paths"] = companions
    return metadata
