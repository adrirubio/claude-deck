"""Service for managing agents and skills."""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from app.models.schemas import Agent, AgentCreate, AgentUpdate, Skill
from app.utils.path_utils import (
    ensure_directory_exists,
    get_claude_user_agents_dir,
    get_claude_user_skills_dir,
    get_project_agents_dir,
)


class AgentService:
    """Service for managing agents and skills."""

    @staticmethod
    def _get_installed_plugins() -> List[Dict]:
        """
        Read installed_plugins.json to get active plugin paths.

        Returns:
            List of dicts with plugin name, path, and scope
        """
        plugins_file = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
        if not plugins_file.exists():
            return []

        try:
            data = json.loads(plugins_file.read_text(encoding="utf-8"))
            plugins = []
            for plugin_name, installs in data.get("plugins", {}).items():
                for install in installs:
                    install_path = install.get("installPath")
                    if install_path and Path(install_path).exists():
                        plugins.append({
                            "name": plugin_name,
                            "path": install_path,
                            "scope": install.get("scope", "user")
                        })
            return plugins
        except (json.JSONDecodeError, Exception) as e:
            print(f"Error reading installed_plugins.json: {e}")
            return []

    @staticmethod
    def _parse_frontmatter(content: str) -> Tuple[Dict, str]:
        """
        Parse YAML frontmatter from markdown content.

        Returns:
            Tuple of (metadata dict, content without frontmatter)
        """
        # Match frontmatter pattern: ---\n...\n---
        frontmatter_pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
        match = re.match(frontmatter_pattern, content, re.DOTALL)

        if match:
            yaml_content = match.group(1)
            markdown_content = match.group(2).strip()

            try:
                metadata = yaml.safe_load(yaml_content) or {}
            except yaml.YAMLError:
                metadata = {}

            return metadata, markdown_content
        else:
            return {}, content.strip()

    @staticmethod
    def _build_frontmatter(metadata: Dict) -> str:
        """
        Build YAML frontmatter string from metadata dict.

        Args:
            metadata: Dictionary of frontmatter metadata

        Returns:
            Formatted frontmatter string with delimiters
        """
        if not metadata:
            return ""

        yaml_content = yaml.dump(metadata, default_flow_style=False, allow_unicode=True)
        return f"---\n{yaml_content}---\n\n"

    @staticmethod
    def list_agents(project_path: Optional[str] = None) -> List[Agent]:
        """
        List all agents from user, project, and plugin scopes.

        Args:
            project_path: Optional project path for project-scoped agents

        Returns:
            List of Agent objects
        """
        agents = []

        # User agents
        user_agents_dir = get_claude_user_agents_dir()
        if user_agents_dir.exists():
            agents.extend(AgentService._scan_agents_dir(user_agents_dir, "user"))

        # Project agents
        if project_path:
            project_agents_dir = get_project_agents_dir(project_path)
            if project_agents_dir.exists():
                agents.extend(
                    AgentService._scan_agents_dir(project_agents_dir, "project")
                )

        # Plugin agents
        for plugin in AgentService._get_installed_plugins():
            plugin_path = Path(plugin["path"])
            agents_dir = plugin_path / "agents"
            if agents_dir.exists():
                agents.extend(
                    AgentService._scan_agents_dir(
                        agents_dir, f"plugin:{plugin['name']}"
                    )
                )

        return agents

    @staticmethod
    def _scan_agents_dir(base_dir: Path, scope: str) -> List[Agent]:
        """
        Scan an agents directory for .md files.

        Args:
            base_dir: Base agents directory
            scope: "user" or "project"

        Returns:
            List of Agent objects
        """
        agents = []

        # Find all .md files (non-recursive, agents are flat)
        for md_file in base_dir.glob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                metadata, markdown_content = AgentService._parse_frontmatter(content)

                agent_name = md_file.stem  # filename without .md

                # Handle tools as either a list or comma-separated string
                tools_raw = metadata.get("tools")
                if isinstance(tools_raw, str):
                    tools = [t.strip() for t in tools_raw.split(",") if t.strip()]
                else:
                    tools = tools_raw

                agents.append(
                    Agent(
                        name=agent_name,
                        scope=scope,
                        description=metadata.get("description"),
                        tools=tools,
                        model=metadata.get("model"),
                        prompt=markdown_content,
                    )
                )
            except Exception as e:
                print(f"Error reading agent file {md_file}: {e}")
                continue

        return agents

    @staticmethod
    def get_agent(
        scope: str, name: str, project_path: Optional[str] = None
    ) -> Optional[Agent]:
        """
        Get a specific agent by scope and name.

        Args:
            scope: "user" or "project"
            name: Agent name (without .md extension)
            project_path: Optional project path for project-scoped agents

        Returns:
            Agent object or None if not found
        """
        if scope == "user":
            base_dir = get_claude_user_agents_dir()
        else:
            base_dir = get_project_agents_dir(project_path)

        file_path = base_dir / f"{name}.md"
        if not file_path.exists():
            return None

        try:
            content = file_path.read_text(encoding="utf-8")
            metadata, markdown_content = AgentService._parse_frontmatter(content)

            # Handle tools as either a list or comma-separated string
            tools_raw = metadata.get("tools")
            if isinstance(tools_raw, str):
                tools = [t.strip() for t in tools_raw.split(",") if t.strip()]
            else:
                tools = tools_raw

            return Agent(
                name=name,
                scope=scope,
                description=metadata.get("description"),
                tools=tools,
                model=metadata.get("model"),
                prompt=markdown_content,
            )
        except Exception as e:
            print(f"Error reading agent file {file_path}: {e}")
            return None

    @staticmethod
    def create_agent(
        agent: AgentCreate, project_path: Optional[str] = None
    ) -> Agent:
        """
        Create a new agent file.

        Args:
            agent: AgentCreate object with agent data
            project_path: Optional project path for project-scoped agents

        Returns:
            Created Agent object

        Raises:
            ValueError: If agent already exists or invalid scope
        """
        if agent.scope == "user":
            base_dir = get_claude_user_agents_dir()
        elif agent.scope == "project":
            base_dir = get_project_agents_dir(project_path)
        else:
            raise ValueError(f"Invalid scope: {agent.scope}")

        file_path = base_dir / f"{agent.name}.md"

        # Check if file already exists
        if file_path.exists():
            raise ValueError(f"Agent already exists: {agent.name}")

        # Ensure directory exists
        ensure_directory_exists(base_dir)

        # Build frontmatter
        metadata = {}
        if agent.description:
            metadata["description"] = agent.description
        if agent.tools:
            metadata["tools"] = agent.tools
        if agent.model:
            metadata["model"] = agent.model

        frontmatter = AgentService._build_frontmatter(metadata)
        full_content = frontmatter + agent.prompt

        # Write file
        file_path.write_text(full_content, encoding="utf-8")

        return Agent(
            name=agent.name,
            scope=agent.scope,
            description=agent.description,
            tools=agent.tools,
            model=agent.model,
            prompt=agent.prompt,
        )

    @staticmethod
    def update_agent(
        scope: str,
        name: str,
        agent: AgentUpdate,
        project_path: Optional[str] = None,
    ) -> Optional[Agent]:
        """
        Update an existing agent file.

        Args:
            scope: "user" or "project"
            name: Agent name (without .md extension)
            agent: AgentUpdate object with updated data
            project_path: Optional project path for project-scoped agents

        Returns:
            Updated Agent object or None if not found
        """
        if scope == "user":
            base_dir = get_claude_user_agents_dir()
        else:
            base_dir = get_project_agents_dir(project_path)

        file_path = base_dir / f"{name}.md"
        if not file_path.exists():
            return None

        try:
            # Read existing content
            existing_content = file_path.read_text(encoding="utf-8")
            metadata, markdown_content = AgentService._parse_frontmatter(
                existing_content
            )

            # Update metadata
            if agent.description is not None:
                metadata["description"] = agent.description
            if agent.tools is not None:
                metadata["tools"] = agent.tools
            if agent.model is not None:
                metadata["model"] = agent.model

            # Update content
            if agent.prompt is not None:
                markdown_content = agent.prompt

            # Build new content
            frontmatter = AgentService._build_frontmatter(metadata)
            full_content = frontmatter + markdown_content

            # Write file
            file_path.write_text(full_content, encoding="utf-8")

            # Handle tools as either a list or comma-separated string
            tools_raw = metadata.get("tools")
            if isinstance(tools_raw, str):
                tools = [t.strip() for t in tools_raw.split(",") if t.strip()]
            else:
                tools = tools_raw

            return Agent(
                name=name,
                scope=scope,
                description=metadata.get("description"),
                tools=tools,
                model=metadata.get("model"),
                prompt=markdown_content,
            )
        except Exception as e:
            print(f"Error updating agent file {file_path}: {e}")
            return None

    @staticmethod
    def delete_agent(
        scope: str, name: str, project_path: Optional[str] = None
    ) -> bool:
        """
        Delete an agent file.

        Args:
            scope: "user" or "project"
            name: Agent name (without .md extension)
            project_path: Optional project path for project-scoped agents

        Returns:
            True if deleted, False if not found
        """
        if scope == "user":
            base_dir = get_claude_user_agents_dir()
        else:
            base_dir = get_project_agents_dir(project_path)

        file_path = base_dir / f"{name}.md"
        if not file_path.exists():
            return False

        try:
            file_path.unlink()
            return True
        except Exception as e:
            print(f"Error deleting agent file {file_path}: {e}")
            return False

    @staticmethod
    def list_skills(project_path: Optional[str] = None) -> List[Skill]:
        """
        List all skills from user, project, and plugin directories.

        Args:
            project_path: Optional project path for project-scoped skills

        Returns:
            List of Skill objects
        """
        skills = []

        # User skills (~/.claude/skills/)
        user_skills_dir = get_claude_user_skills_dir()
        if user_skills_dir.exists():
            skills.extend(AgentService._scan_skills_dir(user_skills_dir, "user"))

        # Project skills (.claude/skills/)
        if project_path:
            project_skills_dir = Path(project_path) / ".claude" / "skills"
            if project_skills_dir.exists():
                skills.extend(
                    AgentService._scan_skills_dir(project_skills_dir, "project")
                )

        # Plugin skills - from installed plugins
        for plugin in AgentService._get_installed_plugins():
            plugin_path = Path(plugin["path"])
            skills_dir = plugin_path / "skills"
            if skills_dir.exists():
                skills.extend(
                    AgentService._scan_plugin_skills_dir(
                        skills_dir, f"plugin:{plugin['name']}"
                    )
                )

        return skills

    @staticmethod
    def _scan_skills_dir(base_dir: Path, location: str) -> List[Skill]:
        """
        Scan a skills directory for skill files.

        Supports two layouts:
        1. Flat .md files: base_dir/skill-name.md
        2. Subdirectories with SKILL.md: base_dir/skill-name/SKILL.md
           (used by `npx skills add` and symlinked from ~/.agents/skills/)

        Args:
            base_dir: Base skills directory
            location: Skill location identifier

        Returns:
            List of Skill objects
        """
        skills = []
        seen_names = set()

        # Layout 1: Flat .md files with frontmatter
        for skill_file in base_dir.glob("*.md"):
            try:
                content = skill_file.read_text(encoding="utf-8")
                metadata, _ = AgentService._parse_frontmatter(content)

                skill_name = skill_file.stem
                seen_names.add(skill_name)

                skills.append(
                    Skill(
                        name=skill_name,
                        description=metadata.get("description"),
                        location=location,
                    )
                )
            except Exception as e:
                print(f"Error reading skill file {skill_file}: {e}")
                continue

        # Layout 2: Subdirectories with SKILL.md
        for item in base_dir.iterdir():
            if not item.is_dir():
                continue
            skill_file = item / "SKILL.md"
            if not skill_file.exists():
                # Check for nested skills (e.g. nextjs/vercel-ai-sdk/SKILL.md)
                for sub in item.iterdir():
                    if sub.is_dir():
                        sub_skill = sub / "SKILL.md"
                        if sub_skill.exists() and sub.name not in seen_names:
                            try:
                                content = sub_skill.read_text(encoding="utf-8")
                                metadata, _ = AgentService._parse_frontmatter(content)
                                seen_names.add(sub.name)
                                skills.append(
                                    Skill(
                                        name=sub.name,
                                        description=metadata.get("description"),
                                        location=location,
                                    )
                                )
                            except Exception as e:
                                print(f"Error reading skill {sub_skill}: {e}")
                continue
            if item.name in seen_names:
                continue
            try:
                content = skill_file.read_text(encoding="utf-8")
                metadata, _ = AgentService._parse_frontmatter(content)
                seen_names.add(item.name)
                skills.append(
                    Skill(
                        name=item.name,
                        description=metadata.get("description"),
                        location=location,
                    )
                )
            except Exception as e:
                print(f"Error reading skill {skill_file}: {e}")
                continue

        return skills

    @staticmethod
    def _scan_plugin_skills_dir(base_dir: Path, location: str) -> List[Skill]:
        """
        Scan a plugin skills directory for SKILL.md files in subdirectories.

        Plugin skills are stored as: skills/{skill-name}/SKILL.md

        Args:
            base_dir: Base skills directory (e.g., {plugin_path}/skills/)
            location: Skill location identifier

        Returns:
            List of Skill objects
        """
        skills = []

        # Each subdirectory is a skill with a SKILL.md file
        for skill_subdir in base_dir.iterdir():
            if not skill_subdir.is_dir():
                continue

            skill_file = skill_subdir / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                content = skill_file.read_text(encoding="utf-8")
                metadata, _ = AgentService._parse_frontmatter(content)

                skill_name = skill_subdir.name  # directory name is skill name

                skills.append(
                    Skill(
                        name=skill_name,
                        description=metadata.get("description"),
                        location=location,
                    )
                )
            except Exception as e:
                print(f"Error reading skill file {skill_file}: {e}")
                continue

        return skills

    @staticmethod
    def get_skill(
        name: str, location: str, project_path: Optional[str] = None
    ) -> Optional[Skill]:
        """
        Get a specific skill by name and location with full content.

        Args:
            name: Skill name
            location: Skill location ("user", "project", or "plugin:pluginname")
            project_path: Optional project path

        Returns:
            Skill object with content or None if not found
        """
        skill_file = None

        if location == "user":
            user_skills_dir = get_claude_user_skills_dir()
            skill_file = user_skills_dir / f"{name}.md"
        elif location == "project" and project_path:
            project_skills_dir = Path(project_path) / ".claude" / "skills"
            skill_file = project_skills_dir / f"{name}.md"
        elif location.startswith("plugin:"):
            # Find the plugin's skill file
            plugin_name = location.replace("plugin:", "")
            for plugin in AgentService._get_installed_plugins():
                if plugin["name"] == plugin_name:
                    plugin_path = Path(plugin["path"])
                    skill_file = plugin_path / "skills" / name / "SKILL.md"
                    break

        if not skill_file or not skill_file.exists():
            return None

        try:
            content = skill_file.read_text(encoding="utf-8")
            metadata, markdown_content = AgentService._parse_frontmatter(content)

            return Skill(
                name=name,
                description=metadata.get("description"),
                location=location,
                content=markdown_content,
            )
        except Exception as e:
            print(f"Error reading skill file {skill_file}: {e}")
            return None
