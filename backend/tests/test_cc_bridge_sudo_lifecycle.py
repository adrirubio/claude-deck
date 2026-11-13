"""Guards, lifecycle controls and sudo attestation for the hosted real-sudo attach regression (#880).

Nothing here runs a privileged command: every outside effect is faked, so these tests run anywhere,
in the full backend suite. The privileged test itself is in test_cc_bridge_real_sudo.py. It runs
only on a hosted runner, in the dedicated job "Hosted real-sudo attach", and the full suite does
not collect it.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from tests import real_sudo_support
from tests.real_sudo_support import (
    CAP_CHOWN,
    CAP_KILL,
    EXPECTED_CAPBND,
    EXPECTED_SUDO_UPSTREAM,
    DisposableAgent,
    SudoAttestationError,
    attest_sudo,
    format_sudo_facts,
    is_ephemeral_hosted_runner,
    parse_sudo_version,
    require_original_sudo,
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "backend-tests.yml"
PRIVILEGED_FILE = "tests/test_cc_bridge_real_sudo.py"

def test_the_privileged_regression_has_no_other_way_to_switch_on():
    hosted_linux = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux"}
    assert is_ephemeral_hosted_runner(hosted_linux)
    assert not is_ephemeral_hosted_runner({**hosted_linux, "RUNNER_OS": "Windows"})
    assert not is_ephemeral_hosted_runner({k: v for k, v in hosted_linux.items() if k != "RUNNER_OS"})
    assert not is_ephemeral_hosted_runner({"CI": "true"})
    assert not is_ephemeral_hosted_runner({})
    assert not is_ephemeral_hosted_runner({"GITHUB_ACTIONS": "true"})
    assert not is_ephemeral_hosted_runner({**hosted_linux, "RUNNER_ENVIRONMENT": "self-hosted"})
    assert not is_ephemeral_hosted_runner({"RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux"})
    assert not is_ephemeral_hosted_runner({"SYNTH_CITY_PRIVILEGED_TESTS": "1"})


def test_the_expected_bounding_set_has_no_chown_and_no_kill():
    assert EXPECTED_CAPBND == 0x800C6
    assert not EXPECTED_CAPBND & (1 << CAP_CHOWN)
    assert not EXPECTED_CAPBND & (1 << CAP_KILL)


def run_sudo(*args, check=True, timeout=60):
    result = subprocess.run(["sudo", "-n", *args], capture_output=True, text=True, timeout=timeout)
    if check:
        assert result.returncode == 0, f"sudo -n {' '.join(args)} failed ({result.returncode}): {result.stderr.strip()}"
    return result


def parse_capbnd(text: str) -> int:
    lines = [line for line in text.splitlines() if line.startswith("CapBnd:")]
    assert len(lines) == 1, f"expected one CapBnd line, saw {text!r}"
    return int(lines[0].split(":", 1)[1].strip(), 16)


# --- the sudo the privileged test claims to represent: production's sudo 1.9.15p5 -------------------

SUDO_ORIGINAL = (
    "Sudo version 1.9.15p5\nSudoers policy plugin version 1.9.15p5\nSudoers file grammar version 50\n"
    "Sudoers I/O plugin version 1.9.15p5\nSudoers audit plugin version 1.9.15p5\n"
)
SUDO_OTHER_UPSTREAM = SUDO_ORIGINAL.replace("1.9.15p5", "1.9.16p2")
SUDO_RS = "sudo-rs 0.2.13\n"
PACKAGE_EXPECTED = "sudo\t1.9.15p5-3ubuntu5.24.04.4\tamd64"
IMAGE = {"ImageOS": "ubuntu24", "ImageVersion": "20261101.1.0"}


def fake_environment(version_output=SUDO_ORIGINAL, package=PACKAGE_EXPECTED, resolved="/usr/bin/sudo", found="/usr/bin/sudo"):
    """Injected effects for attest_sudo. Nothing is executed."""

    def run(argv, **kwargs):
        if argv[0] == "dpkg-query":
            return subprocess.CompletedProcess(argv, 0 if package else 1, package or "", "")
        if argv[1:] == ["--version"]:
            return subprocess.CompletedProcess(argv, 0, version_output, "")
        raise AssertionError(f"unexpected command {argv}")

    return {
        "run": run,
        "which": lambda name: found,
        "realpath": lambda path: resolved,
        "environ": dict(IMAGE),
        "kernel": lambda: "6.11.0-1018-azure",
        "capbnd": lambda: EXPECTED_CAPBND,
    }


def test_the_expected_sudo_is_the_exact_production_upstream_version():
    assert EXPECTED_SUDO_UPSTREAM == "1.9.15p5"


@pytest.mark.parametrize("text,expected", [
    (SUDO_ORIGINAL, "1.9.15p5"),
    (SUDO_OTHER_UPSTREAM, "1.9.16p2"),
    (SUDO_RS, None),
    ("", None),
    ("garbage\n", None),
    ("Sudo version\n", None),
    ("something Sudo version 1.9.15p5\n", None),
])
def test_the_sudo_version_is_read_from_the_first_line_only(text, expected):
    assert parse_sudo_version(text) == expected


def test_the_original_sudo_is_attested_with_its_executable_package_image_and_kernel():
    facts = attest_sudo(**fake_environment())
    require_original_sudo(facts)
    assert facts["upstream_version"] == "1.9.15p5" and facts["is_sudo_rs"] is False
    assert facts["executable"] == "/usr/bin/sudo" and facts["resolved_executable"] == "/usr/bin/sudo"
    assert facts["package"] == "sudo 1.9.15p5-3ubuntu5.24.04.4 amd64"
    assert (facts["image_os"], facts["image_version"], facts["kernel"]) == ("ubuntu24", "20261101.1.0", "6.11.0-1018-azure")
    assert facts["controller_capbnd"] == EXPECTED_CAPBND
    text = format_sudo_facts(facts)
    for fragment in ("1.9.15p5", "/usr/bin/sudo", "ubuntu24", "20261101.1.0", "6.11.0-1018-azure", "0x800c6"):
        assert fragment in text


def test_a_package_revision_that_differs_is_reported_and_not_hidden():
    facts = attest_sudo(**fake_environment(package="sudo\t1.9.15p5-3ubuntu5.24.04.9\tamd64"))
    require_original_sudo(facts)  # the upstream version is what is claimed
    assert "1.9.15p5-3ubuntu5.24.04.9" in format_sudo_facts(facts)


def test_another_upstream_version_stops_the_test_and_names_both_versions():
    facts = attest_sudo(**fake_environment(version_output=SUDO_OTHER_UPSTREAM))
    with pytest.raises(SudoAttestationError) as error:
        require_original_sudo(facts)
    assert "1.9.16p2" in str(error.value) and "1.9.15p5" in str(error.value)


def test_sudo_rs_stops_the_test_and_is_named():
    facts = attest_sudo(**fake_environment(version_output=SUDO_RS, resolved="/usr/lib/cargo/bin/sudo"))
    assert facts["is_sudo_rs"] is True and facts["upstream_version"] is None
    with pytest.raises(SudoAttestationError) as error:
        require_original_sudo(facts)
    assert "sudo-rs" in str(error.value)


def test_a_missing_sudo_stops_the_test_and_says_so():
    facts = attest_sudo(**fake_environment(found=None))
    with pytest.raises(SudoAttestationError) as error:
        require_original_sudo(facts)
    assert "no sudo" in str(error.value).lower()


def test_an_unreadable_package_identity_is_reported_as_unknown_and_does_not_hide_the_version():
    facts = attest_sudo(**fake_environment(package=""))
    assert facts["package"] == "unknown"
    require_original_sudo(facts)


# --- the workflow keeps the privileged test in its own job, and cannot pass without running it ------


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def _keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _keys(item)


def _privileged_job():
    jobs = [job for job in _workflow()["jobs"].values() if job.get("name") == "Hosted real-sudo attach"]
    assert len(jobs) == 1, "the dedicated job Hosted real-sudo attach must exist exactly once"
    return jobs[0]


def test_the_full_suite_ignores_only_the_privileged_file_and_the_other_jobs_are_unchanged():
    jobs = _workflow()["jobs"]
    suite = next(step for step in jobs["backend"]["steps"] if step.get("name") == "Run the full backend suite")
    assert f"--ignore={PRIVILEGED_FILE}" in suite["run"]
    assert suite["run"].count("--ignore") == 1
    assert jobs["backend"]["name"] == "Full backend regression tests"
    assert jobs["backend"]["runs-on"] == "ubuntu-latest"


def test_the_dedicated_job_runs_on_the_ubuntu_2404_runner_and_executes_the_privileged_file():
    job = _privileged_job()
    assert job["runs-on"] == "ubuntu-24.04"
    assert isinstance(job.get("timeout-minutes"), int)
    runs = [step.get("run", "") for step in job["steps"]]
    assert any("pytest" in run and PRIVILEGED_FILE in run for run in runs)
    assert any("tests.real_sudo_support" in run for run in runs), "the sudo attestation step is missing"


def test_the_dedicated_job_cannot_succeed_without_running_the_test():
    job = _privileged_job()
    assert "continue-on-error" not in set(_keys(_workflow())), "no job or step may use continue-on-error"
    for step in job["steps"]:
        assert "|| true" not in step.get("run", "") and "|| :" not in step.get("run", "")
        condition = step.get("if")
        assert condition in (None, "steps.changes.outputs.run_suites != 'false'"), f"unexpected condition {condition!r}"
    privileged = next(step for step in job["steps"] if PRIVILEGED_FILE in step.get("run", ""))
    pytest_arguments = privileged["run"].split("pytest", 1)[1].split()  # what is passed to pytest, not python -m
    for forbidden in ("-k", "-m", "-x", "--deselect", "--ignore", "--co", "--collect-only"):
        assert forbidden not in pytest_arguments, f"pytest must run the whole privileged file: {forbidden}"


# --- the lifecycle of the privileged test: fake commands, so it runs anywhere --------------------
#
# These controls drive DisposableAgent with a fake sudo. They check what the privileged test does
# on a collision, on a partial setup, when a cleanup command fails, and when a process survives.


class FakeSudo:
    """Records the commands and can raise for chosen ones. Nothing is executed."""

    def __init__(self, raise_for=()):
        self.commands = []
        self.raise_for = raise_for

    def __call__(self, *args, check=True, timeout=60):
        self.commands.append(args)
        if args[0] in self.raise_for:
            raise subprocess.TimeoutExpired(args, timeout)
        stdout = ""
        staged = next((a for a in args if isinstance(a, str) and a.endswith("/rules")), None)
        if staged and args[0] in ("sh", "install"):
            self.installed = open(staged).read()  # what the fake "installs"
        if args[0] == "cat":
            stdout = getattr(self, "installed", "")
        return subprocess.CompletedProcess(args, 0, stdout, "")

    def names(self):
        return [c[0] for c in self.commands]


@pytest.fixture
def lifecycle(monkeypatch):
    """A DisposableAgent with every outside effect replaced. Returns (agent, fake sudo)."""
    fake = FakeSudo()
    monkeypatch.setattr(real_sudo_support, "run_sudo", fake)
    agent = DisposableAgent()
    agent.process_wait_seconds = 0.2
    monkeypatch.setattr(agent, "_user_exists", lambda: False)
    monkeypatch.setattr(agent, "_path_exists", lambda path: False)
    monkeypatch.setattr(agent, "_processes_of_uid", lambda uid: [])
    yield agent, fake
    shutil.rmtree(agent.work_dir, ignore_errors=True)


def destructive(fake):
    return [c for c in fake.commands if c[0] in ("rm", "userdel", "pkill")]


def test_a_preflight_collision_creates_nothing_and_cleanup_touches_nothing(lifecycle, monkeypatch):
    agent, fake = lifecycle
    monkeypatch.setattr(agent, "_user_exists", lambda: True)  # the generated name is already taken
    monkeypatch.setattr(agent, "check_prerequisites", agent.check_prerequisites)
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    with pytest.raises(AssertionError):
        agent.create()
    assert not any(v for v in agent.owned.values())
    agent.remove()
    assert destructive(fake) == [], "cleanup touched a resource this test did not create"
    assert "useradd" not in fake.names()


def test_a_colliding_file_is_never_overwritten(lifecycle, monkeypatch):
    agent, fake = lifecycle
    agent.owned["user"] = True  # setup got as far as the user
    agent.agent_uid = 4242
    monkeypatch.setattr(agent, "_path_exists", lambda path: path == agent.dropin)  # the file is there
    agent.attempted.add("dropin")  # we tried to create it, but never confirmed that we did
    with pytest.raises(AssertionError) as error:
        agent.remove()
    assert not any(c[0] == "rm" and agent.dropin in c for c in fake.commands), "deleted a file it did not create"
    assert "left in place" in str(error.value)


def test_the_first_creation_of_the_rules_is_exclusive_and_replacement_needs_ownership(lifecycle):
    agent, fake = lifecycle
    agent.setpriv = "/usr/bin/setpriv"
    agent.install_rules(use_pty=True)
    created = [c for c in fake.commands if c[0] == "sh" and agent.dropin in c]
    assert len(created) == 1 and "set -C" in created[0][2], "the first creation must not overwrite"
    assert agent.owned["dropin"]
    agent.install_rules(use_pty=False)  # replacing the owned file is allowed
    assert any(c[0] == "install" and agent.dropin in c for c in fake.commands)


def test_a_partial_setup_cleans_only_what_exists(lifecycle):
    agent, fake = lifecycle
    agent.owned["user"] = True
    agent.agent_uid = 4242
    agent.owned["root_dir"] = True  # the rules were never installed
    agent.remove()
    assert any(c[0] == "userdel" for c in fake.commands)
    assert any(c[0] == "rm" and agent.root_dir in c for c in fake.commands)
    assert not any(c[0] == "rm" and agent.dropin in c for c in fake.commands)


def test_cleanup_continues_after_a_command_raises_and_reports_it(lifecycle, monkeypatch):
    agent, fake = lifecycle
    fake.raise_for = ("pkill",)  # the very first cleanup command times out
    agent.owned.update(user=True, dropin=True, root_dir=True)
    agent.agent_uid = 4242
    with pytest.raises(AssertionError) as error:
        agent.remove()
    assert {"rm", "userdel"} <= set(fake.names()), "later owned cleanup did not run"
    assert "pkill" in str(error.value)


def test_a_surviving_process_stops_the_user_deletion_and_fails_the_cleanup(lifecycle, monkeypatch):
    agent, fake = lifecycle
    agent.owned.update(user=True, dropin=True, root_dir=True)
    agent.agent_uid = 4242
    monkeypatch.setattr(agent, "_processes_of_uid", lambda uid: [31337])
    with pytest.raises(AssertionError) as error:
        agent.remove()
    assert "userdel" not in fake.names(), "the user was deleted while its process still ran"
    assert "31337" in str(error.value)
    assert {"rm"} <= set(fake.names())  # the rules and the directory are still removed


# --- residual failure paths found in review: a partial rules file, and unreadable processes -----


def test_a_failure_after_the_rules_file_is_reserved_is_still_cleaned_up(lifecycle):
    """The file exists but writing its content fails. It is the test's own file, so it is removed."""
    agent, fake = lifecycle
    agent.setpriv = "/usr/bin/setpriv"
    fake.raise_for = ("install",)  # the stage that writes the content fails after the file exists
    with pytest.raises(subprocess.TimeoutExpired):
        agent.install_rules(use_pty=True)
    assert agent.owned["dropin"], "the file was created exclusively, so it must be owned"
    fake.raise_for = ()
    agent.remove()
    assert any(c[0] == "rm" and agent.dropin in c for c in fake.commands), "the partial file was not removed"


