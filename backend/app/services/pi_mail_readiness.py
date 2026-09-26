from functools import lru_cache
from pathlib import Path
import shutil
import subprocess
import sys
import time

from app.services.providers.pi_cli import PiCliProvider


def integration_path() -> Path:
    return Path(__file__).resolve().parents[3] / "integrations" / "pi-agent-mail"


@lru_cache(maxsize=1)
def _probe(time_bucket: int) -> tuple[bool, str | None]:
    binary = shutil.which("pi")
    node = shutil.which("node")
    if not binary or not node:
        return False, "Pi and Node must be installed"
    if PiCliProvider().get_version() != "0.87.1":
        return False, "Pi 0.87.1 is required by this integration"
    assets = integration_path()
    shim = Path(__file__).resolve().parents[2] / "mcp_shim" / "agent_mail_server.py"
    if not all(candidate.is_file() for candidate in [assets / "extension.ts", assets / "manifest.ts", assets / "readiness.mjs", shim]):
        return False, "Deck Pi extension assets are missing"
    try:
        python = subprocess.run([sys.executable, "-I", "-c", "import mcp, httpx"], capture_output=True, timeout=5)
        runtime = subprocess.run([node, str(assets / "readiness.mjs"), str(Path(binary).resolve())], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False, "Pi extension runtime probe failed"
    if python.returncode or runtime.returncode or runtime.stdout != b"ready":
        return False, "Pi extension dependencies/runtime are incomplete; prepare the integration package"
    return True, None


def pi_mail_readiness() -> tuple[bool, str | None]:
    return _probe(int(time.monotonic() // 30))


def pi_mail_environment() -> dict[str, str]:
    from app.services.agent_mail_install_service import deck_base_url, shim_path

    return {
        "CLAUDE_DECK_MAIL_OPT_IN": "1",
        "CLAUDE_DECK_PROVIDER": "pi-cli",
        "CLAUDE_DECK_URL": deck_base_url(),
        "CLAUDE_DECK_MAIL_PYTHON": str(Path(sys.executable).absolute()),
        "CLAUDE_DECK_MAIL_SHIM": shim_path(),
    }
