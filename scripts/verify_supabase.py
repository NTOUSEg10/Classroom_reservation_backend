"""Read-only deployment checks, explicitly separate from local HTTP fixtures."""

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit
import httpx


async def main():
    base_url = os.environ["TEST_API_URL"].rstrip("/")
    token = os.environ["TEST_BORROWER_ACCESS_TOKEN"]
    if urlsplit(base_url).scheme != "https":
        raise SystemExit("Deployment acceptance requires HTTPS.")
    start = datetime.now(timezone(timedelta(hours=8))).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    params = {
        "start": (start + timedelta(days=1)).isoformat(),
        "end": (start + timedelta(days=1, hours=2)).isoformat(),
    }
    timings = {}
    async with httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": "Bearer " + token},
        timeout=5,
    ) as client:
        identity = await client.get("/api/auth/identity")
        identity.raise_for_status()
        identity_data = identity.json()
        if identity_data.get("onboarding_required") is not False or not str(
            identity_data.get("email", "")
        ).endswith("@email.ntou.edu.tw"):
            raise RuntimeError(
                "Use a fully onboarded school Google test account."
            )
        for route, budget, query in [
            ("/api/rooms/availability", 2, params),
            ("/api/me/eligibility", 0.5, None),
            ("/api/me", 5, None),
        ]:
            began = perf_counter()
            response = await client.get(route, params=query)
            response.raise_for_status()
            duration = perf_counter() - began
            timings[route] = {
                "elapsed_ms": round(duration * 1000, 2),
                "budget_ms": budget * 1000,
            }
            if duration >= budget:
                raise RuntimeError(
                    "Deployment response exceeded budget: " + route
                )
            if route == "/api/me":
                profile = response.json()
                if profile["role"] != "borrower":
                    raise RuntimeError("Use a dedicated borrower test account.")
        forbidden = await client.get("/api/admin/users")
        if forbidden.status_code != 403:
            raise RuntimeError("Borrower must receive 403 on admin API.")
        disabled = await client.post("/api/auth/login", json={})
        if disabled.status_code != 403:
            raise RuntimeError("Legacy password login must be disabled.")
        config_response = await client.get("/api/config")
        config_response.raise_for_status()
        public_config = config_response.json()
    auth_url = public_config["supabase_url"].rstrip("/")
    if urlsplit(auth_url).scheme != "https":
        raise RuntimeError("Real Supabase acceptance requires HTTPS.")
    async with httpx.AsyncClient(timeout=5) as auth_client:
        user_response = await auth_client.get(
            auth_url + "/auth/v1/user",
            headers={
                "Authorization": "Bearer " + token,
                "apikey": public_config["supabase_publishable_key"],
            },
        )
        user_response.raise_for_status()
        auth_user = user_response.json()
        if (
            auth_user.get("id") != profile.get("id")
            or auth_user.get("app_metadata", {}).get("provider") != "google"
        ):
            raise RuntimeError(
                "Supabase must confirm the same Google test identity."
            )
    output = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "https": True,
        "real_auth": True,
        "google_oauth_identity": True,
        "legacy_password_disabled": True,
        "borrower_admin_403": True,
        "timings": timings,
        "limits": "Read-only smoke only; 100-users, device receipt and TLS reverse proxy require separate staging tests.",
    }
    root = Path(__file__).resolve().parent.parent
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports/supabase-deployment.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )
    print(
        "Read-only Supabase Google deployment checks passed. No identifiers or tokens were logged."
    )


if __name__ == "__main__":
    asyncio.run(main())
