import base64

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.models import PushKeys, validate_push_endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/send/token",
        "https://127.0.0.1/x",
        "https://fcm.googleapis.com.evil.example/x",
        "https://fcm.googleapis.com@127.0.0.1/x",
        "https://fcm.googleapis.com:8443/x",
        "https://metadata.google.internal/x",
        "https://example.com/push",
        "https://evilpush.apple.com/x",
    ],
)
def test_push_endpoint_prevents_ssrf(endpoint):
    with pytest.raises(ValueError):
        validate_push_endpoint(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://fcm.googleapis.com/fcm/send/abc",
        "https://updates.push.services.mozilla.com/wpush/v2/abc",
        "https://web.push.apple.com/Qabc",
        "https://wns2-db5p.notify.windows.com/w/?token=a",
    ],
)
def test_push_provider_allowlist(endpoint):
    assert validate_push_endpoint(endpoint) == endpoint


def test_push_keys_require_curve_point_and_secret_length():
    public = base64.urlsafe_b64encode(b"\x04" + b"x" * 64).decode().rstrip("=")
    secret = base64.urlsafe_b64encode(b"x" * 16).decode().rstrip("=")
    PushKeys(p256dh=public, auth=secret)
    with pytest.raises(ValidationError):
        PushKeys(p256dh=public, auth="abc")


def production_settings(**changes):
    values = {
        "environment": "production",
        "database_url": "postgresql://ntou_api:dummy@db.example/ntou?sslmode=verify-full",
        "supabase_url": "https://example.supabase.co",
        "supabase_publishable_key": "public",
        "supabase_service_key": "secret",
        "frontend_origin": "https://rooms.example.edu.tw",
        "dispatch_secret": "secret",
        "vapid_public_key": "public",
        "demo_data": False,
        "_env_file": None,
    }
    values.update(changes)
    return Settings(**values)


@pytest.mark.parametrize(
    "changes",
    [
        {"frontend_origin": "http://rooms.example.edu.tw"},
        {"database_url": "postgresql://postgres:dummy@db.example/ntou"},
        {
            "database_url": "postgresql://ntou_api:dummy@db.example/ntou?sslmode=disable"
        },
        {"demo_data": True},
        {"supabase_service_key": ""},
    ],
)
def test_production_rejects_insecure_config(changes):
    with pytest.raises(ValidationError):
        production_settings(**changes)


def test_configuration_errors_and_repr_do_not_echo_private_secrets():
    settings = production_settings(
        supabase_service_key="private-service-secret",
        dispatch_secret="private-dispatch-secret",
    )
    assert "private-service-secret" not in repr(settings)
    assert "private-dispatch-secret" not in repr(settings)
    with pytest.raises(ValidationError) as error:
        production_settings(
            supabase_service_key="private-service-secret", demo_data=True
        )
    assert "private-service-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_production_https_and_local_health_exception():
    class Connection:
        async def fetchval(self, query):
            return 1

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *args):
            return False

    class Pool:
        def acquire(self):
            return Acquire()

    app = create_app(production_settings(), pool=Pool())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("198.51.100.1", 4000)),
        base_url="http://test",
    ) as client:
        assert (await client.get("/api/config")).status_code == 400
        assert (await client.get("/api/health")).status_code == 400
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 4000)),
        base_url="http://test",
    ) as client:
        assert (await client.get("/api/health")).status_code == 200
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        response = await client.get("/api/config")
        assert response.status_code == 200
        assert response.headers["strict-transport-security"].startswith(
            "max-age="
        )
        assert "secret" not in response.text


@pytest.mark.asyncio
async def test_disabled_password_login_does_not_parse_or_echo_password():
    app = create_app(Settings(environment="test", _env_file=None))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        secret = "DO-NOT-ECHO-" * 20
        response = await client.post(
            "/api/auth/login", json={"email": "bad", "password": secret}
        )
    assert response.status_code == 403
    assert secret not in response.text
