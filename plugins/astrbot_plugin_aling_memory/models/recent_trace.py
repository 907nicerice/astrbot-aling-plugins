from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .memory_item import new_id, parse_iso, utc_now_iso


def utc_after_hours(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).replace(microsecond=0).isoformat()


@dataclass
class RecentTrace:
    id: str
    session_id: str
    created_at: str
    expires_at: str
    topic: str
    summary: str
    user_state: str = ""
    bot_residue: str = ""
    recall_hints: list[str] = field(default_factory=list)
    importance: float = 0.5

    @classmethod
    def create(
        cls,
        session_id: str,
        topic: str,
        summary: str,
        user_state: str = "",
        bot_residue: str = "",
        recall_hints: list[str] | None = None,
        importance: float = 0.5,
        ttl_hours: int = 72,
    ) -> "RecentTrace":
        return cls(
            id=new_id("trace"),
            session_id=session_id,
            created_at=utc_now_iso(),
            expires_at=utc_after_hours(ttl_hours),
            topic=topic.strip()[:80],
            summary=summary.strip()[:260],
            user_state=user_state.strip()[:140],
            bot_residue=bot_residue.strip()[:140],
            recall_hints=recall_hints or [],
            importance=max(0.0, min(1.0, float(importance))),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecentTrace":
        return cls(
            id=str(data.get("id") or new_id("trace")),
            session_id=str(data.get("session_id") or "default"),
            created_at=str(data.get("created_at") or utc_now_iso()),
            expires_at=str(data.get("expires_at") or utc_after_hours(72)),
            topic=str(data.get("topic") or "")[:80],
            summary=str(data.get("summary") or "")[:260],
            user_state=str(data.get("user_state") or "")[:140],
            bot_residue=str(data.get("bot_residue") or "")[:140],
            recall_hints=[str(item) for item in data.get("recall_hints") or [] if str(item).strip()],
            importance=max(0.0, min(1.0, float(data.get("importance", 0.5)))),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def is_expired(self) -> bool:
        expires = parse_iso(self.expires_at)
        if not expires:
            return False
        return expires <= datetime.now(timezone.utc)

    def age_hours(self) -> float:
        created = parse_iso(self.created_at)
        if not created:
            return 0.0
        return max(0.0, (datetime.now(timezone.utc) - created).total_seconds() / 3600)
