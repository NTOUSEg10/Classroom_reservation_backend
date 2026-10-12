"""Validate a school-confirmed room CSV; write only with explicit --apply."""

import argparse
import asyncio
import csv
import io
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import asyncpg
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.config import Settings, database_ssl_context

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
HEADERS = (
    "code",
    "name",
    "building",
    "floor",
    "capacity",
    "equipment",
    "latitude",
    "longitude",
    "map_x",
    "map_y",
    "location_text",
    "location_verified",
    "active",
)


class RoomImportError(ValueError):
    pass


class RoomRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
    name: str = Field(min_length=1, max_length=100)
    building: str = Field(min_length=1, max_length=100)
    floor: int = Field(ge=-20, le=100)
    capacity: int = Field(ge=1, le=1000)
    equipment: list[str] = Field(max_length=20)
    latitude: float | None = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(ge=-180, le=180, allow_inf_nan=False)
    map_x: float | None = Field(ge=0, le=100, allow_inf_nan=False)
    map_y: float | None = Field(ge=0, le=100, allow_inf_nan=False)
    location_text: str = Field(min_length=1, max_length=1000)
    location_verified: bool
    active: bool

    @field_validator("equipment")
    @classmethod
    def valid_equipment(cls, value):
        if len(set(value)) != len(value) or any(
            not item or len(item) > 80 for item in value
        ):
            raise ValueError("Invalid equipment")
        return value

    @model_validator(mode="after")
    def coordinate_pairs(self):
        if (self.latitude is None) != (self.longitude is None) or (
            (self.map_x is None) != (self.map_y is None)
        ):
            raise ValueError("Coordinate pairs must both be set or blank")
        return self


def parse_row(values: dict[str, str], line: int) -> RoomRow:
    values = {key: value.strip() for key, value in values.items()}
    for key, value in values.items():
        if "\x00" in value:
            raise RoomImportError(f"CSV line {line}: invalid field: {key}.")
    parsed: dict = dict(values)
    try:
        for key in ("floor", "capacity"):
            if not re.fullmatch(r"-?(0|[1-9][0-9]*)", values[key]):
                raise ValueError
            parsed[key] = int(values[key])
        for key in ("location_verified", "active"):
            if values[key] not in {"true", "false"}:
                raise ValueError
            parsed[key] = values[key] == "true"
        for key in ("latitude", "longitude", "map_x", "map_y"):
            parsed[key] = float(values[key]) if values[key] else None
    except ValueError:
        raise RoomImportError(
            f"CSV line {line}: invalid field: {key}."
        ) from None
    parsed["equipment"] = (
        [item.strip() for item in values["equipment"].split("|")]
        if values["equipment"]
        else []
    )
    try:
        return RoomRow.model_validate(parsed)
    except ValidationError as error:
        # Print only known field names, never row values or error input details.
        fields = sorted(
            {
                str(item["loc"][0]) if item["loc"] else "coordinates"
                for item in error.errors(include_input=False)
            }
        )
        raise RoomImportError(
            f"CSV line {line}: invalid field(s): {', '.join(fields)}."
        ) from None


def read_rooms(path: Path) -> list[RoomRow]:
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_BYTES + 1)
    except (OSError, ValueError):
        raise RoomImportError("CSV could not be read.") from None
    if len(raw) > MAX_BYTES:
        raise RoomImportError("CSV exceeds the 2 MiB limit.")
    try:
        reader = csv.reader(
            io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True
        )
        headers = next(reader, [])
        if len(headers) != len(HEADERS) or set(headers) != set(HEADERS):
            raise RoomImportError("CSV headers must match rooms-template.csv.")
        rooms = []
        codes = set()
        for fields in reader:
            line = reader.line_num
            if len(rooms) >= MAX_ROWS:
                raise RoomImportError("CSV exceeds the 2000 room limit.")
            if len(fields) != len(headers):
                raise RoomImportError(f"CSV line {line}: wrong column count.")
            room = parse_row(dict(zip(headers, fields, strict=True)), line)
            if room.code in codes:
                raise RoomImportError(f"CSV line {line}: duplicate room code.")
            codes.add(room.code)
            rooms.append(room)
    except (UnicodeError, csv.Error):
        raise RoomImportError(
            "CSV must be valid UTF-8 with valid quoting."
        ) from None
    if not rooms:
        raise RoomImportError("CSV must contain at least one room.")
    return rooms


UPSERT = """
INSERT INTO public.rooms
    (code,name,building,floor,capacity,equipment,latitude,longitude,
     map_x,map_y,location_text,location_verified,active)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
ON CONFLICT (code) DO UPDATE SET
    name=EXCLUDED.name,building=EXCLUDED.building,floor=EXCLUDED.floor,
    capacity=EXCLUDED.capacity,equipment=EXCLUDED.equipment,
    latitude=EXCLUDED.latitude,longitude=EXCLUDED.longitude,
    map_x=EXCLUDED.map_x,map_y=EXCLUDED.map_y,
    location_text=EXCLUDED.location_text,
    location_verified=EXCLUDED.location_verified,active=EXCLUDED.active
"""


async def import_rooms(connection, rooms: list[RoomRow]) -> None:
    async with connection.transaction():
        await connection.execute("SET LOCAL lock_timeout='2s'")
        await connection.execute("SET LOCAL statement_timeout='30s'")
        owner = await connection.fetchval(
            """SELECT pg_has_role(current_user,relowner,'USAGE')
               FROM pg_catalog.pg_class
               WHERE oid=to_regclass('public.rooms')"""
        )
        if not owner:
            raise RoomImportError("Room import requires the table owner role.")
        # Consistent code ordering avoids opposite-order locks across imports.
        await connection.executemany(
            UPSERT,
            [
                tuple(getattr(room, key) for key in HEADERS)
                for room in sorted(rooms, key=lambda room: room.code)
            ],
        )


async def apply_rooms(rooms: list[RoomRow]) -> None:
    url = os.environ.get("DATABASE_MIGRATION_URL", "")
    if not url:
        raise RoomImportError(
            "Set DATABASE_MIGRATION_URL to the owner connection."
        )
    try:
        parsed = urlparse(url)
        if (
            parsed.scheme not in {"postgres", "postgresql"}
            or not parsed.hostname
            or not parsed.username
            or not parsed.path.strip("/")
            or parsed.fragment
            or set(parse_qs(parsed.query, keep_blank_values=True)) - {"sslmode"}
        ):
            raise ValueError
        # Avoid unrelated app settings and .env files when importing metadata.
        settings = Settings.model_construct(
            environment="development",
            database_url=url,
            database_ssl_ca_file=os.environ.get("DATABASE_SSL_CA_FILE", ""),
        )
        tls = database_ssl_context(settings)
        connection = await asyncpg.connect(
            url, ssl=tls, timeout=10, command_timeout=30
        )
        try:
            await import_rooms(connection, rooms)
        finally:
            await connection.close()
    except RoomImportError:
        raise
    except (
        asyncpg.PostgresError,
        asyncpg.InterfaceError,
        OSError,
        ValueError,
        RuntimeError,
        TimeoutError,
    ):
        raise RoomImportError(
            "Database import failed. Check owner permissions, TLS and database logs."
        ) from None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit metadata using owner credentials",
    )
    args = parser.parse_args(argv)
    try:
        rooms = read_rooms(args.csv_file)
        if args.apply:
            asyncio.run(apply_rooms(rooms))
            print(
                f"Imported {len(rooms)} room(s). Existing IDs and bookings retained."
            )
        else:
            print(
                f"Validated {len(rooms)} room(s). Offline only; no database changes."
            )
        return 0
    except RoomImportError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
