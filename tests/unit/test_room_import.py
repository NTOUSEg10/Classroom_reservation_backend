import csv
import os
import ssl
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import asyncpg
import pytest

from scripts.import_rooms import (
    HEADERS,
    MAX_BYTES,
    RoomImportError,
    apply_rooms,
    main,
    read_rooms,
)


def room_values(**changes):
    return {
        "code": "TEST-001",
        "name": "測試教室",
        "building": "測試館",
        "floor": "2",
        "capacity": "40",
        "equipment": "白板|投影機",
        "latitude": "25.15",
        "longitude": "121.77",
        "map_x": "30",
        "map_y": "40",
        "location_text": "測試館二樓，純測試資料。",
        "location_verified": "false",
        "active": "true",
        **changes,
    }


def write_rooms(path, rows, *, headers=HEADERS, bom=False):
    with path.open(
        "w", encoding="utf-8-sig" if bom else "utf-8", newline=""
    ) as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows([row[key] for key in headers] for row in rows)
    return path


def test_default_cli_is_offline_and_does_not_read_app_settings(
    tmp_path, monkeypatch, capsys
):
    path = write_rooms(tmp_path / "rooms.csv", [room_values()], bom=True)
    monkeypatch.setenv("ENVIRONMENT", "invalid-app-setting")
    monkeypatch.setenv("DATABASE_MIGRATION_URL", "private-invalid-dsn")
    connect = AsyncMock(side_effect=AssertionError("Network must not be used"))
    monkeypatch.setattr("scripts.import_rooms.asyncpg.connect", connect)
    assert main([str(path)]) == 0
    assert "Validated 1 room(s). Offline only" in capsys.readouterr().out
    connect.assert_not_called()
    room = read_rooms(path)[0]
    assert room.equipment == ["白板", "投影機"]
    assert room.location_verified is False


def test_module_command_works_without_credentials(tmp_path):
    path = write_rooms(tmp_path / "rooms.csv", [room_values()])
    environment = os.environ.copy()
    environment.pop("DATABASE_MIGRATION_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "scripts.import_rooms", str(path)],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "Offline only; no database changes" in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize(
    "changes",
    [
        {"name": " "},
        {"name": "x" * 101},
        {"building": ""},
        {"code": "../ROOM"},
        {"code": "x" * 41},
        {"location_text": ""},
        {"location_text": "x" * 1001},
        {"location_text": "private-row\x00"},
        {"capacity": "0"},
        {"capacity": "1001"},
        {"capacity": "40.0"},
        {"capacity": "true"},
        {"floor": "101"},
        {"floor": "-21"},
        {"active": "1"},
        {"location_verified": "TRUE"},
        {"latitude": "91"},
        {"longitude": "-181"},
        {"latitude": "NaN"},
        {"latitude": "Infinity"},
        {"longitude": ""},
        {"map_x": "-1"},
        {"map_y": "101"},
        {"map_x": ""},
        {"equipment": "白板|"},
        {"equipment": "白板|白板"},
        {"equipment": "x" * 81},
        {"equipment": "|".join(str(index) for index in range(21))},
    ],
)
def test_invalid_room_values_do_not_echo_data(tmp_path, changes):
    path = write_rooms(tmp_path / "rooms.csv", [room_values(**changes)])
    with pytest.raises(RoomImportError, match="CSV line 2") as error:
        read_rooms(path)
    assert "private-row" not in str(error.value)
    assert "測試" not in str(error.value)


def test_coordinates_can_be_blank_as_complete_pairs_and_headers_reordered(
    tmp_path,
):
    path = write_rooms(
        tmp_path / "rooms.csv",
        [
            room_values(
                latitude="", longitude="", map_x="", map_y="", equipment=""
            )
        ],
        headers=tuple(reversed(HEADERS)),
    )
    room = read_rooms(path)[0]
    assert room.latitude is None and room.map_x is None
    assert room.equipment == []


