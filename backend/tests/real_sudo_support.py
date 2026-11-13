"""Support for the hosted real-sudo attach regression (#880, moved out of #877).

The production service runs with a limited capability set: no CAP_KILL and no CAP_CHOWN. With
`use_pty`, sudo then cannot allocate the pty it needs ("unable to allocate pty"). With a
command-scoped `!use_pty` the attach works and the kernel delivers the resize.

The privileged test uses real `sudo`. It creates a disposable OS user and a new file in /etc/sudoers.d,
and it runs `sudo setpriv`. That is only acceptable on an ephemeral machine. It runs ONLY on
GitHub-hosted Linux runners. There is no other way to turn it on. Where it runs, a missing
prerequisite FAILS the test: it never skips. Everything it creates has a unique random name,
is removed even when the test fails, and its removal is checked. It never edits /etc/sudoers,
a pre-existing sudoers file, a pre-existing user or a pre-existing rule.

A nonzero exit of the attach is not accepted as the negative result. Before either phase the
test attests the sudo it runs against (exactly production's upstream version, 1.9.15p5, and not
sudo-rs) and the setup: the controller and agent identities, the exact reduced bounding set, and
the sudo rule. The negative phase must show the specific refusal to allocate a pty, and no sign of
a wrong setup. The positive phase uses the same user, program, launcher, bounding set and session,
and changes only the command-scoped use_pty line. It checks the sizes the attached program reports.

Run `python -m tests.real_sudo_support` from backend/ to print the sudo attestation.
"""
import getpass
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import asyncio

import pytest

# Production's sudo. The claim of this regression is this exact upstream version.
EXPECTED_SUDO_UPSTREAM = "1.9.15p5"

PRODUCTION_BOUNDING_SET = "-all,+dac_override,+dac_read_search,+setgid,+setuid,+sys_ptrace"
CAP_CHOWN, CAP_DAC_OVERRIDE, CAP_DAC_READ_SEARCH, CAP_KILL = 0, 1, 2, 5
CAP_SETGID, CAP_SETUID, CAP_SYS_PTRACE = 6, 7, 19
EXPECTED_CAPBND = sum(
    1 << bit for bit in (CAP_DAC_OVERRIDE, CAP_DAC_READ_SEARCH, CAP_SETGID, CAP_SETUID, CAP_SYS_PTRACE)
)

# Prints the pty size each time it receives SIGWINCH, as the tmux client does.
CAPABILITY_ATTACH_PROGRAM = (
    "#!/bin/sh\n"
    "trap 'echo \"WINCH:$(stty size)\"' WINCH\n"
    "echo ready\n"
    "while :; do sleep 0.05; done\n"
)

# Prints who it runs as and its bounding set. It runs under !use_pty, so it works under the limits.
CAPABILITY_PROBE_PROGRAM = (
    "#!/bin/sh\n"
    'echo "ID:$(id -u):$(id -un)"\n'
    "grep '^CapBnd:' /proc/self/status\n"
)

# What sudo prints when a setup is wrong. None of these may be in the negative result.
WRONG_SETUP_MARKERS = (
    "a password is required", "is not in the sudoers", "may not run sudo", "not allowed to",
    "command not found", "No such file or directory", "no tty present", "a terminal is required",
    "unknown user", "sudoers",
)


def is_ephemeral_hosted_runner(environ) -> bool:
    """True only on a GitHub-hosted Linux runner, which is a fresh virtual machine for every job."""
    return (
        environ.get("GITHUB_ACTIONS") == "true"
        and environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
        and environ.get("RUNNER_OS") == "Linux"
    )


hosted_runner_only = pytest.mark.skipif(
    not is_ephemeral_hosted_runner(os.environ),
    reason="creates a disposable OS user and a sudoers.d file, so it runs only on ephemeral GitHub-hosted runners",
)



def run_sudo(*args, check=True, timeout=60):
    result = subprocess.run(["sudo", "-n", *args], capture_output=True, text=True, timeout=timeout)
    if check:
        assert result.returncode == 0, f"sudo -n {' '.join(args)} failed ({result.returncode}): {result.stderr.strip()}"
    return result


