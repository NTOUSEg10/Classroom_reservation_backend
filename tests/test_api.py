"""Real PostgreSQL integration tests across authentication, ownership, and booking lifecycle."""

import asyncio
import base64
import time
from datetime import datetime
from uuid import UUID, uuid4

import pytest
import httpx

from tests.harness import ROOT, ROOM_ID, add_profile, booking_payload

pytestmark = pytest.mark.asyncio


async def submit(api, auth, borrower, **changes):
    response = await api.post(
        "/api/reservations",
        headers=auth.headers(borrower),
        json=booking_payload(**changes),
    )
    assert response.status_code == 201, response.text
    return response.json()


def onboarding_payload(**changes):
    return {
        "name": "首次建檔測試",
        "phone": "0912345678",
        "department": "資訊工程學系",
        "institutional_id": "NEW12345",
        **changes,
    }


async def test_google_identity_onboards_without_roster_or_auth_mutation(
    api, db, auth
):
    user = auth.add_user("new-student@email.ntou.edu.tw")
    headers = auth.headers(user)
    identity = await api.get("/api/auth/identity", headers=headers)
    assert identity.status_code == 200
    assert identity.json() == {
        "email": user["email"],
        "onboarding_required": True,
        "profile": None,
    }
    assert (await api.get("/api/me", headers=headers)).status_code == 403
    created = await api.post(
        "/api/auth/register", headers=headers, json=onboarding_payload()
    )
    assert created.status_code == 201, created.text
    profile = created.json()
    assert profile["id"] == user["id"] and profile["email"] == user["email"]
    assert (
        profile["role"] == "borrower"
        and profile["verified"]
        and not profile["suspended"]
    )
    assert await db.fetchval("SELECT count(*) FROM institutional_roster") == 0
    assert (
        await db.fetchval(
            "SELECT count(*) FROM audit_logs WHERE action='register'"
        )
        == 1
    )
    assert (await api.get("/api/auth/identity", headers=headers)).json() == {
        "email": user["email"],
        "onboarding_required": False,
        "profile": profile,
    }
    assert set(auth.requests) == {("GET", "/auth/v1/user")}
    assert set(auth.verified_bearers) == {
        headers["Authorization"].removeprefix("Bearer ")
    }


async def test_onboarding_retry_preserves_existing_admin_and_suspension(
    api, db, auth, admin
):
    await db.execute(
        "UPDATE profiles SET suspended=true WHERE id=$1", UUID(admin["id"])
    )
    original = (await api.get("/api/me", headers=auth.headers(admin))).json()
    repeated = await api.post(
        "/api/auth/register",
        headers=auth.headers(admin),
        json=onboarding_payload(),
    )
    assert repeated.status_code == 201 and repeated.json() == original
    assert repeated.json()["role"] == "admin" and repeated.json()["suspended"]
    assert (
        await db.fetchval(
            "SELECT count(*) FROM audit_logs WHERE action='register'"
        )
        == 0
    )


@pytest.mark.parametrize("table", ["profiles", "audit_logs"])
async def test_failed_onboarding_rolls_back_and_same_google_identity_can_retry(
    api, db, auth, table
):
    user = auth.add_user("retry@email.ntou.edu.tw")
    headers = auth.headers(user)
    await db.execute(f"""CREATE FUNCTION fail_onboarding_insert() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'test injected persistence failure'; END $$;
        CREATE TRIGGER fail_onboarding_insert BEFORE INSERT ON {table}
        FOR EACH ROW EXECUTE FUNCTION fail_onboarding_insert()""")
    failed = await api.post(
        "/api/auth/register", headers=headers, json=onboarding_payload()
    )
    assert failed.status_code == 503
    assert await db.fetchval("SELECT count(*) FROM profiles") == 0
    assert await db.fetchval("SELECT count(*) FROM audit_logs") == 0
    assert auth.users[user["email"]]["id"] == user["id"]
    assert set(auth.requests) == {("GET", "/auth/v1/user")}
    await db.execute(f"DROP TRIGGER fail_onboarding_insert ON {table}")
    retry = await api.post(
        "/api/auth/register", headers=headers, json=onboarding_payload()
    )
    assert retry.status_code == 201 and retry.json()["id"] == user["id"]
    assert await db.fetchval("SELECT count(*) FROM profiles") == 1
    assert (
        await db.fetchval(
            "SELECT count(*) FROM audit_logs WHERE action='register'"
        )
        == 1
    )
    assert set(auth.requests) == {("GET", "/auth/v1/user")}


