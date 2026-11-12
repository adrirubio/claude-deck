"""T-G1: the release guard fails closed, including inside named exceptions."""
import json
import copy
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/old_names.py"


def scan(tmp_path, files, exceptions=(), exclusions=()):
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"schema_version": 1, "exclusions": list(exclusions),
                                  "literal_exceptions": list(exceptions)}))
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path),
                           "--policy", str(policy)], capture_output=True, text=True)


@pytest.mark.parametrize("old", ["Claude Deck", "CLAUDE_DECK_URL", "claude_registry.db",
                                  ".claude-registry", "claude-deck-mail", "Check your Deck inbox.",
                                  "deck_check_inbox", "X-Deck-Operator-Token"])
def test_t_g1_new_runtime_old_name_always_fails(tmp_path, old):
    result = scan(tmp_path, {"backend/app/new_consumer.py": f"value = {old!r}\n"})
    assert result.returncode == 1, result.stdout + result.stderr
    assert "backend/app/new_consumer.py:1" in result.stdout


def test_t_g1_clean_runtime_is_allowed(tmp_path):
    result = scan(tmp_path, {"backend/app/new_consumer.py": "value = 'Albiex Synth City'\n"})
    assert result.returncode == 0, result.stdout + result.stderr


def test_t_g1_internal_variable_is_not_an_old_runtime_input(tmp_path):
    result = scan(tmp_path, {"frontend/src/client.ts": "const DECK_URL = (process.env.SYNTH_CITY_URL);\n"})
    assert result.returncode == 0, result.stdout + result.stderr


def test_t_g1_pi_negative_fixtures_do_not_exempt_current_extension(tmp_path):
    excluded = [{"category": "negative_fixture", "path": "integrations/pi-agent-mail/tests/**",
                 "reason": "Reject old opt-in and environment translation."}]
    result = scan(tmp_path, {"integrations/pi-agent-mail/tests/client.test.ts": "process.env.CLAUDE_DECK_MAIL_OPT_IN = '1';\n",
                             "integrations/pi-agent-mail/extension.ts": "label = 'Albiex Synth City';\n"}, exclusions=excluded)
    assert result.returncode == 0, result.stdout + result.stderr
    result = scan(tmp_path, {"integrations/pi-agent-mail/extension.ts": "label = 'Claude Deck';\n"}, exclusions=excluded)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "integrations/pi-agent-mail/extension.ts:1" in result.stdout


def exception():
    return {"path": "backend/app/services/provider_upgrade_artifacts.py",
            "line": "OLD = 'claude-deck-mail'", "count": 1,
            "category": "conversion_only", "reason": "Identify the owned old registration for one-time conversion."}


def test_t_g1_exact_conversion_literal_is_allowed_but_not_an_ongoing_reader(tmp_path):
    path = exception()["path"]
    result = scan(tmp_path, {path: "OLD = 'claude-deck-mail'\n"}, [exception()])
    assert result.returncode == 0, result.stdout + result.stderr
    result = scan(tmp_path, {path: "OLD = 'claude-deck-mail'\nvalue = os.getenv('CLAUDE_DECK_URL')\n"}, [exception()])
    assert result.returncode == 1, result.stdout + result.stderr
    assert path + ":2" in result.stdout


@pytest.mark.parametrize("text", ["", "OLD = 'claude-deck-mail'\nOLD = 'claude-deck-mail'\n"])
def test_t_g1_stale_or_repeated_exception_fails(tmp_path, text):
    result = scan(tmp_path, {exception()["path"]: text}, [exception()])
    assert result.returncode == 1, result.stdout + result.stderr
    assert "exception count" in result.stdout.lower()


def test_t_g1_policy_cannot_hide_a_production_tree(tmp_path):
    result = scan(tmp_path, {"backend/app/new_consumer.py": "value = 'Claude Deck'\n"})
    policy = tmp_path / "policy.json"
    content = json.loads(policy.read_text())
    content["exclusions"] = [{"category": "history", "path": "backend/app/**", "reason": "invented history"}]
    policy.write_text(json.dumps(content))
    result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path),
                             "--policy", str(policy)], capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "exclusion" in result.stdout.lower()


def test_t_g1_actual_release_tree():
    assert SCRIPT.is_file(), "T-G1 executable guard is missing"
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def assert_ci_job(workflow):
    job = next((job for job in workflow["jobs"].values() if job.get("name") == "Rename old-name guard"), None)
    assert job is not None, "T-G1 must be a named hosted CI check"
    assert not job.get('if'), 'T-G1 must run for every configured pull request'
    assert any("python scripts/ci/old_names.py" in step.get("run", "") for step in job["steps"])
    assert not any("docs_only" in str(step) or "run_suites" in str(step) for step in job["steps"])
    checkout = next(step for step in job['steps'] if step.get('uses', '').startswith('actions/checkout@'))
    assert checkout['with']['ref'] == '${{ github.event.pull_request.head.sha }}'
    assert checkout['with']['persist-credentials'] == 'false'


def test_t_g1_named_ci_job_has_no_docs_bypass():
    workflow = yaml.load((ROOT / '.github/workflows/factory-checks.yml').read_text(), Loader=yaml.BaseLoader)
    assert_ci_job(workflow)


@pytest.mark.parametrize('removed', ['job', 'execution', 'unconditional'])
def test_t_g1_ci_requirement_removal_is_detected(removed):
    workflow = copy.deepcopy(yaml.load((ROOT / '.github/workflows/factory-checks.yml').read_text(), Loader=yaml.BaseLoader))
    key = next(key for key, job in workflow['jobs'].items() if job.get('name') == 'Rename old-name guard')
    if removed == 'job':
        del workflow['jobs'][key]
    elif removed == 'execution':
        workflow['jobs'][key]['steps'] = [step for step in workflow['jobs'][key]['steps'] if 'run' not in step]
    else:
        workflow['jobs'][key]['if'] = 'false'
    with pytest.raises(AssertionError):
        assert_ci_job(workflow)
