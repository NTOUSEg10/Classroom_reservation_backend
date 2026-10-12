import base64
import json
from copy import deepcopy
from uuid import UUID

import httpx
import pytest

from app.config import Settings
from app.main import create_app


USER_ID = "11111111-1111-4111-8111-111111111111"
EMAIL = "fixture@email.ntou.edu.tw"


def google_user():
    return {
        "id": USER_ID,
        "email": EMAIL,
        "email_confirmed_at": "2026-10-12T00:00:00Z",
        "is_anonymous": False,
        "app_metadata": {"provider": "google", "providers": ["google"]},
        "identities": [
            {
                "provider": "google",
                "identity_data": {"email": EMAIL, "email_verified": True},
            }
        ],
        "user_metadata": {
            "role": "admin",
            "email": "user-controlled@example.com",
        },
    }


def oauth_token(claims=None):
    payload = (
        claims
        if claims is not None
        else {"sub": USER_ID, "amr": [{"method": "oauth", "timestamp": 1}]}
    )
    encoded = (
        base64.urlsafe_b64encode(json.dumps(payload).encode())
        .decode()
        .rstrip("=")
    )
    return "fixture-header." + encoded + ".fixture-signature"


class ProfilePool:
    def __init__(self, profile=None):
        self.profile = profile

    def acquire(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def fetchrow(self, query, user_id):
        assert query == "SELECT * FROM profiles WHERE id=$1"
        assert user_id == UUID(USER_ID)
        return self.profile


async def identity_response(
    auth_user, *, token=None, pool=None, path="/api/auth/identity"
):
    token = token or oauth_token()

    def handle(request):
        assert request.url.path == "/auth/v1/user"
        assert request.headers["authorization"] == "Bearer " + token
        return httpx.Response(200, json=auth_user)

    settings = Settings(
        environment="test",
        supabase_url="https://fixture.supabase.co",
        supabase_publishable_key="test-public",
        _env_file=None,
    )
    app = create_app(
        settings,
        pool=pool if pool is not None else object(),
        auth_transport=httpx.MockTransport(handle),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(
                path, headers={"Authorization": "Bearer " + token}
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "upstream,expected", [(401, 401), (503, 503), (429, 503)]
)
async def test_bearer_validation_maps_upstream_failures_without_profile_data(
    upstream, expected
):
    def handle(request):
        assert request.url.path == "/auth/v1/user"
        assert request.headers["authorization"] == "Bearer submitted-token"
        return httpx.Response(
            upstream,
            json={
                "message": "fixture upstream body must not leak",
                "phone": "0912345678",
            },
        )

    settings = Settings(
        environment="test",
        supabase_url="https://fixture.supabase.co",
        supabase_publishable_key="test-public",
        _env_file=None,
    )
    app = create_app(
        settings, pool=object(), auth_transport=httpx.MockTransport(handle)
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/me", headers={"Authorization": "Bearer submitted-token"}
            )
    assert response.status_code == expected
    assert (
        "fixture upstream body" not in response.text
        and "0912345678" not in response.text
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["not-a-uuid", 123, False, None, []])
async def test_invalid_auth_user_payload_cannot_become_an_identity(identifier):
    settings = Settings(
        environment="test",
        supabase_url="https://fixture.supabase.co",
        supabase_publishable_key="test-public",
        _env_file=None,
    )
    app = create_app(
        settings,
        pool=object(),
        auth_transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"id": identifier, "user_metadata": {"role": "admin"}}
            )
        ),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/me", headers={"Authorization": "Bearer submitted-token"}
            )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upstream_network_failure_returns_retryable_503():
    def handle(request):
        raise httpx.ConnectTimeout("fixture timeout", request=request)

    settings = Settings(
        environment="test",
        supabase_url="https://fixture.supabase.co",
        supabase_publishable_key="test-public",
        _env_file=None,
    )
    app = create_app(
        settings, pool=object(), auth_transport=httpx.MockTransport(handle)
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/me", headers={"Authorization": "Bearer submitted-token"}
            )
    assert response.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "email",
    [
        "fixture@mail.ntou.edu.tw",
        "fixture@gmail.com",
        "fixture@ntou.edu.tw",
        "fixture@email.ntou.edu.tw.evil.example",
        "fixture@sub.email.ntou.edu.tw",
        "fixture@evilemail.ntou.edu.tw",
        "@email.ntou.edu.tw",
        "two@@email.ntou.edu.tw",
        " fixture@email.ntou.edu.tw",
    ],
)
async def test_school_domain_is_exact_and_comes_from_auth_server(email):
    user = google_user()
    user["email"] = email
    user["identities"][0]["identity_data"]["email"] = email
    user["user_metadata"].update(
        email=EMAIL, email_verified=True, provider="google"
    )
    response = await identity_response(user)
    assert response.status_code == 403
    assert email not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {
            "app_metadata": {
                "provider": "email",
                "providers": ["email", "google"],
            }
        },
        {"app_metadata": {"provider": "github"}},
        {"app_metadata": None},
        {
            "app_metadata": {
                "provider": "google",
                "providers": ["google", "github"],
            }
        },
        {
            "app_metadata": {
                "provider": "google",
                "providers": ["google", "email"],
            }
        },
        {"app_metadata": {"provider": "google", "providers": []}},
        {"app_metadata": {"provider": "google", "providers": None}},
        {"app_metadata": {"provider": "google", "providers": "google"}},
        {"app_metadata": {"provider": "google", "providers": ["google", None]}},
        {"app_metadata": {"provider": "google", "providers": ["google", True]}},
        {"email_confirmed_at": None},
        {"is_anonymous": True},
        {"is_anonymous": None},
        {"identities": []},
        {"identities": None},
        {
            "identities": [
                {
                    "provider": "email",
                    "identity_data": {"email": EMAIL, "email_verified": True},
                }
            ]
        },
        {
            "identities": [
                {
                    "provider": "google",
                    "identity_data": {"email": EMAIL, "email_verified": "true"},
                }
            ]
        },
        {
            "identities": [
                {
                    "provider": "google",
                    "identity_data": {"email": EMAIL, "email_verified": False},
                }
            ]
        },
        {
            "identities": [
                {
                    "provider": "google",
                    "identity_data": {
                        "email": "other@email.ntou.edu.tw",
                        "email_verified": True,
                    },
                }
            ]
        },
        {"identities": [{"provider": "google", "identity_data": None}]},
        {
            "identities": [
                {
                    "provider": "google",
                    "identity_data": {"email": EMAIL, "email_verified": True},
                },
                {
                    "provider": "github",
                    "identity_data": {"email": EMAIL, "email_verified": True},
                },
            ]
        },
        {
            "identities": [
                {
                    "provider": "google",
                    "identity_data": {"email": EMAIL, "email_verified": True},
                },
                {
                    "provider": "email",
                    "identity_data": {"email": EMAIL, "email_verified": True},
                },
            ]
        },
    ],
)
async def test_mutable_metadata_cannot_replace_trusted_google_verification(
    change,
):
    user = google_user() | deepcopy(change)
    user["user_metadata"].update(
        provider="google", email=EMAIL, email_verified=True, role="admin"
    )
    response = await identity_response(user)
    assert response.status_code == 403
    assert "user-controlled" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claims",
    [
        {"sub": USER_ID, "amr": [{"method": "password"}]},
        {"sub": USER_ID, "amr": [{"method": "token_refresh"}]},
        {"sub": USER_ID, "amr": {"method": "oauth"}},
        {"sub": USER_ID},
        {
            "sub": "22222222-2222-4222-8222-222222222222",
            "amr": [{"method": "oauth"}],
        },
        {"sub": False, "amr": [{"method": "oauth"}]},
        {"sub": USER_ID, "amr": ["oauth", None]},
        [],
    ],
)
async def test_google_linked_identity_still_requires_matching_oauth_session(
    claims,
):
    response = await identity_response(google_user(), token=oauth_token(claims))
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token",
    [
        "opaque-token",
        "header.***.signature",
        "header.W10.signature",
        "header.e30.signature",
    ],
)
async def test_malformed_claims_fail_closed_after_upstream_bearer_validation(
    token,
):
    response = await identity_response(google_user(), token=token)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_valid_google_oauth_identity_without_profile_is_normal_onboarding():
    user = google_user()
    user["email"] = EMAIL.upper()
    user["identities"][0]["identity_data"]["email"] = EMAIL.upper()
    response = await identity_response(user, pool=ProfilePool())
    assert response.status_code == 200
    assert response.json() == {
        "email": EMAIL,
        "onboarding_required": True,
        "profile": None,
    }
    assert "user_metadata" not in response.text
    protected = await identity_response(
        user, pool=ProfilePool(), path="/api/me"
    )
    assert protected.status_code == 403
    assert protected.json() == {"detail": "請先完成基本資料"}


