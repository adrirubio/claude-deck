"""Service for managing output styles."""
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from app.models.schemas import OutputStyle, OutputStyleCreate, OutputStyleUpdate
from app.utils.path_utils import (
    ensure_directory_exists,
    get_claude_user_output_styles_dir,
    get_project_output_styles_dir,
)


class OutputStyleService:
    """Service for managing output styles."""

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
    def list_output_styles(project_path: Optional[str] = None) -> List[OutputStyle]:
        """
        List all output styles from user and project scopes.

        Args:
            project_path: Optional project path for project-scoped styles

        Returns:
            List of OutputStyle objects
        """
        styles = []

        # User output styles
        user_styles_dir = get_claude_user_output_styles_dir()
        if user_styles_dir.exists():
            styles.extend(OutputStyleService._scan_styles_dir(user_styles_dir, "user"))

        # Project output styles
        if project_path:
            project_styles_dir = get_project_output_styles_dir(project_path)
            if project_styles_dir.exists():
                styles.extend(
                    OutputStyleService._scan_styles_dir(project_styles_dir, "project")
                )

        return styles

    @staticmethod
    def _scan_styles_dir(base_dir: Path, scope: str) -> List[OutputStyle]:
        """
        Scan an output styles directory for .md files.

        Args:
            base_dir: Base output styles directory
            scope: "user" or "project"

        Returns:
            List of OutputStyle objects
        """
        styles = []

        # Find all .md files (non-recursive)
        for md_file in base_dir.glob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                metadata, markdown_content = OutputStyleService._parse_frontmatter(content)

                style_name = md_file.stem  # filename without .md

                styles.append(
                    OutputStyle(
                        name=metadata.get("name", style_name),
                        scope=scope,
                        description=metadata.get("description"),
                        keep_coding_instructions=metadata.get("keep-coding-instructions", False),
                        content=markdown_content,
                    )
                )
            except Exception as e:
                print(f"Error reading output style file {md_file}: {e}")
                continue

        return styles

    @staticmethod
    def get_output_style(
        scope: str, name: str, project_path: Optional[str] = None
    ) -> Optional[OutputStyle]:
        """
        Get a specific output style by scope and name.

        Args:
            scope: "user" or "project"
            name: Style name (without .md extension)
            project_path: Optional project path for project-scoped styles

        Returns:
            OutputStyle object or None if not found
        """
        if scope == "user":
            base_dir = get_claude_user_output_styles_dir()
        else:
            base_dir = get_project_output_styles_dir(project_path)

        file_path = base_dir / f"{name}.md"
        if not file_path.exists():
            return None

        try:
            content = file_path.read_text(encoding="utf-8")
            metadata, markdown_content = OutputStyleService._parse_frontmatter(content)

            return OutputStyle(
                name=metadata.get("name", name),
                scope=scope,
                description=metadata.get("description"),
                keep_coding_instructions=metadata.get("keep-coding-instructions", False),
                content=markdown_content,
            )
        except Exception as e:
            print(f"Error reading output style file {file_path}: {e}")
            return None

    @staticmethod
    def create_output_style(
        style: OutputStyleCreate, project_path: Optional[str] = None
    ) -> OutputStyle:
        """
        Create a new output style file.

        Args:
            style: OutputStyleCreate object with style data
            project_path: Optional project path for project-scoped styles

        Returns:
            Created OutputStyle object

        Raises:
            ValueError: If style already exists or invalid scope
        """
        if style.scope == "user":
            base_dir = get_claude_user_output_styles_dir()
        elif style.scope == "project":
            base_dir = get_project_output_styles_dir(project_path)
        else:
            raise ValueError(f"Invalid scope: {style.scope}")

        file_path = base_dir / f"{style.name}.md"

        # Check if file already exists
        if file_path.exists():
            raise ValueError(f"Output style already exists: {style.name}")

        # Ensure directory exists
        ensure_directory_exists(base_dir)

        # Build frontmatter
        metadata = {}
        if style.description:
            metadata["description"] = style.description
        if style.keep_coding_instructions:
            metadata["keep-coding-instructions"] = style.keep_coding_instructions

        frontmatter = OutputStyleService._build_frontmatter(metadata)
        full_content = frontmatter + style.content

        # Write file
        file_path.write_text(full_content, encoding="utf-8")

        return OutputStyle(
            name=style.name,
            scope=style.scope,
            description=style.description,
            keep_coding_instructions=style.keep_coding_instructions,
            content=style.content,
        )

    @staticmethod
    def update_output_style(
        scope: str,
        name: str,
        style: OutputStyleUpdate,
        project_path: Optional[str] = None,
    ) -> Optional[OutputStyle]:
        """
        Update an existing output style file.

        Args:
            scope: "user" or "project"
            name: Style name (without .md extension)
            style: OutputStyleUpdate object with updated data
            project_path: Optional project path for project-scoped styles

        Returns:
            Updated OutputStyle object or None if not found
        """
        if scope == "user":
            base_dir = get_claude_user_output_styles_dir()
        else:
            base_dir = get_project_output_styles_dir(project_path)

        file_path = base_dir / f"{name}.md"
        if not file_path.exists():
            return None

        try:
            # Read existing content
            existing_content = file_path.read_text(encoding="utf-8")
            metadata, markdown_content = OutputStyleService._parse_frontmatter(
                existing_content
            )

            # Update metadata
            if style.description is not None:
                metadata["description"] = style.description
            if style.keep_coding_instructions is not None:
                metadata["keep-coding-instructions"] = style.keep_coding_instructions

            # Update content
            if style.content is not None:
                markdown_content = style.content

            # Build new content
            frontmatter = OutputStyleService._build_frontmatter(metadata)
            full_content = frontmatter + markdown_content

            # Write file
            file_path.write_text(full_content, encoding="utf-8")

            return OutputStyle(
                name=metadata.get("name", name),
                scope=scope,
                description=metadata.get("description"),
                keep_coding_instructions=metadata.get("keep-coding-instructions", False),
                content=markdown_content,
            )
        except Exception as e:
            print(f"Error updating output style file {file_path}: {e}")
            return None

    @staticmethod
    def delete_output_style(
        scope: str, name: str, project_path: Optional[str] = None
    ) -> bool:
        """
        Delete an output style file.

        Args:
            scope: "user" or "project"
            name: Style name (without .md extension)
            project_path: Optional project path for project-scoped styles

        Returns:
            True if deleted, False if not found
        """
        if scope == "user":
            base_dir = get_claude_user_output_styles_dir()
        else:
            base_dir = get_project_output_styles_dir(project_path)

        file_path = base_dir / f"{name}.md"
        if not file_path.exists():
            return False

        try:
            file_path.unlink()
            return True
        except Exception as e:
            print(f"Error deleting output style file {file_path}: {e}")
            return False
