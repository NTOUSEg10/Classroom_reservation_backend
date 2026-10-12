import asyncio
import ssl
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID, uuid4

import asyncpg
import httpx
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .auth import (
    campus_identity,
    current_admin,
    current_user,
    rate_limit,
    response_json,
    supabase_request,
)
from .config import Settings
from .database import (
    RESERVATION_SELECT,
    audit,
    notify,
    points_for,
    reservation_detail,
    transaction,
)
from .models import (
    PushDelete,
    PushSubscription,
    Register,
    ReservationCreate,
    Status,
    StatusChange,
    UserChange,
    Verify,
    ViolationCreate,
    ViolationResolve,
)
from .rules import (
    ensure_eligible,
    validate_booking,
    validate_interval,
    validate_transition,
)


UTC = timezone.utc
NOTIFICATION_COLUMNS = "id,user_id,reservation_id,title,body,read_at,created_at"


def create_app(
    settings: Settings | None = None,
    *,
    auth_transport: httpx.AsyncBaseTransport | None = None,
    pool: asyncpg.Pool | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or Settings()
    clock = clock or (lambda: datetime.now(UTC))

    @asynccontextmanager
    async def lifespan(app):
        owned_pool = pool is None
        if pool is None and settings.database_url:

            async def setup_connection(connection):
                await connection.execute("SET ROLE ntou_backend")

            app.state.pool = await asyncpg.create_pool(
                dsn=settings.database_url,
                min_size=settings.pool_min_size,
                max_size=settings.pool_max_size,
                ssl=ssl.create_default_context()
                if settings.environment == "production"
                else None,
                command_timeout=2,
                server_settings={
                    "search_path": "public",
                    "statement_timeout": "1800",
                },
                setup=setup_connection,
            )
        if settings.environment == "production" and app.state.pool:
            async with app.state.pool.acquire() as conn:
                privileged = await conn.fetchval(
                    "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=session_user"
                )
                if privileged:
                    if owned_pool:
                        await app.state.pool.close()
                    raise RuntimeError(
                        "Production database login must not be superuser or bypass RLS"
                    )
        app.state.http_client = httpx.AsyncClient(
            transport=auth_transport,
            timeout=1.5,
            follow_redirects=False,
            limits=httpx.Limits(
                max_connections=100, max_keepalive_connections=20
            ),
        )
        task = None
        if (
            settings.push_dispatch_enabled
            and settings.enable_notification_worker
            and app.state.pool
        ):
            from notification_worker.worker import run_worker

            task = asyncio.create_task(
                run_worker(
                    app.state.pool,
                    settings.supabase_url.rstrip("/")
                    + "/functions/v1/dispatch-push",
                    settings.dispatch_secret,
                    settings.supabase_service_key,
                    clock=clock,
                )
            )
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await app.state.http_client.aclose()
            if owned_pool and app.state.pool:
                await app.state.pool.close()

    app = FastAPI(
        title="海大教室借用平台",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )
    app.state.settings, app.state.pool, app.state.clock = settings, pool, clock
    app.state.map_cache = {}
    app.state.rate_cleanup_at = clock()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        local_health = (
            request.url.path == "/api/health"
            and request.client
            and request.client.host in {"127.0.0.1", "::1"}
        )
        if (
            settings.environment == "production"
            and request.url.scheme != "https"
            and not local_health
        ):
            return JSONResponse(
                {"detail": "請使用 HTTPS 連線"}, status_code=400
            )
        if app.state.pool is None and request.url.path not in {
            "/api/config",
            "/api/health",
            "/api/docs",
            "/openapi.json",
            "/api/auth/login",
        }:
            return JSONResponse(
                {"detail": "資料庫服務尚未設定"}, status_code=503
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        if settings.environment == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, exc):
        # Do not echo user input: validation errors can otherwise include passwords.
        fields = ", ".join(
            ".".join(str(part) for part in err["loc"] if part != "body")
            for err in exc.errors()
        )
        return JSONResponse(
            {"detail": f"輸入格式有誤，請檢查：{fields}"}, status_code=422
        )

    @app.exception_handler(asyncpg.ExclusionViolationError)
    async def overlap_handler(request, exc):
        return JSONResponse(
            {"detail": "此教室時段已被核准借用"}, status_code=409
        )

    @app.exception_handler(asyncpg.UniqueViolationError)
    async def duplicate_handler(request, exc):
        return JSONResponse(
            {"detail": "資料已存在，請重新確認"}, status_code=409
        )

    @app.exception_handler(asyncpg.PostgresError)
    async def database_handler(request, exc):
        code = (
            409
            if isinstance(
                exc,
                (asyncpg.LockNotAvailableError, asyncpg.DeadlockDetectedError),
            )
            else 503
        )
        return JSONResponse(
            {
                "detail": "資料正在更新，請稍後重試"
                if code == 409
                else "資料庫暫時無法使用，請稍後重試"
            },
            status_code=code,
        )

    @app.exception_handler(asyncio.TimeoutError)
    async def timeout_handler(request, exc):
        return JSONResponse({"detail": "服務忙碌，請稍後重試"}, status_code=503)

    @app.get("/api/health")
    async def health():
        if not app.state.pool:
            raise HTTPException(503, "資料庫尚未連線")
        async with app.state.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok"}

    @app.get("/api/config")
    async def config():
        return {
            "supabase_url": settings.supabase_url,
            "supabase_publishable_key": settings.supabase_publishable_key,
            "vapid_public_key": settings.vapid_public_key,
            "demo_data": settings.demo_data,
        }

    @app.get("/api/auth/identity")
    async def identity(identity=Depends(campus_identity)):
        async with app.state.pool.acquire() as conn:
            profile = await conn.fetchrow(
                "SELECT * FROM profiles WHERE id=$1", identity["id"]
            )
        if profile and profile["email"] != identity["email"]:
            raise HTTPException(403, "校園帳號資料不符，請洽管理員")
        return {
            "email": identity["email"],
            "onboarding_required": profile is None,
            "profile": dict(profile) if profile else None,
        }

    @app.post("/api/auth/register", status_code=201)
    async def register(
        data: Register, request: Request, identity=Depends(campus_identity)
    ):
        await rate_limit(request, identity["email"])
        async with transaction(app.state.pool) as conn:
            # A new identity has no profile row to lock yet; serialize its safe retries.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                "ntou:onboarding:" + str(identity["id"]),
            )
            profile = await conn.fetchrow(
                "SELECT * FROM profiles WHERE id=$1 FOR UPDATE", identity["id"]
            )
            if profile:
                if profile["email"] != identity["email"]:
                    raise HTTPException(403, "校園帳號資料不符，請洽管理員")
                return dict(profile)
            result = await conn.fetchrow(
                """INSERT INTO profiles(id,name,email,phone,department,institutional_id,verified,created_at)
              VALUES($1,$2,$3,$4,$5,$6,true,$7) RETURNING *""",
                identity["id"],
                data.name,
                identity["email"],
                data.phone,
                data.department,
                data.institutional_id,
                clock(),
            )
            await audit(
                conn,
                identity["id"],
                "register",
                clock(),
                target_user_id=identity["id"],
            )
        return dict(result)

    @app.post("/api/auth/login")
    async def login():
        raise HTTPException(403, "請使用學校 Google 帳號登入")

    @app.get("/api/me")
    async def me(user=Depends(current_user)):
        return user["profile"]

    @app.post("/api/me/verify")
    async def verify(data: Verify, user=Depends(current_user)):
        profile = user["profile"]
        async with transaction(app.state.pool) as conn:
            profile = await conn.fetchrow(
                "SELECT * FROM profiles WHERE id=$1 FOR UPDATE", profile["id"]
            )
            if not profile:
                raise HTTPException(403, "帳號已移除，請洽管理員")
            if data.institutional_id != profile["institutional_id"]:
                raise HTTPException(403, "證號與本人資料不符")
            result = await conn.fetchrow(
                "UPDATE profiles SET verified=true WHERE id=$1 RETURNING *",
                profile["id"],
            )
            await audit(
                conn,
                profile["id"],
                "verify_identity",
                clock(),
                target_user_id=profile["id"],
            )
        return dict(result)

    @app.get("/api/me/eligibility")
    async def eligibility(user=Depends(current_user)):
        profile = user["profile"]
        async with app.state.pool.acquire() as conn:
            points = await points_for(conn, profile["id"])
        eligible = (
            profile["verified"] and not profile["suspended"] and points < 3
        )
        reason = (
            "可提出借用申請"
            if eligible
            else (
                "請先完成校園身分驗證"
                if not profile["verified"]
                else "帳號停權或違規點數達上限"
            )
        )
        return {
            "eligible": eligible,
            "verified": profile["verified"],
            "suspended": profile["suspended"],
            "violation_points": points,
            "reason": reason,
        }

    async def attach_map(room, request):
        room = dict(room)
        room["map_url"] = None
        path = room.get("map_path")
        if path:
            cached = app.state.map_cache.get(path)
            if cached and cached[0] > clock():
                room["map_url"] = cached[1]
            else:
                with suppress(HTTPException):
                    response = await supabase_request(
                        request,
                        "POST",
                        f"/storage/v1/object/sign/room-maps/{path}",
                        service=True,
                        json={"expiresIn": 300},
                    )
                    if response.status_code == 200:
                        signed = response_json(response).get(
                            "signedURL"
                        ) or response_json(response).get("signedUrl")
                        if signed and signed.startswith("/object/sign/"):
                            signed = (
                                settings.supabase_url.rstrip("/")
                                + "/storage/v1"
                                + signed
                            )
                        elif signed and signed.startswith(
                            "/storage/v1/object/sign/"
                        ):
                            signed = settings.supabase_url.rstrip("/") + signed
                        if signed and signed.startswith(
                            settings.supabase_url.rstrip("/") + "/storage/v1/"
                        ):
                            room["map_url"] = signed
                            app.state.map_cache[path] = (
                                clock() + timedelta(seconds=240),
                                signed,
                            )
        return room

    @app.get("/api/rooms")
    async def rooms(
        request: Request,
        building: str | None = None,
        capacity: int = Query(0, ge=0, le=1000),
        equipment: list[str] | None = Query(default=None),
    ):
        async with app.state.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM rooms WHERE active AND ($1::text IS NULL OR building=$1)
              AND capacity>=$2 AND ($3::text[] IS NULL OR equipment @> $3) ORDER BY building,code""",
                building,
                capacity,
                equipment,
            )
        return {
            "items": await asyncio.gather(
                *(attach_map(r, request) for r in rows)
            )
        }

    @app.get("/api/rooms/availability")
    async def availability(
        request: Request,
        start: datetime,
        end: datetime,
        building: str | None = None,
        capacity: int = Query(0, ge=0, le=1000),
        equipment: list[str] | None = Query(default=None),
    ):
        validate_interval(start, end)
        async with app.state.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT rooms.*,NOT EXISTS(SELECT 1 FROM reservations r WHERE r.room_id=rooms.id
                AND r.status IN ('approved','checked_out') AND r.starts_at<$2 AND r.ends_at>$1) AS available
              FROM rooms WHERE active AND ($3::text IS NULL OR building=$3) AND capacity>=$4
              AND ($5::text[] IS NULL OR equipment @> $5) ORDER BY building,code""",
                start,
                end,
                building,
                capacity,
                equipment,
            )
        return {
            "items": await asyncio.gather(
                *(attach_map(r, request) for r in rows)
            )
        }

    @app.get("/api/rooms/{room_id}/schedule")
    async def schedule(room_id: UUID, start: datetime, end: datetime):
        validate_interval(start, end)
        async with app.state.pool.acquire() as conn:
            if not await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM rooms WHERE id=$1 AND active)",
                room_id,
            ):
                raise HTTPException(404, "找不到教室")
            rows = await conn.fetch(
                """SELECT id,starts_at,ends_at,status FROM reservations
              WHERE room_id=$1 AND starts_at<$3 AND ends_at>$2 AND status IN ('approved','checked_out') ORDER BY starts_at""",
                room_id,
                start,
                end,
            )
        return {"items": [dict(r) for r in rows]}

    @app.post("/api/reservations", status_code=201)
    async def create_reservation(
        data: ReservationCreate, user=Depends(current_user)
    ):
        now = clock()
        async with transaction(app.state.pool) as conn:
            profile = await conn.fetchrow(
                "SELECT * FROM profiles WHERE id=$1 FOR UPDATE",
                user["profile"]["id"],
            )
            if not profile:
                raise HTTPException(403, "帳號已移除，請洽管理員")
            existing = await conn.fetchrow(
                "SELECT * FROM reservations WHERE user_id=$1 AND request_id=$2",
                profile["id"],
                data.request_id,
            )
            if existing:
                if any(
                    existing[field] != getattr(data, field)
                    for field in (
                        "room_id",
                        "starts_at",
                        "ends_at",
                        "purpose",
                        "attendees",
                        "mode",
                    )
                ):
                    raise HTTPException(409, "此 request_id 已用於不同申請")
                return await reservation_detail(conn, existing["id"])
            ensure_eligible(profile, await points_for(conn, profile["id"]))
            validate_booking(data, now)
            room = await conn.fetchrow(
                "SELECT * FROM rooms WHERE id=$1 FOR SHARE", data.room_id
            )
            if not room or not room["active"]:
                raise HTTPException(404, "教室不存在或暫停借用")
            if data.attendees > room["capacity"]:
                raise HTTPException(422, "借用人數超過教室容量")
            reservation_id = await conn.fetchval(
                """INSERT INTO reservations(user_id,room_id,starts_at,ends_at,purpose,attendees,mode,request_id,created_at,updated_at)
              VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$9) RETURNING id""",
                profile["id"],
                data.room_id,
                data.starts_at,
                data.ends_at,
                data.purpose,
                data.attendees,
                data.mode,
                data.request_id,
                now,
            )
            await audit(
                conn,
                profile["id"],
                "reservation_created",
                now,
                reservation_id=reservation_id,
                new_status="pending",
            )
            await notify(
                conn,
                profile["id"],
                "借用申請已送出",
                f"{room['name']} 申請等待管理員審核。",
                now,
                reservation_id,
            )
            return await reservation_detail(conn, reservation_id)

    @app.get("/api/reservations")
    async def reservations(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        status: Status | None = None,
        user=Depends(current_user),
    ):
        owner = (
            None
            if user["profile"]["role"] == "admin"
            else user["profile"]["id"]
        )
        where = " WHERE ($1::uuid IS NULL OR r.user_id=$1) AND ($2::text IS NULL OR r.status=$2)"
        async with app.state.pool.acquire() as conn:
            async with conn.transaction(
                isolation="repeatable_read", readonly=True
            ):
                total = await conn.fetchval(
                    "SELECT count(*) FROM reservations r" + where, owner, status
                )
                rows = await conn.fetch(
                    RESERVATION_SELECT
                    + where
                    + " ORDER BY r.created_at DESC,r.id LIMIT $3 OFFSET $4",
                    owner,
                    status,
                    limit,
                    offset,
                )
        return {"items": [dict(r) for r in rows], "total": total}

    @app.patch("/api/reservations/{reservation_id}/status")
    async def change_status(
        reservation_id: UUID, data: StatusChange, user=Depends(current_user)
    ):
        actor = user["profile"]
        if actor["role"] != "admin" and data.status != "cancelled":
            raise HTTPException(403, "此操作僅限管理員")
        now = clock()
        async with transaction(app.state.pool) as conn:
            row = await conn.fetchrow(
                "SELECT * FROM reservations WHERE id=$1 FOR UPDATE",
                reservation_id,
            )
            if not row:
                raise HTTPException(404, "找不到借用申請")
            if actor["role"] != "admin" and row["user_id"] != actor["id"]:
                raise HTTPException(403, "只能取消自己的申請")
            validate_transition(row["status"], data.status, data.reason)
            profile = await conn.fetchrow(
                "SELECT * FROM profiles WHERE id=$1 FOR UPDATE", row["user_id"]
            )
            room = await conn.fetchrow(
                "SELECT * FROM rooms WHERE id=$1 FOR UPDATE", row["room_id"]
            )
            if data.status == "approved":
                ensure_eligible(profile, await points_for(conn, profile["id"]))
                if not room["active"]:
                    raise HTTPException(409, "教室暫停借用")
                if row["ends_at"] <= now:
                    raise HTTPException(409, "借用時段已結束，無法核准")
                if await conn.fetchval(
                    """SELECT EXISTS(SELECT 1 FROM reservations WHERE room_id=$1 AND id<>$2
                  AND status IN ('approved','checked_out') AND starts_at<$4 AND ends_at>$3)""",
                    row["room_id"],
                    row["id"],
                    row["starts_at"],
                    row["ends_at"],
                ):
                    raise HTTPException(409, "此教室時段已被核准借用")
            if data.status == "checked_out" and (
                now < row["starts_at"] - timedelta(minutes=15)
                or now >= row["ends_at"]
            ):
                raise HTTPException(
                    409, "鑰匙交付須於借用開始前 15 分鐘至結束前"
                )
            await conn.execute(
                """UPDATE reservations SET status=$2,updated_at=$3,
              decision_reason=CASE WHEN $2 IN ('approved','rejected','cancelled') THEN $4 ELSE decision_reason END,
              reviewed_by=CASE WHEN $2 IN ('approved','rejected') THEN $5 ELSE reviewed_by END,
              key_handed_at=CASE WHEN $2='checked_out' THEN $3 ELSE key_handed_at END,
              key_handed_by=CASE WHEN $2='checked_out' THEN $5 ELSE key_handed_by END,
              key_returned_at=CASE WHEN $2='completed' THEN $3 ELSE key_returned_at END,
              key_returned_by=CASE WHEN $2='completed' THEN $5 ELSE key_returned_by END WHERE id=$1""",
                reservation_id,
                data.status,
                now,
                data.reason,
                actor["id"],
            )
            await audit(
                conn,
                actor["id"],
                "reservation_status_changed",
                now,
                reservation_id=reservation_id,
                target_user_id=row["user_id"],
                old_status=row["status"],
                new_status=data.status,
            )
            labels = {
                "approved": "已核准",
                "rejected": "已拒絕",
                "cancelled": "已取消",
                "checked_out": "已交付鑰匙",
                "completed": "已歸還鑰匙",
            }
            await notify(
                conn,
                row["user_id"],
                "借用狀態更新",
                f"{room['name']}：{labels[data.status]}"
                + (f"。原因：{data.reason}" if data.reason else ""),
                now,
                reservation_id,
            )
            return await reservation_detail(conn, reservation_id)

    @app.get("/api/admin/users")
    async def admin_users(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        user=Depends(current_admin),
    ):
        async with app.state.pool.acquire() as conn:
            total = await conn.fetchval("SELECT count(*) FROM profiles")
            rows = await conn.fetch(
                "SELECT * FROM profiles ORDER BY created_at DESC,id LIMIT $1 OFFSET $2",
                limit,
                offset,
            )
        return {"items": [dict(r) for r in rows], "total": total}

    @app.patch("/api/admin/users/{user_id}")
    async def change_user(
        user_id: UUID, data: UserChange, user=Depends(current_admin)
    ):
        now = clock()
        async with transaction(app.state.pool) as conn:
            profile = await conn.fetchrow(
                "SELECT * FROM profiles WHERE id=$1 FOR UPDATE", user_id
            )
            if not profile:
                raise HTTPException(404, "找不到帳號")
            if not data.suspended and await points_for(conn, user_id) >= 3:
                raise HTTPException(
                    409, "請先結案違規，使有效違規點數低於 3 點"
                )
            result = await conn.fetchrow(
                "UPDATE profiles SET suspended=$2 WHERE id=$1 RETURNING *",
                user_id,
                data.suspended,
            )
            await audit(
                conn,
                user["profile"]["id"],
                "user_suspended" if data.suspended else "user_restored",
                now,
                target_user_id=user_id,
            )
            await notify(
                conn,
                user_id,
                "借用資格更新",
                "帳號已停權，請洽管理員。"
                if data.suspended
                else "帳號借用資格已恢復。",
                now,
            )
        return dict(result)

    @app.post("/api/admin/violations", status_code=201)
    async def create_violation(
        data: ViolationCreate, user=Depends(current_admin)
    ):
        now = clock()
        async with transaction(app.state.pool) as conn:
            # Global ordering for linked operations: reservation, profile, room.
            if data.reservation_id:
                row = await conn.fetchrow(
                    "SELECT user_id FROM reservations WHERE id=$1 FOR UPDATE",
                    data.reservation_id,
                )
                if not row or row["user_id"] != data.user_id:
                    raise HTTPException(422, "違規借用紀錄與借用人不符")
            if not await conn.fetchrow(
                "SELECT id FROM profiles WHERE id=$1 FOR UPDATE", data.user_id
            ):
                raise HTTPException(404, "找不到帳號")
            result = await conn.fetchrow(
                """INSERT INTO violations(user_id,reservation_id,points,reason,created_by,created_at)
              VALUES($1,$2,$3,$4,$5,$6) RETURNING *""",
                data.user_id,
                data.reservation_id,
                data.points,
                data.reason,
                user["profile"]["id"],
                now,
            )
            if await points_for(conn, data.user_id) >= 3:
                await conn.execute(
                    "UPDATE profiles SET suspended=true WHERE id=$1",
                    data.user_id,
                )
            await audit(
                conn,
                user["profile"]["id"],
                "violation_created",
                now,
                target_user_id=data.user_id,
                reservation_id=data.reservation_id,
            )
            await notify(
                conn,
                data.user_id,
                "違規紀錄更新",
                f"新增 {data.points} 點違規：{data.reason}。達 3 點將停止借用資格。",
                now,
                data.reservation_id,
            )
        return dict(result)

    @app.patch("/api/admin/violations/{violation_id}")
    async def resolve_violation(
        violation_id: UUID, data: ViolationResolve, user=Depends(current_admin)
    ):
        async with transaction(app.state.pool) as conn:
            # Read immutable owner before locking; every qualification change locks profile first.
            owner = await conn.fetchval(
                "SELECT user_id FROM violations WHERE id=$1", violation_id
            )
            if not owner:
                raise HTTPException(404, "找不到違規紀錄")
            await conn.fetchrow(
                "SELECT id FROM profiles WHERE id=$1 FOR UPDATE", owner
            )
            result = await conn.fetchrow(
                "UPDATE violations SET resolved=true WHERE id=$1 AND NOT resolved RETURNING *",
                violation_id,
            )
            if not result:
                raise HTTPException(409, "違規紀錄已結案")
            await audit(
                conn,
                user["profile"]["id"],
                "violation_resolved",
                clock(),
                target_user_id=owner,
            )
            await notify(
                conn,
                owner,
                "違規紀錄已結案",
                "違規已結案；停權帳號仍須由管理員恢復。",
                clock(),
                result["reservation_id"],
            )
        return dict(result)

    @app.get("/api/admin/violations")
    async def violations(
        user_id: UUID | None = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        user=Depends(current_admin),
    ):
        async with app.state.pool.acquire() as conn:
            total = await conn.fetchval(
                "SELECT count(*) FROM violations WHERE ($1::uuid IS NULL OR user_id=$1)",
                user_id,
            )
            rows = await conn.fetch(
                """SELECT v.*,p.name AS user_name,p.institutional_id FROM violations v
              JOIN profiles p ON p.id=v.user_id WHERE ($1::uuid IS NULL OR v.user_id=$1)
              ORDER BY v.created_at DESC,v.id LIMIT $2 OFFSET $3""",
                user_id,
                limit,
                offset,
            )
        return {"items": [dict(r) for r in rows], "total": total}

    @app.get("/api/notifications")
    async def notifications(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        user=Depends(current_user),
    ):
        async with app.state.pool.acquire() as conn:
            total = await conn.fetchval(
                "SELECT count(*) FROM notifications WHERE user_id=$1",
                user["profile"]["id"],
            )
            rows = await conn.fetch(
                f"SELECT {NOTIFICATION_COLUMNS} FROM notifications WHERE user_id=$1 ORDER BY created_at DESC,id LIMIT $2 OFFSET $3",
                user["profile"]["id"],
                limit,
                offset,
            )
        return {"items": [dict(r) for r in rows], "total": total}

    @app.patch("/api/notifications/{notification_id}/read")
    async def read_notification(
        notification_id: UUID, user=Depends(current_user)
    ):
        async with app.state.pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE notifications SET read_at=COALESCE(read_at,$3) WHERE id=$1 AND user_id=$2 RETURNING {NOTIFICATION_COLUMNS}",
                notification_id,
                user["profile"]["id"],
                clock(),
            )
        if not row:
            raise HTTPException(404, "找不到通知")
        return dict(row)

    @app.post("/api/push-subscriptions", status_code=201)
    async def push_subscription(
        data: PushSubscription, user=Depends(current_user)
    ):
        async with transaction(app.state.pool) as conn:
            existing = await conn.fetchrow(
                "SELECT user_id FROM push_subscriptions WHERE endpoint=$1",
                data.endpoint,
            )
            if existing and existing["user_id"] != user["profile"]["id"]:
                raise HTTPException(409, "此裝置已屬於其他帳號，請先移除訂閱")
            await conn.execute(
                "DELETE FROM push_subscriptions WHERE endpoint=$1 AND user_id=$2",
                data.endpoint,
                user["profile"]["id"],
            )
            row = await conn.fetchrow(
                """INSERT INTO push_subscriptions(user_id,endpoint,p256dh,auth,created_at)
              VALUES($1,$2,$3,$4,$5) RETURNING id""",
                user["profile"]["id"],
                data.endpoint,
                data.keys.p256dh,
                data.keys.auth,
                clock(),
            )
        return {"id": row["id"]}

    @app.delete("/api/push-subscriptions", status_code=204)
    async def delete_subscription(data: PushDelete, user=Depends(current_user)):
        async with app.state.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM push_subscriptions WHERE endpoint=$1 AND user_id=$2",
                data.endpoint,
                user["profile"]["id"],
            )
        return Response(status_code=204)

    @app.post("/api/admin/rooms/{room_id}/map")
    async def upload_map(
        room_id: UUID,
        file: UploadFile,
        request: Request,
        user=Depends(current_admin),
    ):
        content = await file.read(2097153)
        await file.close()
        is_png = file.content_type == "image/png" and content.startswith(
            b"\x89PNG\r\n\x1a\n"
        )
        is_webp = (
            file.content_type == "image/webp"
            and content.startswith(b"RIFF")
            and content[8:12] == b"WEBP"
        )
        if len(content) > 2097152 or not (is_png or is_webp):
            raise HTTPException(
                422, "圖檔僅接受有效 PNG/WebP 且大小不得超過 2MB"
            )
        async with app.state.pool.acquire() as conn:
            if not await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM rooms WHERE id=$1)", room_id
            ):
                raise HTTPException(404, "找不到教室")
        path = f"{room_id}/{uuid4()}.{'png' if is_png else 'webp'}"
        response = await supabase_request(
            request,
            "POST",
            f"/storage/v1/object/room-maps/{path}",
            service=True,
            content=content,
            headers={"Content-Type": file.content_type},
        )
        if response.status_code not in {200, 201}:
            raise HTTPException(503, "圖資上傳失敗，請稍後重試")
        async with transaction(app.state.pool) as conn:
            room = await conn.fetchrow(
                "UPDATE rooms SET map_path=$2 WHERE id=$1 RETURNING *",
                room_id,
                path,
            )
            await audit(
                conn, user["profile"]["id"], "room_map_uploaded", clock()
            )
        return await attach_map(room, request)

    return app


app = create_app()
