"""100 distinct users over real TCP; run after tests.harness:load_app starts."""

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx

from tests.harness import ROOT, ROOM_ID, booking_payload
from tests.metrics import latency_summary, write_report


async def measure(clients, call, expected_status, threshold):
    gate = asyncio.Event()
    dispatches = []

    async def one(index, client):
        await gate.wait()
        started = time.perf_counter()
        dispatches.append(started)
        response = await call(index, client)
        elapsed = time.perf_counter() - started
        if response.status_code != expected_status:
            raise AssertionError(
                f"Request {index}: expected {expected_status}, received {response.status_code}: {response.text[:200]}"
            )
        return elapsed

    jobs = [
        asyncio.create_task(one(index, client))
        for index, client in enumerate(clients)
    ]
    await asyncio.sleep(0)
    gate.set()
    durations = await asyncio.gather(*jobs)
    result = {
        **latency_summary(durations, [expected_status] * len(durations)),
        "sla_ms": threshold * 1000,
        "passed": max(durations) < threshold,
        "dispatch_spread_ms": round(
            (max(dispatches) - min(dispatches)) * 1000, 3
        ),
    }
    return result


async def run(base_url, sessions_file):
    fixtures = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert fixtures["test_only"] is True, (
        "Only test-only sessions are permitted"
    )
    sessions = fixtures["sessions"]
    clients = [
        httpx.AsyncClient(base_url=base_url, timeout=10) for _ in range(100)
    ]
    try:
        # Out-of-band test sessions are registered in this factory's Auth fixture.
        for index, client in enumerate(clients, start=1):
            client.headers["Authorization"] = (
                f"Bearer {sessions[str(index)]['access_token']}"
            )
        params = {
            "start": "2026-10-13T10:00:00+08:00",
            "end": "2026-10-13T12:00:00+08:00",
        }
        measurements = {
            "availability": await measure(
                clients,
                lambda _, client: client.get(
                    "/api/rooms/availability", params=params
                ),
                200,
                2,
            ),
            "weekly_schedule": await measure(
                clients,
                lambda _, client: client.get(
                    f"/api/rooms/{ROOM_ID}/schedule",
                    params={
                        "start": "2026-10-13T00:00:00+08:00",
                        "end": "2026-10-20T00:00:00+08:00",
                    },
                ),
                200,
                2,
            ),
            "applications": await measure(
                clients,
                lambda _, client: client.post(
                    "/api/reservations", json=booking_payload()
                ),
                201,
                2,
            ),
            "eligibility": await measure(
                clients,
                lambda _, client: client.get("/api/me/eligibility"),
                200,
                0.5,
            ),
            "page_history": await measure(
                clients,
                lambda _, client: client.get("/api/reservations"),
                200,
                5,
            ),
            "permission_refresh": await measure(
                clients, lambda _, client: client.get("/api/me"), 200, 5
            ),
        }
        clients[-1].headers["Authorization"] = (
            f"Bearer {sessions['101']['access_token']}"
        )
        measurements["admin_navigation_under_load"] = await measure(
            clients,
            lambda index, client: client.get(
                "/api/admin/users" if index == 99 else "/api/me"
            ),
            200,
            5,
        )
        output = write_report(
            "upgrade-live-http-100-users",
            {
                "users": 100,
                "transport": "real localhost TCP HTTP + PostgreSQL",
                "auth": "test-only Google sessions + get-user MockTransport; remote OAuth remains deployment gate",
                "seed_scale": {
                    "profiles": 101,
                    "rooms": 4,
                    "pending_reservations": 100,
                },
                "measurements": measurements,
            },
        )
        print(
            json.dumps(
                {"report": str(output), "measurements": measurements},
                ensure_ascii=False,
                indent=2,
            )
        )
        assert all(value["passed"] for value in measurements.values()), (
            "One or more local SLA thresholds failed"
        )
    finally:
        await asyncio.gather(*[client.aclose() for client in clients])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument(
        "--sessions-file",
        type=Path,
        default=ROOT / ".local" / "ntou_load-sessions.json",
    )
    args = parser.parse_args()
    asyncio.run(run(args.base_url, args.sessions_file))
