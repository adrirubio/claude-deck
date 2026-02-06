"""Service for managing agents and skills."""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from app.models.schemas import Agent, AgentCreate, AgentUpdate, AgentHook, Skill, SkillFrontmatter
from app.utils.path_utils import (
    ensure_directory_exists,
    get_claude_user_agents_dir,
    get_claude_user_skills_dir,
    get_project_agents_dir,
)


def get_agent_memory_dir(agent_name: str) -> Path:
    """Get the memory directory for an agent."""
    return Path.home() / ".claude" / "agent-memory" / agent_name


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
    def _metadata_to_frontmatter(metadata: Dict) -> SkillFrontmatter:
        """Convert raw frontmatter dict to SkillFrontmatter model."""
        # The "metadata" sub-dict can also contain some fields
        meta_sub = metadata.get("metadata") or {}

        # Handle hyphenated keys -> underscored fields
        # Check both top-level and metadata sub-dict
        allowed_tools = (
            metadata.get("allowed-tools")
            or metadata.get("allowed_tools")
            or meta_sub.get("allowed-tools")
        )
        if isinstance(allowed_tools, str):
            # Can be comma-separated or YAML list
            allowed_tools = [t.strip() for t in allowed_tools.split(",") if t.strip()]

        user_invocable = metadata.get(
            "user-invocable", metadata.get("user_invocable")
        )
        disable_model = metadata.get(
            "disable-model-invocation", metadata.get("disable_model_invocation")
        )
        argument_hint = (
            metadata.get("argument-hint")
            or metadata.get("argument_hint")
            or meta_sub.get("argument-hint")
            or meta_sub.get("argument_hint")
        )
        version = metadata.get("version") or meta_sub.get("version")

        return SkillFrontmatter(
            name=metadata.get("name"),
            description=metadata.get("description"),
            version=str(version) if version else None,
            license=metadata.get("license"),
            context=metadata.get("context"),
            agent=metadata.get("agent"),
            model=metadata.get("model"),
            allowed_tools=allowed_tools if isinstance(allowed_tools, list) else None,
            user_invocable=user_invocable,
            disable_model_invocation=disable_model,
            argument_hint=argument_hint,
            hooks=metadata.get("hooks"),
            metadata=meta_sub if meta_sub else None,
        )

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
    def _parse_list_field(value) -> Optional[List[str]]:
        """Parse a field that can be a list or comma-separated string."""
        if value is None:
            return None
        if isinstance(value, str):
            return [t.strip() for t in value.split(",") if t.strip()]
        return value

    @staticmethod
    def _parse_hooks(hooks_raw: Optional[Dict]) -> Optional[Dict[str, List[AgentHook]]]:
        """Parse hooks from frontmatter into AgentHook objects."""
        if not hooks_raw:
            return None
        result = {}
        for event, hook_list in hooks_raw.items():
            if isinstance(hook_list, list):
                result[event] = [
                    AgentHook(
                        type=h.get("type", "command"),
                        command=h.get("command"),
                        prompt=h.get("prompt"),
                    )
                    for h in hook_list
                    if isinstance(h, dict)
                ]
            elif isinstance(hook_list, dict):
                result[event] = [
                    AgentHook(
                        type=hook_list.get("type", "command"),
                        command=hook_list.get("command"),
                        prompt=hook_list.get("prompt"),
                    )
                ]
        return result if result else None

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
                tools = AgentService._parse_list_field(metadata.get("tools"))
                disallowed_tools = AgentService._parse_list_field(
                    metadata.get("disallowed-tools") or metadata.get("disallowed_tools")
                )
                skills = AgentService._parse_list_field(metadata.get("skills"))
                hooks = AgentService._parse_hooks(metadata.get("hooks"))

                agents.append(
                    Agent(
                        name=agent_name,
                        scope=scope,
                        description=metadata.get("description"),
                        tools=tools,
                        model=metadata.get("model"),
                        prompt=markdown_content,
                        disallowed_tools=disallowed_tools,
                        permission_mode=metadata.get("permission-mode") or metadata.get("permission_mode"),
                        skills=skills,
                        hooks=hooks,
                        memory=metadata.get("memory"),
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
            tools = AgentService._parse_list_field(metadata.get("tools"))
            disallowed_tools = AgentService._parse_list_field(
                metadata.get("disallowed-tools") or metadata.get("disallowed_tools")
            )
            skills = AgentService._parse_list_field(metadata.get("skills"))
            hooks = AgentService._parse_hooks(metadata.get("hooks"))

            return Agent(
                name=name,
                scope=scope,
                description=metadata.get("description"),
                tools=tools,
                model=metadata.get("model"),
                prompt=markdown_content,
                disallowed_tools=disallowed_tools,
                permission_mode=metadata.get("permission-mode") or metadata.get("permission_mode"),
                skills=skills,
                hooks=hooks,
                memory=metadata.get("memory"),
            )
        except Exception as e:
            print(f"Error reading agent file {file_path}: {e}")
            return None

    @staticmethod
    def _hooks_to_dict(hooks: Optional[Dict[str, List[AgentHook]]]) -> Optional[Dict]:
        """Convert AgentHook objects back to dict for YAML serialization."""
        if not hooks:
            return None
        result = {}
        for event, hook_list in hooks.items():
            result[event] = [
                {k: v for k, v in {"type": h.type, "command": h.command, "prompt": h.prompt}.items() if v}
                for h in hook_list
            ]
        return result

    @staticmethod
    def _ensure_agent_memory_dir(agent_name: str, memory_scope: Optional[str]) -> None:
        """Create agent memory directory if memory scope is set."""
        if memory_scope and memory_scope != "none":
            memory_dir = get_agent_memory_dir(agent_name)
            ensure_directory_exists(memory_dir)

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
        # New subagent management fields
        if agent.disallowed_tools:
            metadata["disallowed-tools"] = agent.disallowed_tools
        if agent.permission_mode:
            metadata["permission-mode"] = agent.permission_mode
        if agent.skills:
            metadata["skills"] = agent.skills
        if agent.hooks:
            metadata["hooks"] = AgentService._hooks_to_dict(agent.hooks)
        if agent.memory:
            metadata["memory"] = agent.memory

        frontmatter = AgentService._build_frontmatter(metadata)
        full_content = frontmatter + agent.prompt

        # Write file
        file_path.write_text(full_content, encoding="utf-8")

        # Create memory directory if needed
        AgentService._ensure_agent_memory_dir(agent.name, agent.memory)

        return Agent(
            name=agent.name,
            scope=agent.scope,
            description=agent.description,
            tools=agent.tools,
            model=agent.model,
            prompt=agent.prompt,
            disallowed_tools=agent.disallowed_tools,
            permission_mode=agent.permission_mode,
            skills=agent.skills,
            hooks=agent.hooks,
            memory=agent.memory,
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

            # Update subagent management fields
            if agent.disallowed_tools is not None:
                if agent.disallowed_tools:
                    metadata["disallowed-tools"] = agent.disallowed_tools
                else:
                    metadata.pop("disallowed-tools", None)
                    metadata.pop("disallowed_tools", None)
            if agent.permission_mode is not None:
                if agent.permission_mode:
                    metadata["permission-mode"] = agent.permission_mode
                else:
                    metadata.pop("permission-mode", None)
                    metadata.pop("permission_mode", None)
            if agent.skills is not None:
                if agent.skills:
                    metadata["skills"] = agent.skills
                else:
                    metadata.pop("skills", None)
            if agent.hooks is not None:
                if agent.hooks:
                    metadata["hooks"] = AgentService._hooks_to_dict(agent.hooks)
                else:
                    metadata.pop("hooks", None)
            if agent.memory is not None:
                if agent.memory and agent.memory != "none":
                    metadata["memory"] = agent.memory
                    # Create memory directory if needed
                    AgentService._ensure_agent_memory_dir(name, agent.memory)
                else:
                    metadata.pop("memory", None)

            # Update content
            if agent.prompt is not None:
                markdown_content = agent.prompt

            # Build new content
            frontmatter = AgentService._build_frontmatter(metadata)
            full_content = frontmatter + markdown_content

            # Write file
            file_path.write_text(full_content, encoding="utf-8")

            # Parse back the result
            tools = AgentService._parse_list_field(metadata.get("tools"))
            disallowed_tools = AgentService._parse_list_field(
                metadata.get("disallowed-tools") or metadata.get("disallowed_tools")
            )
            skills = AgentService._parse_list_field(metadata.get("skills"))
            hooks = AgentService._parse_hooks(metadata.get("hooks"))

            return Agent(
                name=name,
                scope=scope,
                description=metadata.get("description"),
                tools=tools,
                model=metadata.get("model"),
                prompt=markdown_content,
                disallowed_tools=disallowed_tools,
                permission_mode=metadata.get("permission-mode") or metadata.get("permission_mode"),
                skills=skills,
                hooks=hooks,
                memory=metadata.get("memory"),
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
                # Get command names so we can exclude skills that are
                # primarily slash commands (e.g. vercel's deploy/logs/setup)
                commands_dir = plugin_path / "commands"
                command_names = set()
                if commands_dir.exists():
                    for cmd_file in commands_dir.glob("*.md"):
                        command_names.add(cmd_file.stem)

                plugin_skills = AgentService._scan_plugin_skills_dir(
                    skills_dir, f"plugin:{plugin['name']}"
                )
                # Filter out skills whose name matches a command
                if command_names:
                    plugin_skills = [
                        s for s in plugin_skills if s.name not in command_names
                    ]
                skills.extend(plugin_skills)

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

        def _make_skill(name: str, metadata: Dict) -> Skill:
            return Skill(
                name=name,
                description=metadata.get("description"),
                location=location,
                frontmatter=AgentService._metadata_to_frontmatter(metadata),
            )

        # Layout 1: Flat .md files with frontmatter
        for skill_file in base_dir.glob("*.md"):
            try:
                content = skill_file.read_text(encoding="utf-8")
                metadata, _ = AgentService._parse_frontmatter(content)

                skill_name = skill_file.stem
                seen_names.add(skill_name)
                skills.append(_make_skill(skill_name, metadata))
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
                                skills.append(_make_skill(sub.name, metadata))
                            except Exception as e:
                                print(f"Error reading skill {sub_skill}: {e}")
                continue
            if item.name in seen_names:
                continue
            try:
                content = skill_file.read_text(encoding="utf-8")
                metadata, _ = AgentService._parse_frontmatter(content)
                seen_names.add(item.name)
                skills.append(_make_skill(item.name, metadata))
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
                        frontmatter=AgentService._metadata_to_frontmatter(metadata),
                    )
                )
            except Exception as e:
                print(f"Error reading skill file {skill_file}: {e}")
                continue

        return skills

    @staticmethod
    def _find_skill_file(base_dir: Path, name: str) -> Optional[Path]:
        """
        Find a skill file by name, checking both layouts:
        1. Flat: base_dir/name.md
        2. Subdirectory: base_dir/name/SKILL.md
        3. Nested subdirectory: base_dir/*/name/SKILL.md
        """
        # Layout 1: flat .md file
        flat = base_dir / f"{name}.md"
        if flat.exists():
            return flat

        # Layout 2: subdirectory with SKILL.md
        subdir = base_dir / name / "SKILL.md"
        if subdir.exists():
            return subdir

        # Layout 3: nested (e.g. nextjs/vercel-ai-sdk/SKILL.md)
        for parent in base_dir.iterdir():
            if parent.is_dir():
                nested = parent / name / "SKILL.md"
                if nested.exists():
                    return nested

        return None

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
            skill_file = AgentService._find_skill_file(user_skills_dir, name)
        elif location == "project" and project_path:
            project_skills_dir = Path(project_path) / ".claude" / "skills"
            skill_file = AgentService._find_skill_file(project_skills_dir, name)
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
                frontmatter=AgentService._metadata_to_frontmatter(metadata),
            )
        except Exception as e:
            print(f"Error reading skill file {skill_file}: {e}")
            return None
