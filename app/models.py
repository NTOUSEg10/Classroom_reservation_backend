import base64
import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


Status = Literal[
    "pending", "approved", "rejected", "cancelled", "checked_out", "completed"
]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Register(Input):
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=8, max_length=24, pattern=r"^\+?[0-9 ()-]+$")
    department: str = Field(min_length=1, max_length=100)
    institutional_id: str = Field(pattern=r"^[A-Za-z0-9]{6,16}$")

    @field_validator("name", "phone", "department", "institutional_id")
    @classmethod
    def trim_required(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("欄位不可空白")
        return value


class Verify(Input):
    institutional_id: str = Field(pattern=r"^[A-Za-z0-9]{6,16}$")


class ReservationCreate(Input):
    room_id: UUID
    starts_at: datetime
    ends_at: datetime
    purpose: str = Field(min_length=2, max_length=500)
    attendees: int = Field(ge=1, le=1000)
    mode: Literal["immediate", "scheduled"]
    request_id: UUID

    @field_validator("starts_at", "ends_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("時間必須包含時區")
        return value


class StatusChange(Input):
    status: Status
    reason: str | None = Field(default=None, max_length=500)


class UserChange(Input):
    suspended: bool


class ViolationCreate(Input):
    user_id: UUID
    reservation_id: UUID | None = None
    points: int = Field(ge=1, le=3)
    reason: str = Field(min_length=2, max_length=500)


class ViolationResolve(Input):
    resolved: Literal[True]


def validate_push_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").lower()
    allowed = (
        host == "fcm.googleapis.com"
        or host == "updates.push.services.mozilla.com"
        or host == "web.push.apple.com"
        or host.endswith(".push.apple.com")
        or host.endswith(".notify.windows.com")
    )
    if (
        not allowed
        or parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
        or parsed.fragment
        or not parsed.path
        or parsed.path == "/"
    ):
        raise ValueError("不支援的推播端點")
    return endpoint


class PushKeys(Input):
    p256dh: str
    auth: str

    @field_validator("p256dh", "auth")
    @classmethod
    def valid_key(cls, value, info):
        if not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", value):
            raise ValueError("推播金鑰格式錯誤")
        decoded = base64.urlsafe_b64decode(value + "=" * ((-len(value)) % 4))
        if info.field_name == "p256dh" and (
            len(decoded) != 65 or decoded[0] != 4
        ):
            raise ValueError("p256dh 必須為 P-256 公鑰")
        if info.field_name == "auth" and len(decoded) != 16:
            raise ValueError("auth 金鑰須為 16 bytes")
        return value


class PushSubscription(Input):
    endpoint: str = Field(max_length=2048)
    keys: PushKeys
    expirationTime: int | None = None

    @field_validator("endpoint")
    @classmethod
    def safe_endpoint(cls, value):
        return validate_push_endpoint(value)


class PushDelete(Input):
    endpoint: str = Field(max_length=2048)
