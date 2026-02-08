"""Service for MCP OAuth 2.1 authentication flows."""
import hashlib
import secrets
import base64
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

import httpx

from app.services.credentials_service import CredentialsService


@dataclass
class PendingAuth:
    """State for an in-progress OAuth flow."""
    server_name: str
    server_url: str
    code_verifier: str
    code_challenge: str
    token_endpoint: str
    client_id: str
    client_secret: Optional[str]
    redirect_uri: str
    created_at: float = field(default_factory=time.time)


class MCPOAuthService:
    """Handles MCP OAuth 2.1 with PKCE authentication flows."""

    CALLBACK_PATH = "/api/v1/mcp/auth/callback"
    PENDING_TTL = 300  # 5 minutes

    def __init__(self) -> None:
        self._pending: Dict[str, PendingAuth] = {}
        self._credentials = CredentialsService()

    def _cleanup_expired(self) -> None:
        """Remove pending auth entries older than TTL."""
        now = time.time()
        expired = [k for k, v in self._pending.items() if now - v.created_at > self.PENDING_TTL]
        for k in expired:
            del self._pending[k]

    @staticmethod
    def _generate_pkce() -> tuple[str, str]:
        """Generate PKCE code_verifier and code_challenge (S256)."""
        verifier = secrets.token_urlsafe(64)[:128]
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return verifier, challenge

    async def _discover_oauth_metadata(self, server_url: str) -> dict:
        """
        Probe the server, get 401 + WWW-Authenticate header,
        then discover OAuth metadata via RFC 9728 and RFC 8414.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Step 1: Probe server to get 401
            probe_resp = await client.get(server_url, follow_redirects=True)

            if probe_resp.status_code == 401:
                www_auth = probe_resp.headers.get("www-authenticate", "")
            else:
                # Server didn't return 401, try probing well-known directly
                www_auth = ""

            # Step 2: Try Protected Resource Metadata (RFC 9728)
            resource_metadata_url = None
            if "resource_metadata" in www_auth:
                # Extract resource_metadata URL from WWW-Authenticate header
                for part in www_auth.split(","):
                    part = part.strip()
                    if part.startswith("resource_metadata="):
                        resource_metadata_url = part.split("=", 1)[1].strip('"')
                        break

            # Step 3: Get authorization server URL
            auth_server_url = None

            if resource_metadata_url:
                try:
                    rm_resp = await client.get(resource_metadata_url)
                    if rm_resp.status_code == 200:
                        rm_data = rm_resp.json()
                        auth_servers = rm_data.get("authorization_servers", [])
                        if auth_servers:
                            auth_server_url = auth_servers[0]
                except Exception:
                    pass

            # Step 4: Fetch Authorization Server Metadata (RFC 8414)
            if not auth_server_url:
                # Derive from server URL base
                from urllib.parse import urlparse
                parsed = urlparse(server_url)
                auth_server_url = f"{parsed.scheme}://{parsed.netloc}"

            # Try well-known endpoint
            well_known_url = f"{auth_server_url.rstrip('/')}/.well-known/oauth-authorization-server"
            try:
                as_resp = await client.get(well_known_url)
                if as_resp.status_code == 200:
                    return as_resp.json()
            except Exception:
                pass

            # Fallback: try openid-configuration
            openid_url = f"{auth_server_url.rstrip('/')}/.well-known/openid-configuration"
            try:
                oid_resp = await client.get(openid_url)
                if oid_resp.status_code == 200:
                    return oid_resp.json()
            except Exception:
                pass

            raise ValueError(
                f"Could not discover OAuth metadata for {server_url}. "
                "Server may not support MCP OAuth authentication."
            )

    async def _register_client(
        self, registration_endpoint: str, redirect_uri: str, server_name: str
    ) -> dict:
        """Perform Dynamic Client Registration (RFC 7591)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            reg_data = {
                "client_name": f"Claude Deck - {server_name}",
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            }
            resp = await client.post(registration_endpoint, json=reg_data)
            if resp.status_code in (200, 201):
                return resp.json()
            raise ValueError(f"Client registration failed: {resp.status_code} {resp.text}")

    async def start_auth(self, server_url: str, server_name: str, callback_base_url: str) -> dict:
        """
        Start an OAuth flow for an MCP server.

        Returns {auth_url, state} for frontend to open in a popup.
        """
        self._cleanup_expired()

        # Discover OAuth metadata
        metadata = await self._discover_oauth_metadata(server_url)

        authorization_endpoint = metadata.get("authorization_endpoint")
        token_endpoint = metadata.get("token_endpoint")
        registration_endpoint = metadata.get("registration_endpoint")

        if not authorization_endpoint or not token_endpoint:
            raise ValueError("OAuth metadata missing authorization_endpoint or token_endpoint")

        redirect_uri = f"{callback_base_url}{self.CALLBACK_PATH}"

        # Always do fresh dynamic client registration with our redirect_uri.
        # CLI-stored client_ids are bound to a different redirect_uri and can't be reused.
        client_id = None
        client_secret = None
        if registration_endpoint:
            try:
                reg_result = await self._register_client(
                    registration_endpoint, redirect_uri, server_name
                )
                client_id = reg_result.get("client_id")
                client_secret = reg_result.get("client_secret")
            except Exception as e:
                raise ValueError(
                    f"OAuth client registration failed: {e}. "
                    "The server may not support dynamic client registration."
                )

        if not client_id:
            raise ValueError(
                "OAuth metadata does not include a registration_endpoint. "
                "This server may require manual client registration."
            )

        # Generate PKCE
        code_verifier, code_challenge = self._generate_pkce()

        # Generate state
        state = secrets.token_urlsafe(32)

        # Store pending auth
        self._pending[state] = PendingAuth(
            server_name=server_name,
            server_url=server_url,
            code_verifier=code_verifier,
            code_challenge=code_challenge,
            token_endpoint=token_endpoint,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )

        # Build authorization URL
        from urllib.parse import urlencode
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        # Add scopes if specified in metadata
        scopes = metadata.get("scopes_supported")
        if scopes:
            params["scope"] = " ".join(scopes)

        auth_url = f"{authorization_endpoint}?{urlencode(params)}"

        return {"auth_url": auth_url, "state": state}

    async def handle_callback(self, code: str, state: str) -> dict:
        """
        Handle OAuth callback: exchange code for token and store it.

        Returns {success, server_name}.
        """
        self._cleanup_expired()

        pending = self._pending.get(state)
        if not pending:
            raise ValueError("Invalid or expired OAuth state. Please try authenticating again.")

        # Exchange code for token
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": pending.redirect_uri,
                "client_id": pending.client_id,
                "code_verifier": pending.code_verifier,
            }
            if pending.client_secret:
                token_data["client_secret"] = pending.client_secret

            resp = await client.post(
                pending.token_endpoint,
                data=token_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if resp.status_code not in (200, 201):
                raise ValueError(f"Token exchange failed: {resp.status_code} {resp.text}")

            token_resp = resp.json()

        access_token = token_resp.get("access_token")
        if not access_token:
            raise ValueError("Token response missing access_token")

        refresh_token = token_resp.get("refresh_token")
        expires_in = token_resp.get("expires_in", 3600)
        expires_at = int(time.time() + expires_in)

        # Store token
        self._credentials.store_mcp_token(
            server_name=pending.server_name,
            server_url=pending.server_url,
            client_id=pending.client_id,
            client_secret=pending.client_secret,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        )

        # Clean up pending state
        del self._pending[state]

        return {"success": True, "server_name": pending.server_name}
