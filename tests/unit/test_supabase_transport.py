from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app.auth import supabase_request
from app.config import Settings


@pytest.mark.parametrize(
    ("key", "service", "token", "authorization"),
    [
        ("sb_secret_private-fixture", True, None, None),
        ("sb_publishable_public-fixture", False, None, None),
        ("legacy-service-jwt", True, None, "Bearer legacy-service-jwt"),
        ("legacy-anon-jwt", False, None, "Bearer legacy-anon-jwt"),
        (
            "sb_publishable_public-fixture",
            False,
            "user-session-jwt",
            "Bearer user-session-jwt",
        ),
    ],
)
async def test_supabase_headers_preserve_user_jwt_and_never_bearer_opaque_keys(
    key, service, token, authorization
):
    settings = Settings(
        environment="test",
        supabase_url="https://fixture.supabase.co",
        supabase_publishable_key=key if not service else "public-fixture",
        supabase_service_key=key if service else "private-fixture",
        _env_file=None,
    )

    def respond(request):
        assert request.headers["apikey"] == key
        assert request.headers.get("authorization") == authorization
        assert request.headers["content-type"] == "image/webp"
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond)
    ) as client:
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(settings=settings, http_client=client)
            )
        )
        response = await supabase_request(
            request,
            "POST",
            "/storage/v1/object/room-maps/fixture.webp",
            service=service,
            token=token,
            content=b"fixture",
            headers={"Content-Type": "image/webp"},
        )
        assert response.status_code == 200


def test_secret_key_alias_preferred_to_legacy_service_role(monkeypatch):
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_new-private-fixture")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "old-private-fixture")
    settings = Settings(environment="test", _env_file=None)
    assert settings.supabase_service_key == "sb_secret_new-private-fixture"
    assert "new-private-fixture" not in repr(settings)


def test_public_config_rejects_private_secret_keys_without_echoing(monkeypatch):
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_secret_private-fixture")
    with pytest.raises(ValidationError, match="public key") as error:
        Settings(environment="test", _env_file=None)
    assert "private-fixture" not in str(error.value)
