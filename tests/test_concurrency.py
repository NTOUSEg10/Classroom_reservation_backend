import asyncio
import time
from collections import Counter
from datetime import datetime
from uuid import UUID, uuid4

import asyncpg
import pytest

from tests.harness import (
    ROOM_ID,
    add_profile,
    booking_payload,
    test_database_url as database_url,
)
from tests.metrics import latency_summary, write_report

pytestmark = pytest.mark.asyncio


async def concurrent_requests(actions):
    start_gate = asyncio.Event()
    dispatches = []

    async def run(action):
        await start_gate.wait()
        start = time.perf_counter()
        dispatches.append(start)
        result = await action()
        return result, time.perf_counter() - start

    tasks = [asyncio.create_task(run(action)) for action in actions]
    await asyncio.sleep(0)
    start_gate.set()
    results = await asyncio.gather(*tasks)
    return results, (max(dispatches) - min(dispatches)) * 1000


async def test_100_simultaneous_requests_then_approvals_have_one_winner(
    api, db, auth, admin
):
    users = [
        await add_profile(db, auth, index=index) for index in range(1, 101)
    ]
    payloads = [booking_payload() for _ in users]
    creates, create_spread = await concurrent_requests(
        [
            lambda user=user, payload=payload: api.post(
                "/api/reservations", headers=auth.headers(user), json=payload
            )
            for user, payload in zip(users, payloads)
        ]
    )
    assert all(response.status_code == 201 for response, _ in creates), Counter(
        response.status_code for response, _ in creates
    )
    assert max(duration for _, duration in creates) < 2
    approvals, approval_spread = await concurrent_requests(
        [
            lambda reservation=response.json(): api.patch(
                f"/api/reservations/{reservation['id']}/status",
                headers=auth.headers(admin),
                json={"status": "approved"},
            )
            for response, _ in creates
        ]
    )
    statuses = Counter(response.status_code for response, _ in approvals)
    assert statuses == {200: 1, 409: 99}, [
        (r.status_code, r.text)
        for r, _ in approvals
        if r.status_code not in {200, 409}
    ]
    assert (
        await db.fetchval(
            "SELECT count(*) FROM reservations WHERE status='approved'"
        )
        == 1
    )
    assert (
        await db.fetchval(
            "SELECT count(*) FROM reservations WHERE status='pending'"
        )
        == 99
    )
    write_report(
        "upgrade-concurrency-api",
        {
            "database_version": await db.fetchval("SHOW server_version"),
            "users": 100,
            "simultaneity": "100 tasks released by one asyncio Event; scheduler dispatch spread measured",
            "applications": {
                **latency_summary(
                    [duration for _, duration in creates],
                    [r.status_code for r, _ in creates],
                ),
                "dispatch_spread_ms": round(create_spread, 3),
                "sla_ms": 2000,
            },
            "approvals": {
                **latency_summary(
                    [duration for _, duration in approvals],
                    [r.status_code for r, _ in approvals],
                ),
                "dispatch_spread_ms": round(approval_spread, 3),
                "approved_rows": 1,
            },
        },
    )