def parse_capbnd(text: str) -> int:
    lines = [line for line in text.splitlines() if line.startswith("CapBnd:")]
    assert len(lines) == 1, f"expected one CapBnd line, saw {text!r}"
    return int(lines[0].split(":", 1)[1].strip(), 16)


class ProcessObservationError(OSError):
    """The processes of the created user could not be observed reliably."""


class DisposableAgent:
    """A new OS user, a new sudoers.d file and root-owned programs, all with unique names."""

    def __init__(self):
        self.suffix = secrets.token_hex(4)
        self.user = f"sctrial{self.suffix}"
        self.dropin = f"/etc/sudoers.d/zz-sctrial-{self.suffix}"
        self.root_dir = f"/tmp/sctrial-{self.suffix}"
        self.program = f"{self.root_dir}/attach.sh"
        self.probe = f"{self.root_dir}/probe.sh"
        self.work_dir = tempfile.mkdtemp(prefix=f"sctrial-{self.suffix}-")
        self.launcher = f"{self.work_dir}/launcher.sh"
        self.probe_launcher = f"{self.work_dir}/probe-launcher.sh"
        self.outer_probe = f"{self.work_dir}/outer-probe.sh"
        self.setpriv = None
        self.me = getpass.getuser()
        # A resource is "owned" only after this test created it successfully. Cleanup touches
        # nothing else, whatever name was generated. "attempted" is what we tried to create.
        self.owned = {"user": False, "root_dir": False, "dropin": False}
        self.attempted = set()
        self.agent_uid = None
        self.process_wait_seconds = 5.0

    def _stage(self, name, content, mode=0o644):
        path = f"{self.work_dir}/{name}"
        with open(path, "w") as handle:
            handle.write(content)
        os.chmod(path, mode)
        return path

    def rules(self, use_pty: bool) -> str:
        """The only text that differs between the two phases is the last line."""
        return (
            f"# disposable rules for the #749 regression test {self.suffix}\n"
            f"{self.me} ALL=(root) NOPASSWD: {self.setpriv}\n"
            f"Defaults!{self.setpriv} !use_pty\n"
            f"{self.me} ALL=({self.user}) NOPASSWD: {self.program}, {self.probe}\n"
            f"Defaults!{self.probe} !use_pty\n"
            f"Defaults!{self.program} {'use_pty' if use_pty else '!use_pty'}\n"
        )

    def _user_exists(self) -> bool:
        return subprocess.run(["getent", "passwd", self.user], capture_output=True).returncode == 0

    def _path_exists(self, path) -> bool:
        return os.path.exists(path)

    def _proc_pids(self) -> list:
        return [entry for entry in os.listdir("/proc") if entry.isdigit()]

    def _read_proc_status(self, pid) -> str:
        with open(f"/proc/{pid}/status") as handle:
            return handle.read()

    def _processes_of_uid(self, uid) -> list:
        """Pids whose real uid is uid, read from /proc. It does not depend on the user name.

        Only a process that is confirmed gone (it ended while we looked) is ignored. Anything that
        cannot be read or understood raises, so the caller treats the observation as unknown.
        """
        pids = []
        for pid in self._proc_pids():
            try:
                status = self._read_proc_status(pid)
            except (FileNotFoundError, ProcessLookupError):
                continue  # confirmed gone
            except OSError as error:
                raise ProcessObservationError(f"cannot read the status of process {pid}: {error}") from error
            line = next((line for line in status.splitlines() if line.startswith("Uid:")), None)
            try:
                real_uid = int(line.split()[1])
            except (AttributeError, IndexError, ValueError):
                raise ProcessObservationError(f"the status of process {pid} has no readable Uid line") from None
            if real_uid == uid:
                pids.append(int(pid))
        return pids

    def _wait_for_no_processes(self, uid) -> list:
        deadline = time.monotonic() + self.process_wait_seconds
        remaining = self._processes_of_uid(uid)
        while remaining and time.monotonic() < deadline:
            time.sleep(0.1)
            remaining = self._processes_of_uid(uid)
        return remaining

    def check_prerequisites(self):
        assert shutil.which("sudo"), "the privileged regression needs sudo on this hosted runner"
        run_sudo("true")
        for tool in ("setpriv", "visudo", "useradd", "userdel", "install", "mkdir", "rm", "pkill", "cat", "sh"):
            found = run_sudo("sh", "-c", f"command -v {tool}", check=False)
            assert found.returncode == 0, f"the privileged regression needs {tool} on this hosted runner"
        assert os.getuid() != 0, "the controller identity must not be root"
        assert not self._user_exists(), f"the generated user {self.user} already exists"
        assert not self._path_exists(self.dropin), f"{self.dropin} already exists"
        assert not self._path_exists(self.root_dir), f"{self.root_dir} already exists"

    def create(self):
        self.check_prerequisites()
        self.setpriv = run_sudo("sh", "-c", "command -v setpriv").stdout.strip()
        uid, gid = os.getuid(), os.getgid()
        self.attempted.add("user")
        run_sudo("useradd", "--no-create-home", "--shell", "/bin/sh", self.user)  # fails if the user exists
        self.owned["user"] = True
        self.agent_uid = int(run_sudo("id", "-u", self.user).stdout.strip() or 0) or None
        self.attempted.add("root_dir")
        run_sudo("mkdir", "-m", "0755", self.root_dir)  # fails if the directory exists
        self.owned["root_dir"] = True
        for name, content, target in (
            ("attach.sh", CAPABILITY_ATTACH_PROGRAM, self.program),
            ("probe.sh", CAPABILITY_PROBE_PROGRAM, self.probe),
        ):
            staged = self._stage(name, content, 0o755)
            run_sudo("install", "-m", "0755", "-o", "root", "-g", "root", staged, target)
        reduced = (
            f"sudo -n {self.setpriv} --bounding-set={PRODUCTION_BOUNDING_SET} "
            f"--reuid={uid} --regid={gid} --init-groups"
        )
        self._stage("launcher.sh", f"#!/bin/sh\nexec {reduced} sudo -n -u {self.user} {self.program}\n", 0o755)
        self._stage("probe-launcher.sh", f"#!/bin/sh\nexec {reduced} sudo -n -u {self.user} {self.probe}\n", 0o755)
        self._stage(
            "outer-probe.sh",
            f"#!/bin/sh\nexec {reduced} sh -c 'echo \"ID:$(id -u)\"; grep \"^CapBnd:\" /proc/self/status'\n",
            0o755,
        )

    def install_rules(self, use_pty: bool):
        """Install the rules, replacing only this object's own file. A bad file is never installed."""
        rules = self.rules(use_pty)
        staged = self._stage("rules", rules)
        run_sudo("visudo", "-cf", staged)
        if not self.owned["dropin"]:
            # Step 1: reserve the name with an empty file, exclusively (noclobber). If this succeeds,
            # this test created the file, and from then on it is owned and cleaned up. An existing
            # file is never overwritten. An empty sudoers file is valid.
            self.attempted.add("dropin")
            run_sudo("sh", "-c", 'set -C; : > "$1"', "sh", self.dropin)
            self.owned["dropin"] = True
        # Step 2: write the content and the mode. Only the owned file is replaced. If this fails,
        # the file is still owned, so cleanup removes it.
        run_sudo("install", "-m", "0440", "-o", "root", "-g", "root", staged, self.dropin)
        run_sudo("true")  # sudo still works with the new file
        installed = run_sudo("cat", self.dropin).stdout
        assert installed == rules, f"the installed rules are not the intended rules: {installed!r}"

    def attest(self):
        """Attest the setup before a phase. Wrong setup errors fail here and not later."""
        controller = os.getuid()
        outer = subprocess.run([self.outer_probe], capture_output=True, text=True, timeout=60)
        assert outer.returncode == 0, f"the controller probe failed: {outer.stderr.strip()}"
        assert f"ID:{controller}" in outer.stdout.splitlines()
        outer_capbnd = parse_capbnd(outer.stdout)
        inner = subprocess.run([self.probe_launcher], capture_output=True, text=True, timeout=60)
        assert inner.returncode == 0, f"the agent probe through sudo failed: {inner.stderr.strip()}"
        identity = next((l for l in inner.stdout.splitlines() if l.startswith("ID:")), "")
        _, agent_uid, agent_user = identity.split(":", 2)
        assert agent_user == self.user, f"the probe ran as {agent_user!r}, not {self.user!r}"
        assert int(agent_uid) not in (0, controller), "the agent must be a distinct non-root identity"
        inner_capbnd = parse_capbnd(inner.stdout)
        for capbnd in (outer_capbnd, inner_capbnd):
            assert capbnd == EXPECTED_CAPBND, f"CapBnd {capbnd:#x} is not the production set {EXPECTED_CAPBND:#x}"
            assert not capbnd & (1 << CAP_CHOWN) and not capbnd & (1 << CAP_KILL)

    def remove(self):
        """Remove only what this test created, and check that it is gone.

        Every step is tried even if an earlier one fails, and all failures are reported together.
        A resource that was only attempted, or that already existed, is never deleted or signalled.
        The user is deleted only after its processes are confirmed gone, so no process can survive
        under a deleted numeric uid.
        """
        errors = []

        def step(label, action):
            try:
                action()
            except (subprocess.TimeoutExpired, OSError, AssertionError) as error:
                errors.append(f"{label}: {error}")

        survivors = []
        if self.owned["user"]:
            if self.agent_uid is None:
                errors.append("the uid of the created user is unknown, so its processes cannot be checked")
                survivors = ["unknown"]
            else:
                step("pkill", lambda: run_sudo("pkill", "-KILL", "-u", str(self.agent_uid), check=False))
                try:
                    survivors = self._wait_for_no_processes(self.agent_uid)
                except OSError as error:
                    errors.append(f"checking the processes: {error}")
                    survivors = ["unknown"]
                if survivors:
                    errors.append(f"processes of uid {self.agent_uid} are still running: {survivors}; the user was not deleted")
        if self.owned["dropin"]:
            step("remove the rules", lambda: run_sudo("rm", "-f", self.dropin, check=False))
        if self.owned["user"] and not survivors:
            step("userdel", lambda: run_sudo("userdel", "-f", self.user, check=False))
        if self.owned["root_dir"]:
            step("remove the program directory", lambda: run_sudo("rm", "-rf", self.root_dir, check=False))
        step("remove the work directory", lambda: shutil.rmtree(self.work_dir, ignore_errors=True))

        if self.owned["user"] and not survivors and self._user_exists():
            errors.append(f"user {self.user} is still there")
        if self.owned["dropin"] and self._path_exists(self.dropin):
            errors.append(f"{self.dropin} is still there")
        if self.owned["root_dir"] and self._path_exists(self.root_dir):
            errors.append(f"{self.root_dir} is still there")
        if self._path_exists(self.work_dir):
            errors.append(f"{self.work_dir} is still there")
        paths = {"dropin": self.dropin, "root_dir": self.root_dir}
        for name in sorted(self.attempted - {k for k, v in self.owned.items() if v}):
            if name in paths and self._path_exists(paths[name]):
                errors.append(f"{paths[name]} exists but this test did not confirm creating it, so it was left in place")
        assert not errors, "the privileged regression cleanup failed: " + "; ".join(errors)


