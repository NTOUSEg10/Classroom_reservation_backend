"""Supabase HTTP fixture used only by integration, load, and browser tests."""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import asyncpg
import httpx

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 12, 2, 0, tzinfo=timezone.utc)
ROOM_ID = UUID("11111111-1111-4111-8111-111111111111")
ALLOWED_DATABASES = {"ntou_integration", "ntou_load", "ntou_e2e"}


@dataclass
class MutableClock:
    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now


def test_database_url(database: str = "ntou_integration") -> str:
    """Only explicitly named loopback databases may be reset by this harness."""
    if database not in ALLOWED_DATABASES:
        raise RuntimeError("Unknown isolated test database")
    raw = os.getenv("TEST_DATABASE_URL")
    from_environment = bool(raw)
    if not raw:
        local = ROOT / ".local" / "database.env"
        if not local.exists():
            raise RuntimeError(
                "Set TEST_DATABASE_URL to a dedicated local ntou_integration database"
            )
        raw = (
            local.read_text(encoding="utf-8")
            .strip()
            .removeprefix("DATABASE_URL=")
        )
    parts = urlsplit(raw)
    if parts.hostname not in {"127.0.0.1", "localhost", "::1"} or (
        from_environment and parts.path[1:] not in ALLOWED_DATABASES
    ):
        raise RuntimeError(
            "Refusing to reset a non-loopback or non-test PostgreSQL database"
        )
    return urlunsplit(parts._replace(path=f"/{database}"))


async def reset_database(dsn: str) -> asyncpg.Connection:
    # A multi-connection race commits independently, so a single outer rollback cannot isolate it.
    parts = urlsplit(dsn)
    if (
        parts.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parts.path[1:] not in ALLOWED_DATABASES
    ):
        raise RuntimeError("Unsafe database reset target")
    connection = await asyncpg.connect(dsn)
    await connection.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    await connection.execute(
        (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
    )
    await connection.execute(
        (ROOT / "supabase" / "auth-hook.sql").read_text(encoding="utf-8")
    )
    await connection.execute(
        (ROOT / "supabase" / "seed.sql").read_text(encoding="utf-8")
    )
    return connection


def _b64(value: dict) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps(value).encode())
        .decode()
        .rstrip("=")
    )


@dataclass
class FakeSupabase:
    users: dict[str, dict] = field(default_factory=dict)
    tokens: dict[str, str] = field(default_factory=dict)
    requests: list[tuple[str, str]] = field(default_factory=list)
    verified_bearers: list[str] = field(default_factory=list)
    unavailable: bool = False

    def add_user(
        self, email: str, *, user_id: UUID | None = None, confirmed: bool = True
    ) -> dict:
        user = {
            "id": str(user_id or uuid4()),
            "email": email.lower(),
            "aud": "authenticated",
            "role": "authenticated",
            "email_confirmed_at": NOW.isoformat() if confirmed else None,
            "is_anonymous": False,
            "user_metadata": {},
            "app_metadata": {"provider": "google", "providers": ["google"]},
            "identities": [
                {
                    "provider": "google",
                    "user_id": str(user_id) if user_id else None,
                    "identity_data": {
                        "email": email.lower(),
                        "email_verified": True,
                    },
                }
            ],
            "created_at": NOW.isoformat(),
        }
        self.users[user["email"]] = user
        user["identities"][0]["user_id"] = user["id"]
        return user

    def session(self, user: dict, *, claims: dict | None = None) -> dict:
        token = ".".join(
            [
                _b64({"alg": "HS256", "typ": "JWT"}),
                _b64(
                    {
                        "sub": user["id"],
                        "aud": "authenticated",
                        "role": "authenticated",
                        "exp": int(time.time()) + 3600,
                        "amr": [
                            {"method": "oauth", "timestamp": int(time.time())}
                        ],
                        **(claims or {}),
                    }
                ),
                "test-transport-signature",
            ]
        )
        self.tokens[token] = user["email"]
        self.tokens[f"refresh-{user['id']}"] = user["email"]
        return {
            "access_token": token,
            "refresh_token": f"refresh-{user['id']}",
            "expires_in": 3600,
            "expires_at": int(time.time()) + 3600,
            "token_type": "bearer",
            "user": user,
        }

    def headers(self, user: dict) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.session(user)['access_token']}"}

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((request.method, path))
        if self.unavailable:
            return httpx.Response(
                503, json={"msg": "Fixture upstream unavailable"}
            )
        data = (
            json.loads(request.content or b"{}")
            if path.startswith("/auth/v1/")
            else {}
        )
        if path == "/auth/v1/token":
            if request.url.params.get("grant_type") == "refresh_token":
                email = self.tokens.get(data.get("refresh_token"))
            else:
                return httpx.Response(
                    400, json={"msg": "Fixture permits OAuth refresh only"}
                )
            if email not in self.users:
                return httpx.Response(
                    400, json={"msg": "Invalid login credentials"}
                )
            return httpx.Response(200, json=self.session(self.users[email]))
        if path == "/auth/v1/user":
            token = request.headers.get("authorization", "").removeprefix(
                "Bearer "
            )
            self.verified_bearers.append(token)
            email = self.tokens.get(token)
            if not email:
                return httpx.Response(401, json={"msg": "Invalid JWT"})
            return httpx.Response(200, json=self.users[email])
        if path.startswith("/storage/v1/"):
            if "/object/sign/" in path:
                return httpx.Response(
                    200,
                    json={
                        "signedURL": "/storage/v1/object/sign/room-maps/fixture.png?token=test"
                    },
                )
            return httpx.Response(200, json={"Key": "room-maps/fixture.png"})
        if path.startswith("/functions/v1/"):
            return httpx.Response(200, json={"ok": True, "accepted": 1})
        return httpx.Response(
            404, json={"msg": f"Unimplemented fixture path: {path}"}
        )


