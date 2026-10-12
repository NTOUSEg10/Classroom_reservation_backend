import base64
import hashlib
import json
import re
from datetime import timedelta
from uuid import UUID

import httpx
from fastapi import HTTPException, Request


async def supabase_request(
    request: Request,
    method: str,
    path: str,
    *,
    token: str | None = None,
    service: bool = False,
    **kwargs,
):
    settings = request.app.state.settings
    key = (
        settings.supabase_service_key
        if service
        else settings.supabase_publishable_key
    )
    if not settings.supabase_url or not key:
        raise HTTPException(503, "身分驗證服務尚未設定")
    headers = {"apikey": key}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif not key.startswith("sb_"):
        # Opaque publishable/secret API keys are not session JWTs.
        headers["Authorization"] = f"Bearer {key}"
    headers.update(kwargs.pop("headers", {}))
    try:
        response = await request.app.state.http_client.request(
            method,
            settings.supabase_url.rstrip("/") + path,
            headers=headers,
            **kwargs,
        )
    except httpx.HTTPError:
        raise HTTPException(503, "外部服務暫時無法連線，請稍後重試") from None
    if response.status_code >= 500 or response.status_code == 429:
        raise HTTPException(503, "外部服務暫時無法使用，請稍後重試")
    return response


def response_json(response: httpx.Response):
    try:
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError
        return result
    except ValueError:
        raise HTTPException(503, "外部服務回應異常") from None


async def campus_identity(request: Request):
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "請先登入")
    response = await supabase_request(
        request, "GET", "/auth/v1/user", token=token
    )
    if response.status_code != 200:
        raise HTTPException(401, "登入已失效，請重新登入")
    auth_user = response_json(response)
    try:
        if not isinstance(auth_user.get("id"), str):
            raise ValueError
        user_id = UUID(auth_user["id"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, "登入憑證無效") from None
    email = auth_user.get("email")
    app_metadata = auth_user.get("app_metadata")
    identities = auth_user.get("identities")
    if not isinstance(email, str):
        raise HTTPException(403, "請使用學校 Google 帳號登入")
    email = email.lower()
    providers = (
        app_metadata.get("providers")
        if isinstance(app_metadata, dict)
        else None
    )
    only_google_providers = (
        isinstance(providers, list)
        and bool(providers)
        and all(
            isinstance(provider, str) and provider == "google"
            for provider in providers
        )
    )
    only_google_identities = (
        isinstance(identities, list)
        and bool(identities)
        and all(
            isinstance(identity, dict) and identity.get("provider") == "google"
            for identity in identities
        )
    )
    google_verified = isinstance(identities, list) and any(
        isinstance(identity, dict)
        and identity.get("provider") == "google"
        and isinstance(identity.get("identity_data"), dict)
        and identity["identity_data"].get("email_verified") is True
        and isinstance(identity["identity_data"].get("email"), str)
        and identity["identity_data"]["email"].lower() == email
        for identity in identities
    )
    if (
        auth_user.get("is_anonymous") is not False
        or not auth_user.get("email_confirmed_at")
        or not re.fullmatch(r"[^@\s]+@email\.ntou\.edu\.tw", email)
        or not isinstance(app_metadata, dict)
        or app_metadata.get("provider") != "google"
        or not only_google_providers
        or not only_google_identities
        or not google_verified
    ):
        raise HTTPException(403, "請使用已驗證的學校 Google 帳號登入")
    # Supabase validated this exact Bearer above; only then read its session method.
    try:
        _, encoded, _ = token.split(".")
        claims = json.loads(
            base64.b64decode(
                encoded + "=" * ((-len(encoded)) % 4),
                altchars=b"-_",
                validate=True,
            )
        )
        if (
            not isinstance(claims, dict)
            or not isinstance(claims.get("sub"), str)
            or UUID(claims["sub"]) != user_id
        ):
            raise ValueError
        amr = claims.get("amr")
        if not isinstance(amr, list) or not any(
            isinstance(entry, dict) and entry.get("method") == "oauth"
            for entry in amr
        ):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise HTTPException(403, "請重新使用學校 Google 帳號登入") from None
    return {"id": user_id, "email": email, "auth_user": auth_user}


async def current_user(request: Request):
    identity = await campus_identity(request)
    async with request.app.state.pool.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT * FROM profiles WHERE id=$1", identity["id"]
        )
    if not profile:
        raise HTTPException(403, "請先完成基本資料")
    if profile["email"] != identity["email"]:
        raise HTTPException(403, "校園帳號資料不符，請洽管理員")
    return {"profile": dict(profile), "auth_user": identity["auth_user"]}


async def current_admin(request: Request):
    user = await current_user(request)
    if user["profile"]["role"] != "admin":
        raise HTTPException(403, "此操作僅限管理員")
    return user


async def rate_limit(request: Request, email: str):
    settings = request.app.state.settings
    now = request.app.state.clock()
    ip = request.client.host if request.client else "unknown"
    # Database counters survive worker switching; proxy headers are never trusted here.
    async with request.app.state.pool.acquire() as conn:
        if request.app.state.rate_cleanup_at <= now:
            request.app.state.rate_cleanup_at = now + timedelta(minutes=5)
            await conn.execute(
                """DELETE FROM auth_rate_limits WHERE key_hash IN
              (SELECT key_hash FROM auth_rate_limits WHERE expires_at<$1 LIMIT 1000)""",
                now - timedelta(days=1),
            )
        for value in (f"ip:{ip}", f"account:{email.lower()}"):
            key = hashlib.sha256(value.encode()).hexdigest()
            hits = await conn.fetchval(
                """INSERT INTO auth_rate_limits(key_hash,hits,expires_at) VALUES($1,1,$2)
              ON CONFLICT(key_hash) DO UPDATE SET
                hits=CASE WHEN auth_rate_limits.expires_at<=$3 THEN 1 ELSE auth_rate_limits.hits+1 END,
                expires_at=CASE WHEN auth_rate_limits.expires_at<=$3 THEN $2 ELSE auth_rate_limits.expires_at END
              RETURNING hits""",
                key,
                now + timedelta(seconds=settings.auth_rate_window),
                now,
            )
            limit = (
                settings.auth_ip_rate_limit
                if value.startswith("ip:")
                else settings.auth_rate_limit
            )
            if hits > limit:
                raise HTTPException(
                    429,
                    "嘗試次數過多，請稍後再試",
                    headers={"Retry-After": str(settings.auth_rate_window)},
                )
