from datetime import datetime

import httpx
import pytest
import pytest_asyncio

from tests.harness import (
    NOW,
    FakeSupabase,
    MutableClock,
    add_profile,
    application_pool,
    reset_database,
    settings_for,
    test_database_url,
)


@pytest.fixture
def fixed_now() -> datetime:
    return NOW


@pytest_asyncio.fixture
async def db():
    connection = await reset_database(test_database_url())
    try:
        yield connection
    finally:
        await connection.execute(
            "TRUNCATE audit_logs,notifications,push_subscriptions,violations,reservations,profiles,institutional_roster CASCADE"
        )
        await connection.close()


@pytest.fixture
def auth():
    return FakeSupabase()


@pytest.fixture
def clock():
    return MutableClock()


@pytest_asyncio.fixture
async def borrower(db, auth):
    return await add_profile(db, auth)


@pytest_asyncio.fixture
async def other_borrower(db, auth):
    return await add_profile(db, auth, index=2)


@pytest_asyncio.fixture
async def admin(db, auth):
    return await add_profile(db, auth, index=1001, role="admin")


@pytest_asyncio.fixture
async def pool(db):
    pool = await application_pool(test_database_url())
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture
async def api(pool, auth, clock):
    from app.main import create_app

    app = create_app(
        settings_for(test_database_url()),
        auth_transport=httpx.MockTransport(auth.handle),
        pool=pool,
        clock=clock,
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