def test_a_reservation_that_is_not_proven_leaves_an_existing_file_alone(lifecycle, monkeypatch):
    agent, fake = lifecycle
    agent.setpriv = "/usr/bin/setpriv"
    fake.raise_for = ("sh",)  # the exclusive create itself raises, so nothing is proven
    with pytest.raises(subprocess.TimeoutExpired):
        agent.install_rules(use_pty=True)
    assert not agent.owned["dropin"]
    monkeypatch.setattr(agent, "_path_exists", lambda path: path == agent.dropin)
    with pytest.raises(AssertionError) as error:
        agent.remove()
    assert not any(c[0] == "rm" and agent.dropin in c for c in fake.commands)
    assert "left in place" in str(error.value)


@pytest.fixture
def observed(lifecycle, monkeypatch):
    """The real process observation, over a fake /proc, with a created user to clean up."""
    agent, fake = lifecycle
    monkeypatch.setattr(agent, "_processes_of_uid", DisposableAgent._processes_of_uid.__get__(agent))
    agent.owned.update(user=True, dropin=True, root_dir=True)
    agent.agent_uid = 4242
    return agent, fake


def other_uid_status(pid):
    return "Name:\tsh\nUid:\t1000\t1000\t1000\t1000\n"


def test_an_unreadable_process_keeps_the_user_and_fails_the_cleanup(observed, monkeypatch):
    agent, fake = observed
    monkeypatch.setattr(agent, "_proc_pids", lambda: ["10", "11"])

    def read(pid):
        if pid == "10":
            raise PermissionError(13, "Permission denied")
        return other_uid_status(pid)

    monkeypatch.setattr(agent, "_read_proc_status", read)
    with pytest.raises(AssertionError) as error:
        agent.remove()
    assert "userdel" not in fake.names(), "the user was deleted although a process could not be observed"
    assert "rm" in fake.names(), "the other owned cleanup did not continue"
    assert "processes" in str(error.value)


