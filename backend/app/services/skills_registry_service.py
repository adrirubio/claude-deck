"""Service for interacting with skills.sh registry."""
import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# Cache settings
CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours
SEARCH_CACHE_TTL_SECONDS = 60 * 60  # 1 hour for search results

SKILLS_SH_BASE = "https://skills.sh"
SKILLS_SH_SEARCH_API = f"{SKILLS_SH_BASE}/api/search"


class RegistrySkill:
    """A skill from the skills.sh registry."""

    def __init__(
        self,
        skill_id: str,
        name: str,
        source: str,
        installs: int,
        registry_id: str = "",
    ):
        self.skill_id = skill_id
        self.name = name
        self.source = source  # e.g. "vercel-labs/agent-skills"
        self.installs = installs
        self.registry_id = registry_id or f"{source}/{skill_id}"

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "source": self.source,
            "installs": self.installs,
            "registry_id": self.registry_id,
            "url": f"{SKILLS_SH_BASE}/s/{self.source}/{self.skill_id}",
            "github_url": f"https://github.com/{self.source}",
        }


class SkillsRegistryService:
    """Service for browsing and installing skills from skills.sh."""

    # In-memory cache
    _homepage_cache: Optional[Tuple[List[dict], float]] = None
    _search_cache: Dict[str, Tuple[List[dict], float]] = {}

    @classmethod
    def _is_cache_valid(cls, cache_time: float, ttl: float) -> bool:
        return (time.time() - cache_time) < ttl

    @classmethod
    def get_homepage_skills(cls, force_refresh: bool = False) -> List[dict]:
        """
        Fetch the full skills leaderboard from skills.sh homepage.
        Scrapes the embedded Next.js SSR data for the complete catalog.
        Results are cached for 24 hours.
        """
        if (
            not force_refresh
            and cls._homepage_cache
            and cls._is_cache_valid(cls._homepage_cache[1], CACHE_TTL_SECONDS)
        ):
            return cls._homepage_cache[0]

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(SKILLS_SH_BASE)
                resp.raise_for_status()
                html = resp.text

            # Extract skills from Next.js __next_f embedded data
            skills = cls._parse_homepage_skills(html)

            if skills:
                cls._homepage_cache = (skills, time.time())
                logger.info(f"Cached {len(skills)} skills from skills.sh homepage")
            else:
                logger.warning("No skills found in skills.sh homepage HTML")

            return skills

        except Exception as e:
            logger.error(f"Failed to fetch skills.sh homepage: {e}")
            # Return stale cache if available
            if cls._homepage_cache:
                return cls._homepage_cache[0]
            return []

    @classmethod
    def _parse_homepage_skills(cls, html: str) -> List[dict]:
        """Parse skill data from Next.js SSR HTML."""
        skills = []

        # Find __next_f data chunks containing skill objects
        pattern = r'self\.__next_f\.push\(\[1,"(.*?)"\]\)'
        matches = re.findall(pattern, html, re.DOTALL)

        for chunk in matches:
            # Unescape the JSON string
            clean = chunk.replace('\\"', '"').replace("\\n", "\n")

            if "skillId" not in clean or "installs" not in clean:
                continue

            # Extract individual skill objects
            skill_pattern = r'\{"source":"([^"]+)","skillId":"([^"]+)","name":"([^"]+)","installs":(\d+)\}'
            skill_matches = re.findall(skill_pattern, clean)

            for source, skill_id, name, installs in skill_matches:
                skill = RegistrySkill(
                    skill_id=skill_id,
                    name=name,
                    source=source,
                    installs=int(installs),
                )
                skills.append(skill.to_dict())

        return skills

    @classmethod
    def search_skills(cls, query: str, limit: int = 20) -> List[dict]:
        """
        Search skills.sh via their API.
        Requires query >= 2 characters.
        """
        if len(query) < 2:
            return []

        cache_key = f"{query}:{limit}"
        cached = cls._search_cache.get(cache_key)
        if cached and cls._is_cache_valid(cached[1], SEARCH_CACHE_TTL_SECONDS):
            return cached[0]

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    SKILLS_SH_SEARCH_API,
                    params={"q": query, "limit": limit},
                )
                resp.raise_for_status()
                data = resp.json()

            skills = []
            for s in data.get("skills", []):
                skill = RegistrySkill(
                    skill_id=s.get("skillId", ""),
                    name=s.get("name", ""),
                    source=s.get("source", ""),
                    installs=s.get("installs", 0),
                    registry_id=s.get("id", ""),
                )
                skills.append(skill.to_dict())

            cls._search_cache[cache_key] = (skills, time.time())
            return skills

        except Exception as e:
            logger.error(f"Failed to search skills.sh: {e}")
            if cached:
                return cached[0]
            return []

    @classmethod
    def get_installed_skill_sources(cls, project_path: Optional[str] = None) -> set:
        """
        Get set of source repos that are currently installed locally.
        Reads from ~/.claude/skills/ and optionally project .claude/skills/.
        """
        installed = set()
        user_skills_dir = Path.home() / ".claude" / "skills"

        if user_skills_dir.exists():
            for skill_dir in user_skills_dir.iterdir():
                if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                    installed.add(skill_dir.name)

        if project_path:
            project_skills_dir = Path(project_path) / ".claude" / "skills"
            if project_skills_dir.exists():
                for skill_dir in project_skills_dir.iterdir():
                    if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                        installed.add(skill_dir.name)

        return installed

    @classmethod
    def install_skill(
        cls,
        source: str,
        skill_names: Optional[List[str]] = None,
        global_install: bool = True,
        project_path: Optional[str] = None,
    ) -> dict:
        """
        Install a skill from the registry using `npx skills add`.

        Args:
            source: GitHub repo path (e.g. "vercel-labs/agent-skills")
            skill_names: Optional list of specific skill names to install.
                         If None, installs all skills from the repo.
            global_install: Whether to install globally (user-level).
            project_path: Project path for project-level installs.

        Returns:
            dict with success, message, and logs.
        """
        cmd = ["npx", "-y", "skills", "add", source]

        if global_install:
            cmd.append("--global")

        if skill_names:
            cmd.extend(["--skill", ",".join(skill_names)])

        env = None
        cwd = project_path if project_path and not global_install else None

        try:
            logger.info(f"Installing skill: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=cwd,
                env=env,
            )

            logs = result.stdout + ("\n" + result.stderr if result.stderr else "")
            success = result.returncode == 0

            return {
                "success": success,
                "message": (
                    f"Successfully installed skill(s) from {source}"
                    if success
                    else f"Installation failed (exit code {result.returncode})"
                ),
                "logs": logs.strip(),
                "source": source,
                "skill_names": skill_names,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": "Installation timed out (120s)",
                "logs": "",
                "source": source,
                "skill_names": skill_names,
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Installation error: {str(e)}",
                "logs": "",
                "source": source,
                "skill_names": skill_names,
            }

    @classmethod
    def list_available_skills_in_repo(cls, source: str) -> List[str]:
        """
        List available skill names in a remote repo using `npx skills add --list`.

        Args:
            source: GitHub repo path (e.g. "vercel-labs/agent-skills")

        Returns:
            List of skill names available in the repo.
        """
        try:
            result = subprocess.run(
                ["npx", "-y", "skills", "add", source, "--list"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                logger.warning(f"Failed to list skills in {source}: {result.stderr}")
                return []

            # Parse the output — each line is typically a skill name
            names = []
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith(("npm", "npx", "added", "Fetching")):
                    names.append(line)

            return names

        except Exception as e:
            logger.error(f"Failed to list skills in {source}: {e}")
            return []
