from datetime import timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest

from scripts.import_rooms import RoomImportError, RoomRow, import_rooms
from tests.harness import NOW, ROOM_ID


def room_row(code="IMPORT-001", **changes):
    return RoomRow(
        code=code,
        name="純測試教室",
        building="純測試館",
        floor=2,
        capacity=40,
        equipment=["白板"],
        latitude=None,
        longitude=None,
        map_x=None,
        map_y=None,
        location_text="僅供本機隔離測試。",
        location_verified=False,
        active=True,
    ).model_copy(update=changes)


async def test_import_is_idempotent_and_retains_existing_maps_and_bookings(
    db, borrower
):
    await db.execute(
        "UPDATE rooms SET map_path='existing-map.webp' WHERE id=$1", ROOM_ID
    )
    reservation_id = uuid4()
    await db.execute(
        """INSERT INTO reservations
        (id,user_id,room_id,starts_at,ends_at,purpose,attendees,mode,status,request_id)
        VALUES ($1,$2,$3,$4,$5,'測試用途',10,'scheduled','approved',$6)""",
        reservation_id,
        UUID(borrower["id"]),
        ROOM_ID,
        NOW + timedelta(days=1),
        NOW + timedelta(days=1, hours=1),
        uuid4(),
    )
    original_booking = dict(
        await db.fetchrow(
            "SELECT * FROM reservations WHERE id=$1", reservation_id
        )
    )
    original_profiles = await db.fetchval("SELECT count(*) FROM profiles")
    rows = [room_row("ENG-201", location_verified=True), room_row()]
    await import_rooms(db, rows)
    first_id = await db.fetchval("SELECT id FROM rooms WHERE code='IMPORT-001'")
    await import_rooms(db, list(reversed(rows)))
    assert await db.fetchval("SELECT count(*) FROM rooms") == 5
    assert (
        await db.fetchval("SELECT id FROM rooms WHERE code='IMPORT-001'")
        == first_id
    )
    updated = await db.fetchrow("SELECT * FROM rooms WHERE code='ENG-201'")
    assert updated["id"] == ROOM_ID
    assert updated["map_path"] == "existing-map.webp"
    assert updated["capacity"] == 40 and updated["location_verified"] is True
    assert (
        await db.fetchval("SELECT count(*) FROM profiles") == original_profiles
    )
    assert (
        dict(
            await db.fetchrow(
                "SELECT * FROM reservations WHERE id=$1", reservation_id
            )
        )
        == original_booking
    )
    assert (
        await db.fetchval("SELECT capacity FROM rooms WHERE code='SCI-102'")
        == 32
    )


async def test_location_verification_and_active_are_explicit_metadata(db):
    await import_rooms(
        db, [room_row("ENG-201", location_verified=True, active=True)]
    )
    await import_rooms(
        db, [room_row("ENG-201", location_verified=False, active=False)]
    )
    assert (
        await db.fetchval(
            "SELECT location_verified FROM rooms WHERE id=$1", ROOM_ID
        )
        is False
    )
    assert (
        await db.fetchval("SELECT active FROM rooms WHERE id=$1", ROOM_ID)
        is False
    )


async def test_late_database_constraint_failure_rolls_back_all_rows(db):
    await db.execute(
        "ALTER TABLE rooms ADD CONSTRAINT import_test_capacity CHECK (capacity<90) NOT VALID"
    )
    before = dict(await db.fetchrow("SELECT * FROM rooms WHERE id=$1", ROOM_ID))
    rows = [room_row("ENG-201", capacity=70), room_row("ZZ-FAIL", capacity=100)]
    with pytest.raises(asyncpg.CheckViolationError):
        await import_rooms(db, rows)
    assert (
        dict(await db.fetchrow("SELECT * FROM rooms WHERE id=$1", ROOM_ID))
        == before
    )
    assert (
        await db.fetchval("SELECT count(*) FROM rooms WHERE code='ZZ-FAIL'")
        == 0
    )


async def test_application_role_cannot_use_owner_import(db, pool):
    async with pool.acquire() as connection:
        assert (
            await connection.fetchval("SELECT current_user") == "ntou_backend"
        )
        with pytest.raises(RoomImportError, match="table owner"):
            await import_rooms(connection, [room_row()])
        assert not await connection.fetchval(
            "SELECT has_table_privilege(current_user,'public.rooms','INSERT')"
        )
        assert not await connection.fetchval(
            "SELECT has_column_privilege(current_user,'public.rooms','capacity','UPDATE')"
        )
    assert await db.fetchval("SELECT count(*) FROM rooms") == 4


async def test_imported_metadata_is_queryable_through_existing_public_api(
    db, api
):
    await import_rooms(
        db, [room_row(), room_row("IMPORT-INACTIVE", active=False)]
    )
    response = await api.get("/api/rooms", params={"building": "純測試館"})
    assert response.status_code == 200
    rooms = response.json()["items"]
    assert len(rooms) == 1 and rooms[0]["code"] == "IMPORT-001"
    interval = {
        "start": "2026-10-13T08:00:00+08:00",
        "end": "2026-10-13T09:00:00+08:00",
    }
    availability = await api.get(
        "/api/rooms/availability", params={**interval, "building": "純測試館"}
    )
    assert availability.status_code == 200
    assert availability.json()["items"][0]["available"] is True
    schedule = await api.get(
        f"/api/rooms/{rooms[0]['id']}/schedule", params=interval
    )
    assert schedule.status_code == 200 and schedule.json()["items"] == []