@pytest.mark.asyncio
async def test_oauth_refresh_keeps_access_and_role_is_read_from_database():
    profile = {
        "id": USER_ID,
        "email": EMAIL,
        "role": "borrower",
        "verified": True,
        "suspended": True,
    }
    token = oauth_token(
        {
            "sub": USER_ID,
            "amr": [
                {"method": "token_refresh"},
                {"method": "oauth"},
                {"method": "totp"},
            ],
        }
    )
    response = await identity_response(
        google_user(), token=token, pool=ProfilePool(profile)
    )
    assert response.status_code == 200
    assert response.json() == {
        "email": EMAIL,
        "onboarding_required": False,
        "profile": profile,
    }
    denied = await identity_response(
        google_user(),
        token=token,
        pool=ProfilePool(profile),
        path="/api/admin/users",
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_identity_does_not_return_profile_for_mismatched_email():
    profile = {
        "id": USER_ID,
        "email": "previous@mail.ntou.edu.tw",
        "name": "private existing record",
    }
    response = await identity_response(google_user(), pool=ProfilePool(profile))
    assert response.status_code == 403
    assert "private existing record" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"email": EMAIL, "password": "must-not-echo"},
        {"password": ["invalid-type"]},
    ],
)
async def test_legacy_password_login_is_disabled_without_calling_auth(payload):
    def handle(request):
        raise AssertionError("Password endpoint must not call Supabase")

    app = create_app(
        Settings(environment="test", _env_file=None),
        auth_transport=httpx.MockTransport(handle),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/auth/login", json=payload)
    assert response.status_code == 403
    assert response.json() == {"detail": "請使用學校 Google 帳號登入"}
    assert "must-not-echo" not in response.text


@pytest.mark.asyncio
async def test_eligibility_uses_one_profile_snapshot_and_revalidates_each_request():
    class EligibilityPool(ProfilePool):
        def __init__(self):
            super().__init__(
                {
                    "id": USER_ID,
                    "email": EMAIL,
                    "role": "borrower",
                    "verified": True,
                    "suspended": False,
                    "violation_points": 0,
                }
            )
            self.acquires = 0
            self.queries = 0

        def acquire(self):
            self.acquires += 1
            return self

        async def fetchrow(self, query, user_id):
            assert user_id == UUID(USER_ID)
            assert "FROM profiles p WHERE p.id=$1" in query
            assert "v.user_id=p.id AND NOT v.resolved" in query
            self.queries += 1
            return dict(self.profile)

    pool = EligibilityPool()
    verified = []
    token = oauth_token()

    def handle(request):
        verified.append(request.headers["authorization"])
        return httpx.Response(200, json=google_user())

    app = create_app(
        Settings(
            environment="test",
            supabase_url="https://fixture.supabase.co",
            supabase_publishable_key="test-public",
            _env_file=None,
        ),
        pool=pool,
        auth_transport=httpx.MockTransport(handle),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {"Authorization": "Bearer " + token}
            first = await client.get("/api/me/eligibility", headers=headers)
            assert first.status_code == 200
            assert first.json()["eligible"] is True
            pool.profile.update(suspended=True, violation_points=3)
            second = await client.get("/api/me/eligibility", headers=headers)
            assert second.status_code == 200
            assert second.json()["eligible"] is False
            assert second.json()["suspended"] is True
            assert second.json()["violation_points"] == 3
    assert pool.acquires == pool.queries == 2
    assert verified == ["Bearer " + token] * 2


@pytest.mark.asyncio
async def test_eligibility_does_not_query_database_when_live_auth_is_revoked():
    class NoAccessPool:
        def acquire(self):
            raise AssertionError("Revoked authentication cannot reach profiles")

    app = create_app(
        Settings(
            environment="test",
            supabase_url="https://fixture.supabase.co",
            supabase_publishable_key="test-public",
            _env_file=None,
        ),
        pool=NoAccessPool(),
        auth_transport=httpx.MockTransport(
            lambda _: httpx.Response(401, json={"msg": "revoked"})
        ),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/me/eligibility",
                headers={"Authorization": "Bearer " + oauth_token()},
            )
    assert response.status_code == 401
