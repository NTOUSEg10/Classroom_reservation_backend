from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from .models import ReservationCreate


TAIPEI = timezone(timedelta(hours=8))
TRANSITIONS = {
    "pending": {"approved", "rejected", "cancelled"},
    "approved": {"checked_out", "cancelled"},
    "checked_out": {"completed"},
    "rejected": set(),
    "cancelled": set(),
    "completed": set(),
}


def validate_interval(start: datetime, end: datetime, max_days: int = 7):
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(422, "時間必須包含時區")
    if end <= start or end - start > timedelta(days=max_days):
        raise HTTPException(422, f"查詢時段須大於零且不超過 {max_days} 天")


def validate_booking(data: ReservationCreate, now: datetime):
    start, end = (
        data.starts_at.astimezone(TAIPEI),
        data.ends_at.astimezone(TAIPEI),
    )
    if start < now - timedelta(minutes=5) or start > now + timedelta(days=90):
        raise HTTPException(422, "開始時間須介於現在前 5 分鐘至未來 90 天")
    if not timedelta(minutes=30) <= end - start <= timedelta(hours=8):
        raise HTTPException(422, "借用時間須為 30 分鐘至 8 小時")
    if (
        start.date() != end.date()
        or start.hour < 8
        or end.hour > 22
        or (end.hour == 22 and (end.minute or end.second or end.microsecond))
    ):
        raise HTTPException(422, "教室開放時間為同日 08:00–22:00")
    if data.mode == "immediate" and start > now + timedelta(minutes=15):
        raise HTTPException(422, "即時借用須於 15 分鐘內開始")


def validate_transition(current: str, target: str, reason: str | None):
    if target not in TRANSITIONS[current]:
        raise HTTPException(409, "不允許此借用狀態變更")
    if target == "rejected" and (not reason or len(reason.strip()) < 2):
        raise HTTPException(422, "拒絕申請須填寫理由")


def ensure_eligible(profile, points: int):
    if not profile["verified"]:
        raise HTTPException(403, "請先完成校園身分驗證")
    if profile["suspended"] or points >= 3:
        raise HTTPException(403, "帳號已停權，請洽管理員")
