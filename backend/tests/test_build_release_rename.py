"""C8: execute the shipped version/archive helpers without publishing or live units."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tomllib
import zipfile

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
BACKEND_NAME = "albiex-synth-city-backend"
SYNTHETIC_VERSION = "3.1.1-c8.fixture"
UNIT_DIR = ROOT / "scripts/product-factory"
UNIT_NAMES = {
    "albiex-synth-city-product.service",
    "albiex-synth-city-product-tmux.service",
    "albiex-synth-city-product-supervisor.service",
    "albiex-synth-city-product-supervisor-failure.service",
    "albiex-synth-city-product-supervisor.timer",
}


def _json(path):
    return json.loads(path.read_text())


@pytest.mark.parametrize("directory,name", [
    ("docs", "albiex-synth-city-docs"),
    ("integrations/pi-agent-mail", "albiex-synth-city-pi-agent-mail"),
])
def test_package_and_npm_lock_roots_have_the_qualified_product_identity(directory, name):
    package = _json(ROOT / directory / "package.json")
    lock = _json(ROOT / directory / "package-lock.json")
    assert package["name"] == lock["name"] == lock["packages"][""]["name"] == name


def test_backend_project_and_uv_lock_agree_on_identity_and_current_version():
    project = tomllib.loads((ROOT / "backend/pyproject.toml").read_text())["project"]
    lock = tomllib.loads((ROOT / "backend/uv.lock").read_text())
    roots = [package for package in lock["package"] if package.get("source") == {"editable": "."}]
    assert len(roots) == 1
    assert project["name"] == roots[0]["name"] == BACKEND_NAME
    assert project["version"] == roots[0]["version"] == (ROOT / "VERSION").read_text().strip()
    assert _json(ROOT / "frontend/package.json")["name"] == "frontend"


def _version_fixture(tmp_path):
    # Copy the actual helper and inputs; only the fixture's package identity is
    # normalized before execution so the old literal lookup has a behavioral red.
    for relative in ("VERSION", "scripts/bump-version.sh", "frontend/package.json",
                     "frontend/package-lock.json", "backend/pyproject.toml",
                     "backend/uv.lock", "backend/app/config.py"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    project = tmp_path / "backend/pyproject.toml"
    old = tomllib.loads(project.read_text())["project"]["name"]
    project.write_text(project.read_text().replace(f'name = "{old}"', f'name = "{BACKEND_NAME}"', 1))
    lock = tmp_path / "backend/uv.lock"
    lock.write_text(lock.read_text().replace(f'name = "{old}"', f'name = "{BACKEND_NAME}"', 1))
    return tmp_path


def _bump(root, *, argument=True, env=None):
    if not argument:
        (root / "VERSION").write_text(SYNTHETIC_VERSION + "\n")
    return subprocess.run(["bash", str(root / "scripts/bump-version.sh"),
                           *([SYNTHETIC_VERSION] if argument else [])],
                          cwd=root, env=env, capture_output=True, text=True, timeout=20)


@pytest.mark.parametrize("argument", [True, False])
def test_bump_updates_and_reports_the_renamed_uv_entry_not_other_packages(tmp_path, argument):
    root = _version_fixture(tmp_path)
    path = root / "backend/uv.lock"
    before = tomllib.loads(path.read_text())
    result = _bump(root, argument=argument)
    assert result.returncode == 0, result.stderr
    after = tomllib.loads(path.read_text())
    actual = [p for p in after["package"] if p["name"] == BACKEND_NAME]
    assert len(actual) == 1 and actual[0]["version"] == SYNTHETIC_VERSION
    assert re.search(r"uv\.lock:\s+" + re.escape(SYNTHETIC_VERSION), result.stdout)
    assert [p for p in after["package"] if p["name"] != BACKEND_NAME] == [
        p for p in before["package"] if p["name"] != BACKEND_NAME]


@pytest.mark.parametrize("defect", ["missing", "duplicate", "write_mismatch"])
def test_bump_refuses_unverified_uv_root_instead_of_reporting_success(tmp_path, defect):
    root = _version_fixture(tmp_path)
    path = root / "backend/uv.lock"
    env = None
    if defect == "missing":
        path.write_text(path.read_text().replace(f'name = "{BACKEND_NAME}"', 'name = "unrelated-project"'))
    elif defect == "duplicate":
        path.write_text(path.read_text() + f'\n[[package]]\nname = "{BACKEND_NAME}"\nversion = "0.0.0"\n')
    else:
        # A boundary fault: sed succeeds without applying the uv.lock write.
        # The independent verification must catch it, not trust the writer.
        binary = root / "test-bin/sed"
        binary.parent.mkdir()
        binary.write_text('#!/bin/bash\nfor arg in "$@"; do\n'
                          'case "$arg" in */backend/uv.lock) exit 0;; esac\ndone\n'
                          'exec ' + shutil.which("sed") + ' "$@"\n')
        binary.chmod(0o700)
        env = dict(os.environ, PATH=str(binary.parent) + os.pathsep + os.environ["PATH"])
    result = _bump(root, env=env)
    assert result.returncode != 0, "bump helper claimed success without a unique, verified renamed uv root"


def _workflow():
    # BaseLoader preserves the GitHub Actions `on` key and expression strings.
    return yaml.load((ROOT / ".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader)


def _step(name):
    return next(step for step in _workflow()["jobs"]["release"]["steps"] if step["name"] == name)


def test_release_steps_dry_run_real_archives_and_checksums_with_the_new_names(tmp_path):
    assert shutil.which("zip"), "the shipped release archive command requires zip"
    dist = tmp_path / "frontend/dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<title>Albiex Synth City</title>\n")
    (dist / "assets/app.js").write_bytes(b"synthetic frontend fixture\n")
    env = dict(os.environ, RELEASE_VERSION=SYNTHETIC_VERSION, RELEASE_COMMIT="a" * 40, DRY_RUN="true")
    result = subprocess.run(["bash", "-e", "-c", _step("Create release archive")["run"]],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    stem = "albiex-synth-city-frontend-v" + SYNTHETIC_VERSION
    assert {p.name for p in tmp_path.glob("*.zip")} == {stem + ".zip"}
    assert {p.name for p in tmp_path.glob("*.tar.gz")} == {stem + ".tar.gz"}
    with zipfile.ZipFile(tmp_path / (stem + ".zip")) as archive:
        assert archive.testzip() is None
        assert archive.read("index.html") == (dist / "index.html").read_bytes()
        assert archive.read("assets/app.js") == (dist / "assets/app.js").read_bytes()
    with tarfile.open(tmp_path / (stem + ".tar.gz")) as archive:
        assert archive.extractfile("./index.html").read() == (dist / "index.html").read_bytes()
        assert archive.extractfile("./assets/app.js").read() == (dist / "assets/app.js").read_bytes()
    lines = (tmp_path / "SHA256SUMS.txt").read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        digest, name = line.split()
        assert name in {stem + ".zip", stem + ".tar.gz"}
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest
    (tmp_path / "CHANGELOG.md").write_text(f"## [{SYNTHETIC_VERSION}]\n\nSynthetic release notes.\n")
    result = subprocess.run(["bash", "-e", "-c", _step("Prepare release description")["run"]],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    description = (tmp_path / "release-description.md").read_text()
    assert "Synthetic release notes." in description and "a" * 40 in description
    assert all(line in description for line in lines)


def test_release_action_title_and_every_upload_path_use_the_approved_names():
    action = _step("Create GitHub Release")
    title = action["with"]["name"].replace("${{ inputs.version }}", SYNTHETIC_VERSION)
    assert title == "Albiex Synth City v" + SYNTHETIC_VERSION
    expected = {"albiex-synth-city-frontend-v" + SYNTHETIC_VERSION + suffix for suffix in (".zip", ".tar.gz")}
    for raw in (_step("Upload description and archives for review")["with"]["path"], action["with"]["files"]):
        paths = {line.strip().replace("${{ inputs.version }}", SYNTHETIC_VERSION) for line in raw.splitlines()}
        assert expected <= paths
        assert not any("claude-deck-frontend" in path for path in paths)
    assert action["if"] == "${{ !inputs.dry_run }}"
    assert _workflow()["on"]["workflow_dispatch"]["inputs"]["dry_run"]["default"] == "true"
    checkout = _step("Checkout accepted commit")
    assert checkout["with"]["ref"] == "${{ inputs.commit }}"
    assert checkout["with"]["persist-credentials"] == "false"


def test_all_five_units_use_only_new_filenames_and_consistent_cross_references():
    actual = {p.name for p in UNIT_DIR.iterdir() if p.suffix in (".service", ".timer")}
    assert actual == UNIT_NAMES
    edges = set()
    for name in UNIT_NAMES:
        source = (UNIT_DIR / name).read_text()
        assert "claude-deck-product" not in source
        if name.endswith(".service"):
            assert re.search(r"^ExecStart=.+", source, re.M)
            assert "/opt/albiex-synth-city-product/" in source
        for key, value in re.findall(r"^(After|Requires|OnFailure|Unit)=(.*)$", source, re.M):
            for target in value.split():
                if target.startswith("albiex-synth-city-product"):
                    assert target in UNIT_NAMES, (name, key, target)
                    edges.add((name, key, target))
    assert ("albiex-synth-city-product.service", "Requires", "albiex-synth-city-product-tmux.service") in edges
    assert ("albiex-synth-city-product-supervisor.service", "After", "albiex-synth-city-product.service") in edges
    assert ("albiex-synth-city-product-supervisor.service", "OnFailure", "albiex-synth-city-product-supervisor-failure.service") in edges
    assert ("albiex-synth-city-product-supervisor.timer", "Unit", "albiex-synth-city-product-supervisor.service") in edges


@pytest.mark.parametrize("script", ["productctl", "product-supervisor", "controller-tmux"])
def test_future_factory_assets_share_the_new_root_and_state_stem(script):
    source = (UNIT_DIR / script).read_text()
    assert "/opt/albiex-synth-city-product" in source
    assert "claude-deck-product" not in source
