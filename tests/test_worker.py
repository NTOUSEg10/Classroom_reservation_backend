import asyncio
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from notification_worker.worker import Dispatcher
from tests.harness import NOW


async def insert_note(db, borrower, *, attempts=0, claimed_at=None):
    return await db.fetchval(
        """INSERT INTO notifications(user_id,title,body,created_at,next_attempt_at,attempts,claimed_at)
           VALUES($1,'狀態已更新','請查看借用紀錄',$2,$2,$3,$4) RETURNING id""",
        UUID(borrower["id"]),
        NOW,
        attempts,
        claimed_at,
    )


@pytest.mark.asyncio
async def test_committed_notification_dispatches_and_uses_private_credentials(
    db, pool, borrower
):
    note = await insert_note(db, borrower)
    received = []

    def provider(request):
        received.append(request)
        return httpx.Response(200, json={"ok": True, "accepted": 1})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(provider)
    ) as client:
        dispatcher = Dispatcher(
            pool,
            client,
            "https://fixture.supabase.co/functions/v1/dispatch-push",
            "fixture-dispatch-secret",
            "fixture-service-key",
            clock=lambda: NOW,
        )
        result = await dispatcher.tick()
    assert result.accepted == 1 and result.failed == 0
    assert received[0].headers["X-Dispatch-Secret"] == "fixture-dispatch-secret"
    assert received[0].headers["apikey"] == "fixture-service-key"
    row = await db.fetchrow("SELECT * FROM notifications WHERE id=$1", note)
    assert (
        row["delivered_at"] == NOW
        and row["attempts"] == 1
        and row["last_error"] is None
    )
    # Mock clock checks dispatch timing; actual remote provider latency is a separate deployment gate.
    assert (row["delivered_at"] - row["created_at"]).total_seconds() < 3


@pytest.mark.asyncio
async def test_failed_push_is_durable_and_retries_with_mock_clock(
    db, pool, borrower
):
    note = await insert_note(db, borrower)
    time = [NOW]
    status = [503]
    sent = []

    def provider(request):
        sent.append(request)
        return httpx.Response(status[0], json={"ok": status[0] == 200})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(provider)
    ) as client:
        dispatcher = Dispatcher(
            pool,
            client,
            "https://fixture.supabase.co/functions/v1/dispatch-push",
            "secret",
            "key",
            clock=lambda: time[0],
        )
        assert (await dispatcher.tick()).failed == 1
        row = await db.fetchrow("SELECT * FROM notifications WHERE id=$1", note)
        assert row["delivered_at"] is None and row["claimed_at"] is None
        assert row["last_error"] == "HTTPStatusError"
        time[0] += timedelta(milliseconds=999)
        assert (await dispatcher.tick()).accepted == 0 and len(sent) == 1
        time[0] += timedelta(milliseconds=1)
        status[0] = 200
        assert (await dispatcher.tick()).accepted == 1
    row = await db.fetchrow("SELECT * FROM notifications WHERE id=$1", note)
    assert row["attempts"] == 2 and row["last_error"] is None


@pytest.mark.asyncio
async def test_two_workers_claim_each_notification_once(db, pool, borrower):
    notes = {await insert_note(db, borrower) for _ in range(200)}
    received = []

    def provider(request):
        import json

        received.append(UUID(json.loads(request.content)["notification_id"]))
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(provider)
    ) as client:
        workers = [
            Dispatcher(
                pool,
                client,
                "https://fixture.supabase.co/functions/v1/dispatch-push",
                "secret",
                "key",
                clock=lambda: NOW,
            )
            for _ in range(2)
        ]
        results = await asyncio.gather(*(worker.tick() for worker in workers))
    assert sum(result.accepted for result in results) == 200
    assert len(received) == 200 and set(received) == notes


@pytest.mark.asyncio
async def test_crashed_worker_lease_recovers_after_30_seconds(
    db, pool, borrower
):
    note = await insert_note(db, borrower, claimed_at=NOW)
    time = [NOW + timedelta(seconds=30)]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"ok": True})
        )
    ) as client:
        dispatcher = Dispatcher(
            pool,
            client,
            "https://fixture.supabase.co/functions/v1/dispatch-push",
            "secret",
            "key",
            clock=lambda: time[0],
        )
        assert (await dispatcher.tick()).accepted == 0
        time[0] += timedelta(milliseconds=1)
        assert (await dispatcher.tick()).accepted == 1
    assert await db.fetchval(
        "SELECT delivered_at IS NOT NULL FROM notifications WHERE id=$1", note
    )


@pytest.mark.asyncio
async def test_bad_ack_cannot_mark_push_delivered(db, pool, borrower):
    note = await insert_note(db, borrower)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"unexpected": "response"})
        )
    ) as client:
        dispatcher = Dispatcher(
            pool,
            client,
            "https://fixture.supabase.co/functions/v1/dispatch-push",
            "secret",
            "key",
            clock=lambda: NOW,
        )
        assert (await dispatcher.tick()).failed == 1
    assert (
        await db.fetchval(
            "SELECT delivered_at FROM notifications WHERE id=$1", note
        )
        is None
    )


@pytest.mark.asyncio
async def test_hung_provider_expires_without_blocking_other_notifications(
    db, pool, borrower, monkeypatch
):
    import json

    hung = await insert_note(db, borrower)
    healthy = await insert_note(db, borrower)
    clock = [NOW]
    deadlines = []
    real_timeout = asyncio.timeout

    def accelerated_timeout(seconds):
        deadlines.append(seconds)
        return real_timeout(0.01)

    # Accelerate the timer while keeping real task cancellation and PostgreSQL writes.
    monkeypatch.setattr(
        "notification_worker.worker.asyncio",
        SimpleNamespace(timeout=accelerated_timeout, gather=asyncio.gather),
    )

    async def provider(request):
        if UUID(json.loads(request.content)["notification_id"]) == hung:
            try:
                await asyncio.Event().wait()
            finally:
                clock[0] = NOW + timedelta(seconds=1.7)
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(provider)
    ) as client:
        dispatcher = Dispatcher(
            pool,
            client,
            "https://fixture.supabase.co/functions/v1/dispatch-push",
            "secret",
            "key",
            clock=lambda: clock[0],
        )
        result = await dispatcher.tick()

    assert deadlines == [1.7, 1.7]
    assert result.accepted == 1 and result.failed == 1
    row = await db.fetchrow("SELECT * FROM notifications WHERE id=$1", hung)
    assert row["delivered_at"] is None and row["claimed_at"] is None
    assert row["last_error"] == "TimeoutError"
    assert row["next_attempt_at"] == NOW + timedelta(seconds=2.7)
    assert await db.fetchval(
        "SELECT delivered_at IS NOT NULL FROM notifications WHERE id=$1",
        healthy,
    )
