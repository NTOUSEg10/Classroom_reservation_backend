import json

import httpx
import pytest

from scripts import verify_supabase


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (None, None),
        ("unfinished", "fully onboarded"),
        ("wrong_domain", "fully onboarded"),
        ("admin", "dedicated borrower"),
        ("admin_allowed", "403 on admin"),
        ("password_enabled", "password login"),
        ("different_uuid", "same Google"),
        ("non_google", "same Google"),
    ],
)
async def test_deployment_smoke_checks_google_identity_and_access(
    monkeypatch, tmp_path, capsys, change, expected
):
    monkeypatch.setenv("TEST_API_URL", "https://api.example.test")
    monkeypatch.setenv("TEST_BORROWER_ACCESS_TOKEN", "private-fixture-token")
    monkeypatch.setattr(
        verify_supabase,
        "__file__",
        str(tmp_path / "scripts" / "verify_supabase.py"),
    )

    def respond(request):
        assert (
            request.headers["authorization"] == "Bearer private-fixture-token"
        )
        path = request.url.path
        if path == "/api/auth/identity":
            return httpx.Response(
                200,
                json={
                    "email": "borrower@other.test"
                    if change == "wrong_domain"
                    else "borrower@email.ntou.edu.tw",
                    "onboarding_required": change == "unfinished",
                },
            )
        if path == "/api/me":
            return httpx.Response(
                200,
                json={
                    "id": "same-id",
                    "role": "admin" if change == "admin" else "borrower",
                },
            )
        if path == "/api/admin/users":
            return httpx.Response(200 if change == "admin_allowed" else 403)
        if path == "/api/auth/login":
            assert json.loads(request.content) == {}
            return httpx.Response(200 if change == "password_enabled" else 403)
        if path == "/api/config":
            return httpx.Response(
                200,
                json={
                    "supabase_url": "https://auth.example.test",
                    "supabase_publishable_key": "public-key",
                },
            )
        if path == "/auth/v1/user":
            assert request.headers["apikey"] == "public-key"
            return httpx.Response(
                200,
                json={
                    "id": "other-id"
                    if change == "different_uuid"
                    else "same-id",
                    "app_metadata": {
                        "provider": "email"
                        if change == "non_google"
                        else "google"
                    },
                },
            )
        assert path in {"/api/rooms/availability", "/api/me/eligibility"}
        return httpx.Response(200, json={})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        verify_supabase.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(respond), **kwargs
        ),
    )
    if expected:
        with pytest.raises(RuntimeError, match=expected):
            await verify_supabase.main()
        assert not (tmp_path / "reports" / "supabase-deployment.json").exists()
    else:
        await verify_supabase.main()
        report = (tmp_path / "reports" / "supabase-deployment.json").read_text()
        assert json.loads(report)["google_oauth_identity"] is True
        assert "private-fixture-token" not in report
    assert "private-fixture-token" not in capsys.readouterr().out


async def test_deployment_smoke_rejects_plain_http(monkeypatch):
    monkeypatch.setenv("TEST_API_URL", "http://api.example.test")
    monkeypatch.setenv("TEST_BORROWER_ACCESS_TOKEN", "private-fixture-token")
    with pytest.raises(SystemExit, match="HTTPS"):
        await verify_supabase.main()