def test_a_process_that_disappeared_is_not_a_survivor(observed, monkeypatch):
    agent, fake = observed
    monkeypatch.setattr(agent, "_proc_pids", lambda: ["10", "11"])

    def read(pid):
        if pid == "10":
            raise FileNotFoundError(2, "No such file or directory")  # it ended while we looked
        return other_uid_status(pid)

    monkeypatch.setattr(agent, "_read_proc_status", read)
    agent.remove()
    assert "userdel" in fake.names()


def test_a_process_of_the_created_uid_keeps_the_user(observed, monkeypatch):
    agent, fake = observed
    monkeypatch.setattr(agent, "_proc_pids", lambda: ["11"])
    monkeypatch.setattr(agent, "_read_proc_status", lambda pid: "Name:\tsleep\nUid:\t4242\t4242\t4242\t4242\n")
    with pytest.raises(AssertionError) as error:
        agent.remove()
    assert "userdel" not in fake.names()
    assert "11" in str(error.value)


def test_an_invalid_process_status_is_unknown_and_keeps_the_user(observed, monkeypatch):
    agent, fake = observed
    monkeypatch.setattr(agent, "_proc_pids", lambda: ["11"])
    monkeypatch.setattr(agent, "_read_proc_status", lambda pid: "Name:\tsleep\n")  # no Uid line
    with pytest.raises(AssertionError):
        agent.remove()
    assert "userdel" not in fake.names()
