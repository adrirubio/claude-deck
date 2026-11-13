"""Companion paths: the files that travel with a changed source file.

The map is a checked-in JSON document of explicit entries, never a guess. A plan that names a source
file is shown its companions so the Leader approves them with the plan.
"""
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

MAP_PATH = Path(__file__).with_name("companion_map.json")
KINDS = frozenset({"test", "fixture", "doc", "contract"})
# plan_metadata keys the server owns: a caller may not supply them, and old records that carry them
# as opaque metadata keep the authority they had.
COMPANION_KEY = "companion_paths"
PROVENANCE_KEY = "companion_provenance"
PROVENANCE_VALUE = "checked-in-map-v1"
RESERVED_KEYS = frozenset({COMPANION_KEY, PROVENANCE_KEY})
TRAILER_HEADER = "Companion paths added from the checked-in map:"
_DIGEST_LABEL = "Companion digest:"
_TRAILER = re.compile(
    r"\n\n" + re.escape(TRAILER_HEADER) + r"\n((?:- [^\n]+\n)+)" + re.escape(_DIGEST_LABEL) + r" ([0-9a-f]{64})\Z")
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


def with_companions(plan_metadata, mapping=None, lookup_paths=None):
    """A copy of ``plan_metadata`` with the server-owned companion keys when it names mapped source paths.

    ``lookup_paths`` is the canonical form of ``allowed_paths``; without it the raw list is used.
    """
    metadata = dict(plan_metadata or {})
    paths = lookup_paths if lookup_paths is not None else metadata.get("allowed_paths")
    if not isinstance(paths, list) or not paths or any(not isinstance(path, str) for path in paths):
        return metadata
    companions = companions_for(paths, mapping)
    if companions:
        metadata[COMPANION_KEY] = companions
        metadata[PROVENANCE_KEY] = PROVENANCE_VALUE
    return metadata


def plan_body(summary, plan_metadata):
    """The Leader's view of a plan: the owner's summary and the companions the server added."""
    companions = (plan_metadata or {}).get(COMPANION_KEY)
    if (plan_metadata or {}).get(PROVENANCE_KEY) != PROVENANCE_VALUE or not isinstance(companions, list) or not companions:
        return summary
    listing = "\n".join(f"- `{path}`" for path in companions)
    return f"{summary}\n\nCompanion paths added from the checked-in map (approved with this plan):\n{listing}"


def verified_companions(plan_metadata, summary, body):
    """Companions the server presented, or ``None``.

    Needs the provenance marker, a well-formed sorted list and the exact server-rendered Mail body. An old
    record that carries ``companion_paths`` as opaque metadata fails this and keeps its original authority.
    """
    if not isinstance(plan_metadata, dict) or plan_metadata.get(PROVENANCE_KEY) != PROVENANCE_VALUE:
        return None
    companions = plan_metadata.get(COMPANION_KEY)
    if (not isinstance(companions, list) or not companions or companions != sorted(set(companions))
            or any(not isinstance(path, str) for path in companions)):
        return None
    return companions if body == plan_body(summary, plan_metadata) else None


def _trailer_digest(identity, named, extras, summary):
    document = {"v": 1, "identity": list(identity), "named": list(named), "extras": list(extras), "summary": summary}
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def summary_with_trailer(summary, identity, named, extras):
    """The stored summary of an amendment: the owner's text plus the digest-bound list of added companions."""
    if not extras:
        return summary
    listing = "\n".join(f"- {path}" for path in extras)
    digest = _trailer_digest(identity, named, extras, summary)
    return f"{summary}\n\n{TRAILER_HEADER}\n{listing}\n{_DIGEST_LABEL} {digest}"


def split_summary(stored, identity, allowed_paths):
    """``(owner summary, named paths, added companions)`` of a stored amendment.

    A trailer counts only when its digest, which binds the owner summary, the named paths and the list to the
    request identity, verifies. Similar text in an older summary is plain summary text.
    """
    allowed = sorted(allowed_paths)
    match = _TRAILER.search(stored)
    if match:
        extras = [line[2:] for line in match.group(1).splitlines()]
        named = sorted(set(allowed) - set(extras))
        summary = stored[:match.start()]
        if (extras == sorted(set(extras)) and set(extras) <= set(allowed) and named
                and match.group(2) == _trailer_digest(identity, named, extras, summary)):
            return summary, named, extras
    return stored, allowed, []