async def test_parallel_same_google_uuid_has_one_profile_and_audit(
    api, db, auth
):
    user = auth.add_user("parallel@email.ntou.edu.tw")
    headers = auth.headers(user)
    gate = asyncio.Event()

    async def register():
        await gate.wait()
        return await api.post(
            "/api/auth/register", headers=headers, json=onboarding_payload()
        )

    tasks = [asyncio.create_task(register()) for _ in range(20)]
    await asyncio.sleep(0)
    gate.set()
    responses = await asyncio.gather(*tasks)
    assert all(response.status_code == 201 for response in responses)
    assert {response.json()["id"] for response in responses} == {user["id"]}
    assert await db.fetchval("SELECT count(*) FROM profiles") == 1
    assert (
        await db.fetchval(
            "SELECT count(*) FROM audit_logs WHERE action='register'"
        )
        == 1
    )


async def test_different_google_uuids_compete_for_one_institutional_id(
    api, db, auth
):
    users = [
        auth.add_user(f"race{index}@email.ntou.edu.tw") for index in range(2)
    ]
    gate = asyncio.Event()

    async def register(user):
        await gate.wait()
        return await api.post(
            "/api/auth/register",
            headers=auth.headers(user),
            json=onboarding_payload(),
        )

    tasks = [asyncio.create_task(register(user)) for user in users]
    await asyncio.sleep(0)
    gate.set()
    responses = await asyncio.gather(*tasks)
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert await db.fetchval("SELECT count(*) FROM profiles") == 1
    assert (
        await db.fetchval(
            "SELECT count(*) FROM audit_logs WHERE action='register'"
        )
        == 1
    )
    assert set(auth.requests) == {("GET", "/auth/v1/user")}


@pytest.mark.parametrize(
    "change",
    [
        {"role": "admin"},
        {"verified": True},
        {"suspended": True},
        {"id": str(uuid4())},
        {"email": "spoof@email.ntou.edu.tw"},
        {"password": "Input-must-never-be-echoed!"},
        {"phone": "invalid"},
        {"institutional_id": "12"},
        {"name": " "},
        {"department": " "},
    ],
)
async def test_onboarding_rejects_extra_privilege_and_invalid_contact(
    api, db, auth, change
):
    user = auth.add_user("invalid@email.ntou.edu.tw")
    response = await api.post(
        "/api/auth/register",
        headers=auth.headers(user),
        json=onboarding_payload(**change),
    )
    assert response.status_code == 422
    assert "Input-must-never-be-echoed!" not in response.text
    assert await db.fetchval("SELECT count(*) FROM profiles") == 0


