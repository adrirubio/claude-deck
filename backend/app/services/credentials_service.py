"""Service for managing Claude Code OAuth credentials."""
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from app.utils.path_utils import get_claude_user_config_dir


class CredentialsService:
    """Reads/writes ~/.claude/.credentials.json for MCP OAuth tokens."""

    def _get_credentials_path(self) -> Path:
        return get_claude_user_config_dir() / ".credentials.json"

    def _read_credentials(self) -> Dict[str, Any]:
        path = self._get_credentials_path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_credentials(self, data: Dict[str, Any]) -> None:
        path = self._get_credentials_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))
        # Secure file permissions (owner read/write only)
        os.chmod(path, 0o600)

    @staticmethod
    def _make_key(server_name: str, server_url: str) -> str:
        """Generate CLI-compatible credential key: {server_name}|{hash}."""
        url_hash = hashlib.sha256(server_url.encode()).hexdigest()[:16]
        return f"{server_name}|{url_hash}"

    def _find_entries_for_server(self, mcp_oauth: Dict[str, Any], server_name: str) -> list:
        """Find all credential entries matching server_name prefix."""
        return [
            (key, mcp_oauth[key])
            for key in mcp_oauth
            if key.startswith(f"{server_name}|")
        ]

    def _find_entry(self, server_name: str, server_url: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Find the best credential entry for a server.

        Prefers entries with a non-empty accessToken. Among those,
        prefers an exact URL-hash match if server_url is given.
        """
        creds = self._read_credentials()
        mcp_oauth = creds.get("mcpOAuth", {})

        # Try exact key first if URL provided
        if server_url:
            key = self._make_key(server_name, server_url)
            entry = mcp_oauth.get(key)
            if entry and entry.get("accessToken"):
                return entry

        # Gather all prefix-matched entries
        matches = self._find_entries_for_server(mcp_oauth, server_name)
        if not matches:
            return None

        # Prefer entries with a valid (non-empty) access token
        with_token = [(k, e) for k, e in matches if e.get("accessToken")]
        if with_token:
            return with_token[0][1]

        # Fall back to any entry (e.g., client registration only)
        return matches[0][1]

    def get_mcp_token(self, server_name: str, server_url: str) -> Optional[str]:
        """Find stored OAuth access_token for an MCP server."""
        entry = self._find_entry(server_name, server_url)
        if not entry:
            return None

        access_token = entry.get("accessToken")
        if not access_token:
            return None  # Empty or missing token

        # Check expiry
        expires_at = entry.get("expiresAt", 0)
        if expires_at and time.time() > expires_at:
            return None  # Token expired

        return access_token

    def get_client_registration(self, server_name: str) -> Optional[Dict[str, str]]:
        """Get stored client_id/client_secret from a previous registration."""
        entry = self._find_entry(server_name)
        if not entry:
            return None
        client_id = entry.get("clientId")
        if not client_id:
            return None
        return {
            "client_id": client_id,
            "client_secret": entry.get("clientSecret"),
            "server_url": entry.get("serverUrl"),
        }

    def store_mcp_token(
        self,
        server_name: str,
        server_url: str,
        client_id: str,
        client_secret: Optional[str],
        access_token: str,
        refresh_token: Optional[str],
        expires_at: int,
    ) -> None:
        """Store OAuth token in CLI-compatible format."""
        creds = self._read_credentials()
        if "mcpOAuth" not in creds:
            creds["mcpOAuth"] = {}

        key = self._make_key(server_name, server_url)
        creds["mcpOAuth"][key] = {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": expires_at,
            "clientId": client_id,
            "clientSecret": client_secret,
            "serverUrl": server_url,
        }

        self._write_credentials(creds)

    def get_auth_status(self, server_name: str) -> Dict[str, Any]:
        """Return auth status for UI display."""
        entry = self._find_entry(server_name)
        if not entry:
            return {"has_token": False, "expired": False, "server_url": None}

        access_token = entry.get("accessToken")
        if not access_token:
            # Entry exists (client registered) but no actual token yet
            has_client = bool(entry.get("clientId"))
            return {
                "has_token": False,
                "expired": False,
                "server_url": entry.get("serverUrl"),
                "has_client_registration": has_client,
            }

        expires_at = entry.get("expiresAt", 0)
        expired = bool(expires_at and time.time() > expires_at)

        return {
            "has_token": True,
            "expired": expired,
            "server_url": entry.get("serverUrl"),
        }

    def delete_mcp_token(self, server_name: str) -> bool:
        """Remove stored token for a server."""
        creds = self._read_credentials()
        mcp_oauth = creds.get("mcpOAuth", {})

        found_key = self._find_key_for_server(mcp_oauth, server_name)
        if not found_key:
            return False

        del mcp_oauth[found_key]
        creds["mcpOAuth"] = mcp_oauth
        self._write_credentials(creds)
        return True