async def add_profile(
    connection,
    auth: FakeSupabase,
    *,
    index: int = 1,
    role: str = "borrower",
    verified: bool = True,
    confirmed: bool = True,
) -> dict:
    user = auth.add_user(
        f"fixture{index}@email.ntou.edu.tw", confirmed=confirmed
    )
    institutional_id = f"TEST{index:06}"
    await connection.execute(
        "INSERT INTO profiles(id,name,email,phone,department,institutional_id,role,verified) VALUES($1,$2,$3,$4,$5,$6,$7,$8)",
        UUID(user["id"]),
        f"測試使用者 {index}",
        user["email"],
        "0912345678",
        "資訊工程學系",
        institutional_id,
        role,
        verified,
    )
    return {**user, "institutional_id": institutional_id}


async def application_pool(dsn: str) -> asyncpg.Pool:
    from app.database import initialize_connection, reset_connection

    return await asyncpg.create_pool(
        dsn,
        min_size=2,
        max_size=20,
        init=initialize_connection,
        reset=reset_connection,
        command_timeout=5,
    )


def settings_for(dsn: str):
    from app.config import Settings

    return Settings(
        _env_file=None,
        database_url=dsn,
        supabase_url="https://fixture.supabase.co",
        supabase_publishable_key="test-publishable",
        supabase_service_key="test-service",
        environment="test",
        auth_rate_limit=10000,
        auth_ip_rate_limit=10000,
        enable_notification_worker=False,
    )


def booking_payload(
    *,
    room_id=ROOM_ID,
    start="2026-10-13T10:00:00+08:00",
    end="2026-10-13T12:00:00+08:00",
    **changes,
) -> dict:
    return {
        "room_id": str(room_id),
        "starts_at": start,
        "ends_at": end,
        "purpose": "專題討論測試",
        "attendees": 12,
        "mode": "scheduled",
        "request_id": str(uuid4()),
        **changes,
    }


async def seed_admin_pagination(connection, count: int):
    borrower = await connection.fetchval(
        "SELECT id FROM profiles WHERE institutional_id='TEST000001'"
    )
    admin = await connection.fetchval(
        "SELECT id FROM profiles WHERE institutional_id=$1",
        f"TEST{count + 1:06}",
    )
    await connection.executemany(
        """INSERT INTO violations(user_id,points,reason,resolved,created_by,created_at)
           VALUES($1,1,$2,$3,$4,$5)""",
        [
            (
                borrower,
                "Playwright 最舊未結案違規"
                if index == 0
                else f"Playwright 已結案違規 {index:03}",
                index != 0,
                admin,
                NOW - timedelta(days=365)
                if index == 0
                else NOW - timedelta(minutes=101 - index),
            )
            for index in range(101)
        ],
    )


def create_live_app(
    database: str = "ntou_load",
    count: int = 100,
    *,
    admin_pagination: bool = False,
):
    """A test-only Uvicorn factory; there is no fixture route or login in the real app."""
    from contextlib import asynccontextmanager
    from app.main import create_app

    dsn = test_database_url(database)
    auth = FakeSupabase()
    settings = settings_for(dsn)
    # Supply the real restricted-role pool during lifespan; no production login is changed.
    settings.database_url = ""
    app = create_app(
        settings,
        auth_transport=httpx.MockTransport(auth.handle),
        clock=lambda: NOW,
    )
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        connection = await reset_database(dsn)
        try:
            for index in range(1, count + 1):
                await add_profile(connection, auth, index=index)
            await add_profile(connection, auth, index=count + 1, role="admin")
            if admin_pagination:
                await add_profile(connection, auth, index=count + 2)
                await seed_admin_pagination(connection, count)
                auth.add_user(f"fixture{count + 3}@email.ntou.edu.tw")
            sessions = {
                email.split("@")[0].removeprefix("fixture"): auth.session(user)
                for email, user in auth.users.items()
            }
            directory = ROOT / ".local"
            directory.mkdir(exist_ok=True)
            (directory / f"{database}-sessions.json").write_text(
                json.dumps(
                    {
                        "test_only": True,
                        "auth": "MockTransport Google identities; no real credentials",
                        "sessions": sessions,
                    }
                ),
                encoding="utf-8",
            )
        finally:
            await connection.close()
        application.state.pool = await application_pool(dsn)
        async with original_lifespan(application):
            yield

    app.router.lifespan_context = lifespan
    return app


def load_app():
    return create_live_app("ntou_load", 100)


def e2e_app():
    return create_live_app("ntou_e2e", 100, admin_pagination=True)