@pytest.mark.parametrize(
    "content",
    [
        "",
        ",".join(HEADERS) + "\n",
        ",".join(HEADERS[:-1]) + "\n",
        ",".join((*HEADERS, "private-header")) + "\n",
        ",".join((*HEADERS[:-1], HEADERS[0])) + "\n",
        ",".join(HEADERS) + '\n"unterminated',
        ",".join(HEADERS) + "\nonly-one-field\n",
        ",".join(HEADERS) + "\n" + "," * len(HEADERS) + "\n",
        ",".join(HEADERS) + "\n\n",
    ],
)
def test_malformed_csv_rejected_before_apply(
    tmp_path, monkeypatch, content, capsys
):
    path = tmp_path / "rooms.csv"
    path.write_text(content, encoding="utf-8")
    apply = AsyncMock(
        side_effect=AssertionError("Must validate before database use")
    )
    monkeypatch.setattr("scripts.import_rooms.apply_rooms", apply)
    assert main([str(path), "--apply"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "private-header" not in output.err
    apply.assert_not_called()


def test_invalid_encoding_and_size_rejected(tmp_path):
    path = tmp_path / "rooms.csv"
    path.write_bytes(b"\xff")
    with pytest.raises(RoomImportError, match="UTF-8"):
        read_rooms(path)
    path.write_bytes(b" " * (MAX_BYTES + 1))
    with pytest.raises(RoomImportError, match="2 MiB"):
        read_rooms(path)


def test_row_limit_and_trimmed_duplicate_codes_rejected(tmp_path, monkeypatch):
    path = tmp_path / "rooms.csv"
    write_rooms(path, [room_values(), room_values(code=" TEST-001 ")])
    with pytest.raises(RoomImportError, match="duplicate room code"):
        read_rooms(path)
    monkeypatch.setattr("scripts.import_rooms.MAX_ROWS", 1)
    write_rooms(path, [room_values(), room_values(code="TEST-002")])
    with pytest.raises(RoomImportError, match="2000 room limit"):
        read_rooms(path)


def test_missing_file_is_controlled_and_does_not_echo_path(tmp_path, capsys):
    assert main([str(tmp_path / "private-input-name.csv")]) == 1
    assert "private-input" not in capsys.readouterr().err


async def test_apply_requires_explicit_owner_environment_without_app_fallback(
    tmp_path, monkeypatch
):
    path = write_rooms(tmp_path / "rooms.csv", [room_values()])
    monkeypatch.delenv("DATABASE_MIGRATION_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "private-app-dsn")
    connect = AsyncMock()
    monkeypatch.setattr("scripts.import_rooms.asyncpg.connect", connect)
    with pytest.raises(RoomImportError, match="DATABASE_MIGRATION_URL"):
        await apply_rooms(read_rooms(path))
    connect.assert_not_called()


async def test_apply_remote_tls_verifies_host_even_with_weak_dsn(
    tmp_path, monkeypatch
):
    path = write_rooms(tmp_path / "rooms.csv", [room_values()])
    monkeypatch.setenv(
        "DATABASE_MIGRATION_URL",
        "postgresql://owner:private-password@db.example.test:5432/ntou?sslmode=disable",
    )
    monkeypatch.delenv("DATABASE_SSL_CA_FILE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "invalid-unrelated-app-setting")
    connection = AsyncMock()
    connect = AsyncMock(return_value=connection)
    imported = AsyncMock()
    monkeypatch.setattr("scripts.import_rooms.asyncpg.connect", connect)
    monkeypatch.setattr("scripts.import_rooms.import_rooms", imported)
    await apply_rooms(read_rooms(path))
    tls = connect.call_args.kwargs["ssl"]
    assert tls.verify_mode == ssl.CERT_REQUIRED and tls.check_hostname
    imported.assert_awaited_once()
    connection.close.assert_awaited_once()


@pytest.mark.parametrize(
    "url",
    [
        "private-invalid-dsn",
        "postgresql://owner:private-password@127.0.0.1/ntou?host=db.example.test&sslmode=disable",
        "postgresql://owner:private-password@127.0.0.1/ntou?sslrootcert=private-path",
    ],
)
async def test_malformed_or_override_dsn_fails_before_connection(
    tmp_path, monkeypatch, url
):
    path = write_rooms(tmp_path / "rooms.csv", [room_values()])
    monkeypatch.setenv("DATABASE_MIGRATION_URL", url)
    connect = AsyncMock()
    monkeypatch.setattr("scripts.import_rooms.asyncpg.connect", connect)
    with pytest.raises(
        RoomImportError, match="Database import failed"
    ) as error:
        await apply_rooms(read_rooms(path))
    assert "private-" not in str(error.value)
    connect.assert_not_called()


@pytest.mark.parametrize("failure", [OSError, asyncpg.InvalidPasswordError])
async def test_database_errors_never_echo_credentials_or_server_details(
    tmp_path, monkeypatch, failure
):
    path = write_rooms(tmp_path / "rooms.csv", [room_values()])
    monkeypatch.setenv(
        "DATABASE_MIGRATION_URL",
        "postgresql://owner:private-password@127.0.0.1:5432/ntou",
    )
    connect = AsyncMock(
        side_effect=failure("private-password private-server-detail")
    )
    monkeypatch.setattr("scripts.import_rooms.asyncpg.connect", connect)
    with pytest.raises(
        RoomImportError, match="Database import failed"
    ) as error:
        await apply_rooms(read_rooms(path))
    assert "private-" not in str(error.value)
    assert error.value.__suppress_context__
