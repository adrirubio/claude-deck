"""Fixture checks must detect changes without rewriting reviewed artifacts."""
import hashlib
import importlib.util
import json
from pathlib import Path


_spec = importlib.util.spec_from_file_location(
    "factory_fixture_generator", Path(__file__).resolve().parents[3] / "scripts/factory-fixtures.py")
generator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generator)


def test_check_detects_response_manifest_and_copy_changes(tmp_path):
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "schema.json").write_text('{"schema_version":1}\n')
    historical = {"reviewed_head": "a" * 40, "contract_version": "p04"}
    archive = tmp_path / "v1"
    archive.mkdir()
    (archive / "schema.json").write_text('{"schema_version":0}\n')
    artifacts = generator.contract_artifacts(generated, historical, archive)
    manifest = json.loads(artifacts["manifest.json"])
    assert manifest["reviewed_head"] == historical["reviewed_head"]
    assert manifest["changed_from_p01"] == ["schema.json"]
    assert manifest["artifact_sha256"]["schema.json"] == hashlib.sha256(artifacts["schema.json"]).hexdigest()
    copies = (tmp_path / "backend", tmp_path / "frontend")
    assert generator.synchronize(artifacts, copies, write=True)
    assert generator.synchronize(artifacts, copies, write=False) == []
    for name in ("schema.json", "manifest.json"):
        path = copies[1] / name
        path.write_text("{}\n")
        assert generator.synchronize(artifacts, copies, write=False)
        assert path.read_text() == "{}\n"
        generator.synchronize(artifacts, copies, write=True)
    obsolete = copies[0] / "obsolete.json"
    obsolete.write_text("{}\n")
    assert generator.synchronize(artifacts, copies, write=False)
    assert obsolete.exists()
    generator.synchronize(artifacts, copies, write=True)
    assert not obsolete.exists()
    assert (archive / "schema.json").read_text() == '{"schema_version":0}\n'
