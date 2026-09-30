"""Cross-origin access to the local Deck API is explicit, not wildcard."""

import httpx
import pytest

from app.main import app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin, allowed",
    [
        ("http://localhost:5173", True),
        ("http://127.0.0.1:5173", True),
        ("http://untrusted.example:5173", False),
        ("http://localhost:9999", False),
    ],
)
async def test_autonomy_mutation_preflight_accepts_only_configured_origins(origin, allowed):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.options(
            "/api/v1/agent-teams/presets/1",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == (200 if allowed else 400)
    assert response.headers.get("access-control-allow-origin") == (
        origin if allowed else None
    )