@pytest.mark.parametrize(
    "missing", ["name", "phone", "department", "institutional_id"]
)
async def test_onboarding_requires_all_basic_fields(api, auth, missing):
    user = auth.add_user("missing@email.ntou.edu.tw")
    payload = onboarding_payload()
    del payload[missing]
    assert (
        await api.post(
            "/api/auth/register", headers=auth.headers(user), json=payload
        )
    ).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        b'{"email":"secret@email.ntou.edu.tw","password":"DO-NOT-ECHO"}',
        b"{broken",
        b"",
    ],
)
async def test_legacy_password_endpoint_is_403_without_parsing_or_upstream_call(
    api, auth, body
):
    response = await api.post(
        "/api/auth/login",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 403 and response.json() == {
        "detail": "請使用學校 Google 帳號登入"
    }
    assert "DO-NOT-ECHO" not in response.text and "secret@" not in response.text
    assert not auth.requests


@pytest.mark.parametrize(
    "change",
    [
        {"email": "student@gmail.com"},
        {"email": "student@mail.ntou.edu.tw"},
        {"email": "student@sub.email.ntou.edu.tw"},
        {"email": "student@email.ntou.edu.tw.evil.example"},
        {"email": "two@@email.ntou.edu.tw"},
        {"email": " student@email.ntou.edu.tw"},
        {"email_confirmed_at": None},
        {"is_anonymous": True},
        {"is_anonymous": None},
        {
            "app_metadata": {"provider": "email", "providers": ["google"]},
            "user_metadata": {"provider": "google"},
        },
        {
            "app_metadata": {
                "provider": "google",
                "providers": ["google", "github"],
            }
        },
        {"app_metadata": {"provider": "google", "providers": []}},
        {"app_metadata": {}},
        {"identities": []},
        {"identities": [{"provider": "email"}]},
        {
            "identities": [
                {
                    "provider": "google",
                    "identity_data": {
                        "email": "identity@email.ntou.edu.tw",
                        "email_verified": "true",
                    },
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
        {
            "identities": [
                {
                    "provider": "google",
                    "identity_data": {
                        "email": "identity@email.ntou.edu.tw",
                        "email_verified": True,
                    },
                },
                {"provider": "github"},
            ]
        },
    ],
)
async def test_campus_google_policy_fails_closed_before_profile_access(
    api, db, auth, change
):
    user = auth.add_user("identity@email.ntou.edu.tw")
    headers = auth.headers(user)
    user.update(change)
    for route in ("/api/auth/identity", "/api/me", "/api/me/eligibility"):
        assert (await api.get(route, headers=headers)).status_code == 403
    assert (
        await api.post(
            "/api/auth/register", headers=headers, json=onboarding_payload()
        )
    ).status_code == 403
    assert await db.fetchval("SELECT count(*) FROM profiles") == 0


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": str(uuid4())},
        {"sub": "bad-uuid"},
        {"amr": []},
        {"amr": None},
        {"amr": [{"method": "password"}]},
        {"amr": [{"method": "token_refresh"}]},
        {"amr": ["oauth"]},
    ],
)
async def test_only_same_upstream_verified_bearer_with_oauth_amr_is_allowed(
    api, auth, claims
):
    user = auth.add_user("amr@email.ntou.edu.tw")
    token = auth.session(user, claims=claims)["access_token"]
    response = await api.get(
        "/api/auth/identity", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403
    assert auth.verified_bearers == [token]


async def test_oauth_amr_survives_session_refresh(api, auth):
    user = auth.add_user("refresh@email.ntou.edu.tw")
    session = auth.session(user)
    response = auth.handle(
        httpx.Request(
            "POST",
            "https://fixture.supabase.co/auth/v1/token?grant_type=refresh_token",
            json={"refresh_token": session["refresh_token"]},
        )
    )
    refreshed = response.json()
    assert (
        await api.get(
            "/api/auth/identity",
            headers={"Authorization": f"Bearer {refreshed['access_token']}"},
        )
    ).status_code == 200
    assert auth.verified_bearers[-1] == refreshed["access_token"]


async def test_auth_hook_sql_and_business_role_permissions(db, pool):
    await db.execute(
        (ROOT / "supabase" / "tests" / "auth-hook.sql").read_text(
            encoding="utf-8"
        )
    )
    import asyncpg

    async with pool.acquire() as connection:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await connection.fetchval(
                "SELECT count(*) FROM institutional_roster"
            )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await connection.fetchval(
                "SELECT ntou_google_signup_gate('{}'::jsonb)"
            )


async def test_onboarding_rate_limits_account_and_ip_then_recovers(
    pool, db, auth, clock
):
    from datetime import timedelta
    from app.main import create_app
    from tests.harness import settings_for, test_database_url

    settings = settings_for(test_database_url())
    settings.auth_rate_limit, settings.auth_ip_rate_limit = 2, 3
    users = [
        auth.add_user(f"limited{index}@email.ntou.edu.tw") for index in range(2)
    ]
    app = create_app(
        settings,
        pool=pool,
        clock=clock,
        auth_transport=httpx.MockTransport(auth.handle),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for _ in range(2):
                assert (
                    await client.post(
                        "/api/auth/register",
                        headers=auth.headers(users[0]),
                        json=onboarding_payload(),
                    )
                ).status_code == 201
            limited = await client.post(
                "/api/auth/register",
                headers=auth.headers(users[0]),
                json=onboarding_payload(),
            )
            assert (
                limited.status_code == 429
                and limited.headers["Retry-After"] == "60"
            )
            assert (
                await client.post(
                    "/api/auth/register",
                    headers=auth.headers(users[1]),
                    json=onboarding_payload(institutional_id="OTHER1234"),
                )
            ).status_code == 429
            assert (
                users[0]["email"] not in limited.text
                and "0912345678" not in limited.text
            )
            keys = await db.fetch("SELECT key_hash FROM auth_rate_limits")
            assert keys and all(len(row["key_hash"]) == 64 for row in keys)
            clock.now += timedelta(seconds=60)
            assert (
                await client.post(
                    "/api/auth/register",
                    headers=auth.headers(users[0]),
                    json=onboarding_payload(),
                )
            ).status_code == 201


async def test_history_pagination_and_status_filter_preserve_owner_scope(
    api, auth, borrower, other_borrower
):
    owned = [await submit(api, auth, borrower) for _ in range(3)]
    await submit(api, auth, other_borrower)
    headers = auth.headers(borrower)
    pages = [
        (
            await api.get(
                "/api/reservations",
                headers=headers,
                params={"limit": 2, "offset": offset},
            )
        ).json()
        for offset in (0, 2, 4)
    ]
    assert [page["total"] for page in pages] == [3, 3, 3]
    assert [len(page["items"]) for page in pages] == [2, 1, 0]
    identifiers = [row["id"] for page in pages for row in page["items"]]
    assert len(identifiers) == len(set(identifiers)) == 3
    assert set(identifiers) == {row["id"] for row in owned}
    assert (
        await api.patch(
            f"/api/reservations/{owned[0]['id']}/status",
            headers=headers,
            json={"status": "cancelled"},
        )
    ).status_code == 200
    filtered = (
        await api.get(
            "/api/reservations", headers=headers, params={"status": "pending"}
        )
    ).json()
    assert filtered["total"] == 2 and all(
        row["status"] == "pending" for row in filtered["items"]
    )
    for invalid in ({"limit": 101}, {"offset": -1}):
        assert (
            await api.get("/api/reservations", headers=headers, params=invalid)
        ).status_code == 422


async def test_upstream_failure_returns_503(api, auth, borrower):
    auth.unavailable = True
    response = await api.get(
        "/api/auth/identity", headers=auth.headers(borrower)
    )
    assert response.status_code == 503


async def test_google_confirmation_and_own_id_verification_without_roster(
    api, db, auth
):
    user = await add_profile(db, auth, index=3, verified=False, confirmed=False)
    headers = auth.headers(user)
    assert (
        await api.post(
            "/api/reservations", headers=headers, json=booking_payload()
        )
    ).status_code == 403
    body = {"institutional_id": user["institutional_id"]}
    assert (
        await api.post("/api/me/verify", headers=headers, json=body)
    ).status_code == 403
    auth.users[user["email"]]["email_confirmed_at"] = "2026-10-12T02:00:00Z"
    assert (
        await api.post(
            "/api/me/verify",
            headers=headers,
            json={"institutional_id": "WRONG123"},
        )
    ).status_code == 403
    verified = await api.post("/api/me/verify", headers=headers, json=body)
    assert verified.status_code == 200 and verified.json()["verified"]
    assert (
        await api.post(
            "/api/reservations", headers=headers, json=booking_payload()
        )
    ).status_code == 201


async def test_missing_and_forged_bearer_are_denied(api):
    payload = booking_payload()
    assert (
        await api.post("/api/reservations", json=payload)
    ).status_code == 401
    assert (
        await api.post(
            "/api/reservations",
            json=payload,
            headers={"Authorization": "Bearer forged"},
        )
    ).status_code == 401
    assert (await api.get("/api/auth/identity")).status_code == 401
    assert (
        await api.post("/api/auth/register", json=onboarding_payload())
    ).status_code == 401


async def test_legacy_profile_email_mismatch_is_preserved_and_denied(
    api, db, auth, borrower
):
    await db.execute(
        "UPDATE profiles SET email='previous@mail.ntou.edu.tw' WHERE id=$1",
        UUID(borrower["id"]),
    )
    headers = auth.headers(borrower)
    assert (
        await api.get("/api/auth/identity", headers=headers)
    ).status_code == 403
    assert (await api.get("/api/me", headers=headers)).status_code == 403
    assert (
        await api.post(
            "/api/auth/register", headers=headers, json=onboarding_payload()
        )
    ).status_code == 403
    assert (
        await db.fetchval(
            "SELECT email FROM profiles WHERE id=$1", UUID(borrower["id"])
        )
        == "previous@mail.ntou.edu.tw"
    )


async def test_room_filters_require_all_selected_equipment(api):
    single = await api.get("/api/rooms", params={"equipment": "投影機"})
    assert single.status_code == 200 and len(single.json()["items"]) == 3
    multiple = await api.get(
        "/api/rooms", params=[("equipment", "投影機"), ("equipment", "麥克風")]
    )
    assert multiple.status_code == 200 and [
        item["code"] for item in multiple.json()["items"]
    ] == ["HUM-305"]
    availability = await api.get(
        "/api/rooms/availability",
        params=[
            ("start", "2026-10-13T10:00:00+08:00"),
            ("end", "2026-10-13T12:00:00+08:00"),
            ("equipment", "投影機"),
            ("equipment", "麥克風"),
        ],
    )
    assert availability.status_code == 200 and [
        item["code"] for item in availability.json()["items"]
    ] == ["HUM-305"]


async def test_full_lifecycle_keys_history_audit_and_durable_notifications(
    api, db, auth, borrower, admin, clock
):
    booking = await submit(api, auth, borrower)
    assert booking["status"] == "pending"
    states = []
    for status in ("approved", "checked_out", "completed"):
        if status == "checked_out":
            clock.now = datetime.fromisoformat("2026-10-13T10:00:00+08:00")
        response = await api.patch(
            f"/api/reservations/{booking['id']}/status",
            headers=auth.headers(admin),
            json={"status": status},
        )
        assert response.status_code == 200, response.text
        states.append(response.json())
    assert states[1]["key_handed_at"] and states[2]["key_returned_at"]
    record = await db.fetchrow(
        "SELECT * FROM reservations WHERE id=$1", UUID(booking["id"])
    )
    assert (
        str(record["key_handed_by"])
        == admin["id"]
        == str(record["key_returned_by"])
    )
    repeat = await api.patch(
        f"/api/reservations/{booking['id']}/status",
        headers=auth.headers(admin),
        json={"status": "completed"},
    )
    assert repeat.status_code == 409
    history = (
        await api.get("/api/reservations", headers=auth.headers(borrower))
    ).json()
    assert (
        history["total"] == 1 and history["items"][0]["status"] == "completed"
    )
    logs = await db.fetch(
        "SELECT old_status,new_status FROM audit_logs WHERE reservation_id=$1",
        UUID(booking["id"]),
    )
    assert {(r["old_status"], r["new_status"]) for r in logs} >= {
        ("pending", "approved"),
        ("approved", "checked_out"),
        ("checked_out", "completed"),
    }
    assert (
        await db.fetchval(
            "SELECT count(*) FROM notifications WHERE reservation_id=$1 AND user_id=$2",
            UUID(booking["id"]),
            UUID(borrower["id"]),
        )
        >= 4
    )


async def test_rejection_needs_reason_and_cannot_be_reopened(
    api, auth, borrower, admin
):
    booking = await submit(api, auth, borrower)
    route = f"/api/reservations/{booking['id']}/status"
    assert (
        await api.patch(
            route, headers=auth.headers(admin), json={"status": "rejected"}
        )
    ).status_code == 422
    assert (
        await api.patch(
            route, headers=auth.headers(admin), json={"status": "completed"}
        )
    ).status_code == 409
    rejected = await api.patch(
        route,
        headers=auth.headers(admin),
        json={"status": "rejected", "reason": "教室已有活動"},
    )
    assert (
        rejected.status_code == 200
        and rejected.json()["decision_reason"] == "教室已有活動"
    )
    assert (
        await api.patch(
            route, headers=auth.headers(admin), json={"status": "approved"}
        )
    ).status_code == 409


async def test_idempotency_prevents_duplicate_and_uses_original_request(
    api, db, auth, borrower
):
    payload = booking_payload()
    first = await api.post(
        "/api/reservations", headers=auth.headers(borrower), json=payload
    )
    repeated = await api.post(
        "/api/reservations", headers=auth.headers(borrower), json=payload
    )
    assert first.status_code == 201 and repeated.status_code in {200, 201}
    assert repeated.json()["id"] == first.json()["id"]
    assert (
        await db.fetchval(
            "SELECT count(*) FROM reservations WHERE user_id=$1",
            UUID(borrower["id"]),
        )
        == 1
    )


async def test_immediate_mode(api, auth, borrower):
    booking = await submit(
        api,
        auth,
        borrower,
        start="2026-10-12T10:05:00+08:00",
        end="2026-10-12T11:05:00+08:00",
        mode="immediate",
    )
    assert booking["mode"] == "immediate" and booking["status"] == "pending"


@pytest.mark.parametrize(
    "changes",
    [
        {"starts_at": "2026-10-13T10:00:00", "ends_at": "2026-10-13T12:00:00"},
        {"ends_at": "2026-10-13T09:00:00+08:00"},
        {"ends_at": "2026-10-13T10:15:00+08:00"},
        {
            "starts_at": "2026-10-11T10:00:00+08:00",
            "ends_at": "2026-10-11T12:00:00+08:00",
        },
        {
            "starts_at": "2027-03-12T10:00:00+08:00",
            "ends_at": "2027-03-12T12:00:00+08:00",
        },
        {
            "starts_at": "2026-10-13T21:00:00+08:00",
            "ends_at": "2026-10-14T09:00:00+08:00",
        },
        {
            "starts_at": "2026-10-13T07:00:00+08:00",
            "ends_at": "2026-10-13T09:00:00+08:00",
        },
        {"attendees": 49},
        {"user_id": str(uuid4())},
        {"status": "approved"},
    ],
)
async def test_invalid_booking_boundaries_leave_no_record(
    api, db, auth, borrower, changes
):
    response = await api.post(
        "/api/reservations",
        headers=auth.headers(borrower),
        json=booking_payload(**changes),
    )
    assert response.status_code == 422, response.text
    assert await db.fetchval("SELECT count(*) FROM reservations") == 0


async def test_inactive_room_cannot_be_requested(api, db, auth, borrower):
    await db.execute("UPDATE rooms SET active=false WHERE id=$1", ROOM_ID)
    response = await api.post(
        "/api/reservations",
        headers=auth.headers(borrower),
        json=booking_payload(),
    )
    assert response.status_code in {404, 409, 422}
    assert await db.fetchval("SELECT count(*) FROM reservations") == 0


async def test_borrower_cannot_call_any_admin_mutation_even_with_metadata_role(
    api, auth, borrower, other_borrower
):
    auth.users[borrower["email"]]["user_metadata"] = {
        "role": "admin",
        "verified": True,
    }
    booking = await submit(api, auth, borrower)
    headers = auth.headers(borrower)
    cases = [
        ("GET", "/api/admin/users", None),
        ("GET", "/api/admin/violations", None),
        (
            "PATCH",
            f"/api/admin/users/{other_borrower['id']}",
            {"suspended": True},
        ),
        (
            "POST",
            "/api/admin/violations",
            {
                "user_id": other_borrower["id"],
                "points": 1,
                "reason": "逾時歸還",
            },
        ),
        ("PATCH", f"/api/admin/violations/{uuid4()}", {"resolved": True}),
        (
            "PATCH",
            f"/api/reservations/{booking['id']}/status",
            {"status": "approved"},
        ),
        (
            "PATCH",
            f"/api/reservations/{booking['id']}/status",
            {"status": "rejected", "reason": "沒有權限"},
        ),
        (
            "PATCH",
            f"/api/reservations/{booking['id']}/status",
            {"status": "checked_out"},
        ),
    ]
    for method, route, payload in cases:
        response = await api.request(
            method, route, headers=headers, json=payload
        )
        assert response.status_code == 403, (route, response.text)
    image = await api.post(
        f"/api/admin/rooms/{ROOM_ID}/map",
        headers=headers,
        files={"file": ("fixture.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert image.status_code == 403


async def test_owner_history_cancel_and_notifications_do_not_leak(
    api, auth, borrower, other_borrower
):
    first = await submit(api, auth, borrower)
    second = await submit(api, auth, other_borrower)
    history = (
        await api.get("/api/reservations", headers=auth.headers(borrower))
    ).json()
    assert history["total"] == 1 and history["items"][0]["id"] == first["id"]
    foreign_cancel = await api.patch(
        f"/api/reservations/{second['id']}/status",
        headers=auth.headers(borrower),
        json={"status": "cancelled"},
    )
    assert foreign_cancel.status_code in {403, 404}
    notes = (
        await api.get(
            "/api/notifications", headers=auth.headers(other_borrower)
        )
    ).json()["items"]
    assert notes
    foreign_read = await api.patch(
        f"/api/notifications/{notes[0]['id']}/read",
        headers=auth.headers(borrower),
        json={},
    )
    assert foreign_read.status_code == 404
    assert (
        await api.patch(
            f"/api/notifications/{notes[0]['id']}/read",
            headers=auth.headers(other_borrower),
            json={},
        )
    ).status_code == 200
    assert (
        await api.patch(
            f"/api/reservations/{first['id']}/status",
            headers=auth.headers(borrower),
            json={"status": "cancelled"},
        )
    ).status_code == 200


async def test_partial_overlap_blocked_adjacent_available_and_public_schedule_redacted(
    api, auth, borrower, admin
):
    original = await submit(api, auth, borrower)
    assert (
        await api.patch(
            f"/api/reservations/{original['id']}/status",
            headers=auth.headers(admin),
            json={"status": "approved"},
        )
    ).status_code == 200
    partial = await submit(
        api,
        auth,
        borrower,
        start="2026-10-13T11:00:00+08:00",
        end="2026-10-13T13:00:00+08:00",
    )
    assert (
        await api.patch(
            f"/api/reservations/{partial['id']}/status",
            headers=auth.headers(admin),
            json={"status": "approved"},
        )
    ).status_code == 409
    adjacent = await submit(
        api,
        auth,
        borrower,
        start="2026-10-13T12:00:00+08:00",
        end="2026-10-13T14:00:00+08:00",
    )
    assert (
        await api.patch(
            f"/api/reservations/{adjacent['id']}/status",
            headers=auth.headers(admin),
            json={"status": "approved"},
        )
    ).status_code == 200
    params = {
        "start": "2026-10-13T11:00:00+08:00",
        "end": "2026-10-13T11:30:00+08:00",
    }
    rooms = (await api.get("/api/rooms/availability", params=params)).json()[
        "items"
    ]
    assert not next(room for room in rooms if room["id"] == str(ROOM_ID))[
        "available"
    ]
    schedule = await api.get(
        f"/api/rooms/{ROOM_ID}/schedule",
        params={
            "start": "2026-10-13T00:00:00+08:00",
            "end": "2026-10-19T00:00:00+08:00",
        },
    )
    assert schedule.status_code == 200 and len(schedule.json()["items"]) == 2
    assert (
        "user_id" not in schedule.text
        and "purpose" not in schedule.text
        and borrower["email"] not in schedule.text
    )


async def test_suspension_applies_to_existing_token_within_five_seconds(
    api, auth, borrower, admin
):
    headers = auth.headers(borrower)
    pending = await submit(api, auth, borrower)
    started = time.perf_counter()
    suspend = await api.patch(
        f"/api/admin/users/{borrower['id']}",
        headers=auth.headers(admin),
        json={"suspended": True},
    )
    assert suspend.status_code == 200
    assert (
        await api.post(
            "/api/reservations", headers=headers, json=booking_payload()
        )
    ).status_code == 403
    assert time.perf_counter() - started < 5
    assert (
        await api.patch(
            f"/api/reservations/{pending['id']}/status",
            headers=auth.headers(admin),
            json={"status": "approved"},
        )
    ).status_code == 403
    restored = await api.patch(
        f"/api/admin/users/{borrower['id']}",
        headers=auth.headers(admin),
        json={"suspended": False},
    )
    assert restored.status_code == 200
    assert (
        await api.post(
            "/api/reservations", headers=headers, json=booking_payload()
        )
    ).status_code == 201


async def test_three_violation_points_suspend_then_resolution_allows_restore(
    api, auth, borrower, admin
):
    violation = await api.post(
        "/api/admin/violations",
        headers=auth.headers(admin),
        json={
            "user_id": borrower["id"],
            "points": 3,
            "reason": "未依規定歸還鑰匙",
        },
    )
    assert violation.status_code == 201, violation.text
    eligibility = (
        await api.get("/api/me/eligibility", headers=auth.headers(borrower))
    ).json()
    assert (
        eligibility["violation_points"] == 3
        and eligibility["suspended"]
        and not eligibility["eligible"]
    )
    assert (
        await api.post(
            "/api/reservations",
            headers=auth.headers(borrower),
            json=booking_payload(),
        )
    ).status_code == 403
    assert (
        await api.patch(
            f"/api/admin/users/{borrower['id']}",
            headers=auth.headers(admin),
            json={"suspended": False},
        )
    ).status_code == 409
    assert (
        await api.patch(
            f"/api/admin/violations/{violation.json()['id']}",
            headers=auth.headers(admin),
            json={"resolved": True},
        )
    ).status_code == 200
    assert (
        await api.patch(
            f"/api/admin/users/{borrower['id']}",
            headers=auth.headers(admin),
            json={"suspended": False},
        )
    ).status_code == 200
    assert (
        await api.post(
            "/api/reservations",
            headers=auth.headers(borrower),
            json=booking_payload(),
        )
    ).status_code == 201


async def test_violation_pagination_reaches_old_unresolved_record(
    api, db, auth, borrower, other_borrower, admin, clock
):
    headers = auth.headers(admin)
    oldest = await api.post(
        "/api/admin/violations",
        headers=headers,
        json={
            "user_id": borrower["id"],
            "points": 3,
            "reason": "歷史未結案違規",
        },
    )
    assert oldest.status_code == 201, oldest.text
    oldest_id = oldest.json()["id"]
    # Seed a history longer than one page, with every newer violation already resolved.
    await db.execute(
        """INSERT INTO violations(user_id,points,reason,resolved,created_by,created_at)
        SELECT $1,1,'較新已結案違規',true,$2,$3::timestamptz + sequence * interval '1 second'
        FROM generate_series(1,100) AS sequence""",
        UUID(borrower["id"]),
        UUID(admin["id"]),
        clock.now,
    )
    first = await api.get(
        "/api/admin/violations",
        headers=headers,
        params={"limit": 100, "offset": 0},
    )
    assert first.status_code == 200, first.text
    assert first.json()["total"] == 101 and len(first.json()["items"]) == 100
    first_ids = {item["id"] for item in first.json()["items"]}
    assert len(first_ids) == 100
    assert all(item["id"] != oldest_id for item in first.json()["items"])
    last = await api.get(
        "/api/admin/violations",
        headers=headers,
        params={"limit": 100, "offset": 100},
    )
    assert last.status_code == 200, last.text
    assert last.json()["total"] == 101 and [
        item["id"] for item in last.json()["items"]
    ] == [oldest_id]
    assert oldest_id not in first_ids
    assert last.json()["items"][0]["user_name"] == "測試使用者 1"
    assert (
        last.json()["items"][0]["institutional_id"]
        == borrower["institutional_id"]
    )
    assert not last.json()["items"][0]["resolved"]
    assert (
        await api.patch(
            f"/api/admin/users/{borrower['id']}",
            headers=headers,
            json={"suspended": False},
        )
    ).status_code == 409
    resolved = await api.patch(
        f"/api/admin/violations/{oldest_id}",
        headers=headers,
        json={"resolved": True},
    )
    assert resolved.status_code == 200 and resolved.json()["resolved"]
    assert (
        await api.patch(
            f"/api/admin/users/{borrower['id']}",
            headers=headers,
            json={"suspended": False},
        )
    ).status_code == 200
    assert (
        await api.post(
            "/api/reservations",
            headers=auth.headers(borrower),
            json=booking_payload(),
        )
    ).status_code == 201
    await db.execute(
        """INSERT INTO violations(user_id,points,reason,resolved,created_by,created_at)
        VALUES($1,1,'其他借用人違規',true,$2,$3)""",
        UUID(other_borrower["id"]),
        UUID(admin["id"]),
        clock.now,
    )
    filtered = await api.get(
        "/api/admin/violations",
        headers=headers,
        params={"user_id": borrower["id"], "limit": 100, "offset": 100},
    )
    assert filtered.status_code == 200 and filtered.json()["total"] == 101
    assert [item["id"] for item in filtered.json()["items"]] == [oldest_id]
    empty = await api.get(
        "/api/admin/violations",
        headers=headers,
        params={"limit": 100, "offset": 102},
    )
    assert empty.status_code == 200 and empty.json() == {
        "items": [],
        "total": 102,
    }
    for params in [{"limit": 0}, {"limit": 101}, {"offset": -1}]:
        assert (
            await api.get(
                "/api/admin/violations", headers=headers, params=params
            )
        ).status_code == 422


async def test_push_subscriptions_are_owned_and_ssrf_safe(
    api, db, auth, borrower, other_borrower
):
    keys = {
        "p256dh": base64.urlsafe_b64encode(b"\x04" + bytes(64))
        .decode()
        .rstrip("="),
        "auth": base64.urlsafe_b64encode(bytes(16)).decode().rstrip("="),
    }
    endpoint = "https://fcm.googleapis.com/fcm/send/fixture-endpoint"
    created = await api.post(
        "/api/push-subscriptions",
        headers=auth.headers(borrower),
        json={"endpoint": endpoint, "keys": keys},
    )
    assert created.status_code == 201, created.text
    foreign_delete = await api.request(
        "DELETE",
        "/api/push-subscriptions",
        headers=auth.headers(other_borrower),
        json={"endpoint": endpoint},
    )
    assert foreign_delete.status_code in {204, 404}
    assert await db.fetchval("SELECT count(*) FROM push_subscriptions") == 1
    for bad in [
        "http://127.0.0.1/internal",
        "https://fcm.googleapis.com.evil.example/push",
        "https://fcm.googleapis.com:8443/push",
    ]:
        assert (
            await api.post(
                "/api/push-subscriptions",
                headers=auth.headers(borrower),
                json={"endpoint": bad, "keys": keys},
            )
        ).status_code == 422
    assert (
        await api.request(
            "DELETE",
            "/api/push-subscriptions",
            headers=auth.headers(borrower),
            json={"endpoint": endpoint},
        )
    ).status_code == 204


async def test_application_role_cannot_change_role_or_write_audit_history(
    pool, db, borrower
):
    import asyncpg

    async with pool.acquire() as connection:
        assert (
            await connection.fetchval("SELECT current_user") == "ntou_backend"
        )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await connection.execute(
                "UPDATE profiles SET role='admin' WHERE id=$1",
                UUID(borrower["id"]),
            )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await connection.execute("DELETE FROM audit_logs")
    columns = await db.fetch(
        "SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public' AND column_name ILIKE '%password%'"
    )
    assert not columns


async def test_storage_upload_accepts_safe_image_and_rejects_active_or_oversized_content(
    api, db, auth, admin
):
    route = f"/api/admin/rooms/{ROOM_ID}/map"
    headers = auth.headers(admin)
    for filename, content, mime in [
        ("bad.svg", b'<svg onload="alert(1)"></svg>', "image/svg+xml"),
        ("fake.png", b"not a png", "image/png"),
        ("large.png", b"\x89PNG\r\n\x1a\n" + bytes(2097152), "image/png"),
    ]:
        assert (
            await api.post(
                route,
                headers=headers,
                files={"file": (filename, content, mime)},
            )
        ).status_code == 422
    # Fixture validates transport/ownership; production image decoding remains the Storage MIME gate.
    image = b"\x89PNG\r\n\x1a\nfixture-test"
    uploaded = await api.post(
        route, headers=headers, files={"file": ("room.png", image, "image/png")}
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["map_url"].startswith(
        "https://fixture.supabase.co/storage/v1/object/sign/"
    )
    assert await db.fetchval("SELECT map_path FROM rooms WHERE id=$1", ROOM_ID)