async def wait_for_terminal_bytes(websocket, needle: bytes, timeout=30.0):
    deadline = time.monotonic() + timeout
    while needle not in websocket.sent:
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {needle!r}; the terminal showed {websocket.sent!r}")
        await asyncio.sleep(0.05)



# --- which sudo this runner has ------------------------------------------------------------------


class SudoAttestationError(AssertionError):
    """The sudo on this runner is not the sudo the regression claims to represent."""


def parse_sudo_version(text: str):
    """The upstream version from the first line of `sudo --version`, or None.

    Only the exact first line "Sudo version <version>" of the original sudo counts. sudo-rs prints
    "sudo-rs <version>", and anything else is not an upstream sudo version.
    """
    first = text.splitlines()[0] if text.splitlines() else ""
    match = re.fullmatch(r"Sudo version (\S+)", first)
    return match.group(1) if match else None


def _own_capbnd() -> int:
    with open("/proc/self/status") as handle:
        return parse_capbnd(handle.read())


def attest_sudo(run=subprocess.run, which=shutil.which, realpath=os.path.realpath, environ=None, kernel=None, capbnd=None) -> dict:
    """The facts about the sudo on this runner. Every outside effect can be replaced in a test."""
    environ = os.environ if environ is None else environ
    executable = which("sudo")
    facts = {
        "executable": executable,
        "resolved_executable": realpath(executable) if executable else None,
        "version_line": None,
        "upstream_version": None,
        "is_sudo_rs": False,
        "package": "unknown",
        "image_os": environ.get("ImageOS", "unknown"),
        "image_version": environ.get("ImageVersion", "unknown"),
        "kernel": kernel() if kernel else os.uname().release,
        "controller_capbnd": (capbnd or _own_capbnd)(),
    }
    if not executable:
        return facts
    version = run([executable, "--version"], capture_output=True, text=True, timeout=30)
    first = version.stdout.splitlines()[0] if version.stdout.splitlines() else ""
    facts["version_line"] = first
    facts["upstream_version"] = parse_sudo_version(version.stdout)
    resolved = facts["resolved_executable"] or ""
    facts["is_sudo_rs"] = "sudo-rs" in first or "sudo-rs" in resolved or "/cargo/bin/" in resolved
    package = run(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Architecture}", "sudo"], capture_output=True, text=True, timeout=30)
    if package.returncode == 0 and package.stdout.strip():
        facts["package"] = package.stdout.strip().replace("\t", " ")
    return facts