async def test_direct_sql_100_independent_connections_preserve_exclusion_constraint(
    db, borrower
):
    ids = [uuid4() for _ in range(100)]
    await db.executemany(
        "INSERT INTO reservations(id,user_id,room_id,starts_at,ends_at,purpose,attendees,mode,request_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)",
        [
            (
                identifier,
                UUID(borrower["id"]),
                ROOM_ID,
                datetime.fromisoformat("2026-10-13T10:00:00+08:00"),
                datetime.fromisoformat("2026-10-13T12:00:00+08:00"),
                "資料庫直接並行防護",
                10,
                "scheduled",
                uuid4(),
            )
            for identifier in ids
        ],
    )
    opened = await asyncio.gather(
        *[asyncpg.connect(database_url(), command_timeout=10) for _ in ids],
        return_exceptions=True,
    )
    connections = [
        result for result in opened if isinstance(result, asyncpg.Connection)
    ]
    winner = None
    winner_committed = False
    jobs = []
    try:
        errors = Counter(
            type(result).__name__
            for result in opened
            if isinstance(result, Exception)
        )
        assert not errors, (
            f"Only {len(connections)}/100 test DB connections opened: {dict(errors)}; stop idle test servers or increase the local test connection budget"
        )
        for connection in connections:
            await connection.execute("SET ROLE ntou_backend")
        pids = [
            await connection.fetchval("SELECT pg_backend_pid()")
            for connection in connections
        ]
        assert len(set(pids)) == 100
        gate = asyncio.Event()
        winner_started = time.perf_counter()
        dispatches = [winner_started]
        winner = connections[0].transaction()
        await winner.start()
        await connections[0].execute(
            "UPDATE reservations SET status='approved' WHERE id=$1", ids[0]
        )

        async def approve(connection, identifier):
            await gate.wait()
            started = time.perf_counter()
            dispatches.append(started)
            try:
                async with connection.transaction():
                    await connection.execute(
                        "UPDATE reservations SET status='approved' WHERE id=$1",
                        identifier,
                    )
                outcome = "approved"
            except (
                asyncpg.ExclusionViolationError,
                asyncpg.DeadlockDetectedError,
            ) as error:
                outcome = error.sqlstate
            return outcome, time.perf_counter() - started

        jobs = [
            asyncio.create_task(approve(connection, identifier))
            for connection, identifier in zip(connections[1:], ids[1:])
        ]
        await asyncio.sleep(0)
        gate.set()
        blocked = 0
        deadline = time.perf_counter() + 5
        while time.perf_counter() < deadline:
            blocked = await db.fetchval(
                "SELECT count(*) FROM pg_stat_activity WHERE pid=ANY($1::int[]) AND wait_event_type='Lock'",
                pids[1:],
            )
            if blocked == 99:
                break
            await asyncio.sleep(0.01)
        assert blocked == 99, (
            f"Only {blocked}/99 competing transactions reached the PostgreSQL lock wait"
        )
        await winner.commit()
        winner_committed = True
        results = [
            ("approved", time.perf_counter() - winner_started),
            *await asyncio.gather(*jobs),
        ]
        outcomes = Counter(outcome for outcome, _ in results)
        assert outcomes == {"approved": 1, "23P01": 99}, outcomes
        assert (
            await db.fetchval(
                "SELECT count(*) FROM reservations WHERE status='approved'"
            )
            == 1
        )
        write_report(
            "upgrade-concurrency-direct-sql",
            {
                "database_version": await db.fetchval("SHOW server_version"),
                "independent_connections": len(set(pids)),
                "outcomes": dict(outcomes),
                "approved_rows": 1,
                "dispatch_spread_ms": round(
                    (max(dispatches) - min(dispatches)) * 1000, 3
                ),
                "blocked_connections_before_winner_commit": blocked,
                "explicit_transaction_overlap": True,
                "latency": latency_summary(
                    [duration for _, duration in results]
                ),
                "note": "Winner is deliberately held uncommitted until all 99 competing connections wait on PostgreSQL locks; these durations include that hold and are not API SLA measurements. Every losing transaction rolls back with SQLSTATE 23P01.",
            },
        )
    finally:
        if winner is not None and not winner_committed:
            await winner.rollback()
        for job in jobs:
            if not job.done():
                job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        await asyncio.gather(
            *[connection.close() for connection in connections]
        )


async def test_100_same_request_id_has_one_record(api, db, auth, borrower):
    payload = booking_payload()
    results, _ = await concurrent_requests(
        [
            lambda: api.post(
                "/api/reservations",
                headers=auth.headers(borrower),
                json=payload,
            )
            for _ in range(100)
        ]
    )
    assert all(response.status_code in {200, 201} for response, _ in results)
    assert len({response.json()["id"] for response, _ in results}) == 1
    assert await db.fetchval("SELECT count(*) FROM reservations") == 1
