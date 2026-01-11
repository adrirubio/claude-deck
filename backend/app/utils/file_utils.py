"""File utilities for reading and writing JSON files."""
import json
from pathlib import Path
from typing import Any, Optional


def read_json_file(file_path: Path) -> Optional[dict[str, Any]]:
    """
    Read a JSON file and return its contents.

    Args:
        file_path: Path to the JSON file

    Returns:
        Dictionary containing the JSON data, or None if file doesn't exist
    """
    if not file_path.exists():
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return None
    except Exception:
        return None


async def write_json_file(file_path: Path, data: dict[str, Any]) -> bool:
    """
    Write data to a JSON file.

    Args:
        file_path: Path to the JSON file
        data: Dictionary to write as JSON

    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


async def read_text_file(file_path: Path) -> Optional[str]:
    """
    Read a text file and return its contents.

    Args:
        file_path: Path to the text file

    Returns:
        String containing the file contents, or None if file doesn't exist
    """
    if not file_path.exists():
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


async def write_text_file(file_path: Path, content: str) -> bool:
    """
    Write text content to a file.

    Args:
        file_path: Path to the text file
        content: String content to write

    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception:
        return False


def file_exists(file_path: Path) -> bool:
    """
    Check if a file exists.

    Args:
        file_path: Path to check

    Returns:
        True if file exists, False otherwise
    """
    return file_path.exists() and file_path.is_file()


def directory_exists(dir_path: Path) -> bool:
    """
    Check if a directory exists.

    Args:
        dir_path: Path to check

    Returns:
        True if directory exists, False otherwise
    """
    return dir_path.exists() and dir_path.is_dir()