def format_sudo_facts(facts: dict) -> str:
    return "\n".join((
        "sudo attestation:",
        f"  executable: {facts['executable']} (resolved: {facts['resolved_executable']})",
        f"  version line: {facts['version_line']!r}",
        f"  upstream version: {facts['upstream_version']} (claimed: {EXPECTED_SUDO_UPSTREAM})",
        f"  sudo-rs: {facts['is_sudo_rs']}",
        f"  package: {facts['package']}",
        f"  image: {facts['image_os']} {facts['image_version']}",
        f"  kernel: {facts['kernel']}",
        f"  controller bounding set before reduction: {facts['controller_capbnd']:#x}",
    ))


def require_original_sudo(facts: dict) -> None:
    """Stop unless this runner has production's sudo, exactly. Another version is a mismatch."""
    if not facts["executable"]:
        raise SudoAttestationError("no sudo was found on this runner. " + format_sudo_facts(facts))
    if facts["is_sudo_rs"]:
        raise SudoAttestationError(
            f"this runner's sudo is sudo-rs, not the original sudo {EXPECTED_SUDO_UPSTREAM}. " + format_sudo_facts(facts)
        )
    if facts["upstream_version"] != EXPECTED_SUDO_UPSTREAM:
        raise SudoAttestationError(
            f"this runner's sudo is upstream version {facts['upstream_version']!r}, "
            f"not {EXPECTED_SUDO_UPSTREAM}. " + format_sudo_facts(facts)
        )


def main() -> int:
    facts = attest_sudo()
    text = format_sudo_facts(facts)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as handle:
            handle.write("```\n" + text + "\n```\n")
    try:
        require_original_sudo(facts)
    except SudoAttestationError as error:
        print(f"MISMATCH: {error}", file=sys.stderr)
        return 1
    print(f"OK: the original sudo {EXPECTED_SUDO_UPSTREAM}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
