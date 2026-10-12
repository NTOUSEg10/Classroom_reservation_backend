from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models import Register, ReservationCreate
from app.rules import (
    ensure_eligible,
    validate_booking,
    validate_interval,
    validate_transition,
)


NOW = datetime(2026, 10, 11, 0, tzinfo=timezone.utc)


def booking(**changes):
    values = {
        "room_id": uuid4(),
        "starts_at": NOW + timedelta(hours=1),
        "ends_at": NOW + timedelta(hours=2),
        "purpose": "專題讨论",
        "attendees": 12,
        "mode": "scheduled",
        "request_id": uuid4(),
    }
    values.update(changes)
    return ReservationCreate(**values)


def test_interval_boundaries_and_adjacent_policy():
    validate_interval(NOW, NOW + timedelta(days=7))
    for start, end in [
        (NOW, NOW),
        (NOW, NOW + timedelta(days=7, microseconds=1)),
        (NOW.replace(tzinfo=None), NOW),
    ]:
        with pytest.raises(HTTPException) as error:
            validate_interval(start, end)
        assert error.value.status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"starts_at": NOW - timedelta(minutes=6)},
        {
            "starts_at": NOW + timedelta(days=91),
            "ends_at": NOW + timedelta(days=91, hours=1),
        },
        {"ends_at": NOW + timedelta(hours=1, minutes=29)},
        {"ends_at": NOW + timedelta(hours=10)},
        {
            "starts_at": NOW - timedelta(hours=1),
            "ends_at": NOW + timedelta(hours=1),
        },
        {
            "starts_at": NOW + timedelta(hours=13),
            "ends_at": NOW + timedelta(hours=14, seconds=1),
        },
        {
            "starts_at": NOW + timedelta(hours=15),
            "ends_at": NOW + timedelta(hours=25),
        },
        {"mode": "immediate"},
    ],
)
def test_booking_rejects_invalid_window(changes):
    with pytest.raises(HTTPException) as error:
        validate_booking(booking(**changes), NOW)
    assert error.value.status_code == 422


def test_booking_accepts_opening_exact_half_hour_and_immediate():
    validate_booking(
        booking(
            starts_at=NOW, ends_at=NOW + timedelta(minutes=30), mode="immediate"
        ),
        NOW,
    )
    validate_booking(
        booking(
            starts_at=NOW + timedelta(hours=13),
            ends_at=NOW + timedelta(hours=14),
        ),
        NOW,
    )


def test_missing_timezone_and_privilege_fields_are_rejected():
    with pytest.raises(ValidationError):
        booking(starts_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        booking(user_id=uuid4())
    data = {
        "name": "測試學生",
        "phone": "0912345678",
        "department": "資訊工程",
        "institutional_id": "123456789",
    }
    result = Register(**data)
    assert result.institutional_id == "123456789"
    for changes in [
        {"role": "admin"},
        {"verified": True},
        {"email": "test@example.com"},
        {"name": " "},
        {"id": str(uuid4())},
        {"suspended": False},
        {"password": "must-not-be-accepted"},
    ]:
        with pytest.raises(ValidationError):
            Register(**(data | changes))


def test_lifecycle_rejects_skips_terminal_reentry_and_missing_reason():
    validate_transition("pending", "approved", None)
    validate_transition("approved", "checked_out", None)
    validate_transition("checked_out", "completed", None)
    validate_transition("pending", "rejected", "場地維護")
    for current, target in [
        ("pending", "completed"),
        ("approved", "completed"),
        ("checked_out", "cancelled"),
        ("completed", "pending"),
        ("pending", "pending"),
    ]:
        with pytest.raises(HTTPException) as error:
            validate_transition(current, target, None)
        assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        validate_transition("pending", "rejected", " ")
    assert error.value.status_code == 422


def test_eligibility_does_not_trust_existing_session():
    ensure_eligible({"verified": True, "suspended": False}, 2)
    for profile, points in [
        ({"verified": False, "suspended": False}, 0),
        ({"verified": True, "suspended": True}, 0),
        ({"verified": True, "suspended": False}, 3),
    ]:
        with pytest.raises(HTTPException) as error:
            ensure_eligible(profile, points)
        assert error.value.status_code == 403
