from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4


ALLOWED_MEMORY_TYPES = {
    "small_memory",
    "preference_memory",
    "relationship_memory",
    "life_signal",
    "project_context",
    "context_summary",
}

ALLOWED_STATUSES = {"active", "stale", "deprecated"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


@dataclass
class MemoryItem:
    id: str
    type: str
    content: str
    tags: list[str] = field(default_factory=list)
    use_rule: str = ""
    tone: str = ""
    confidence: float = 0.7
    source: str = "manual"
    status: str = "active"
    ttl_days: Optional[int] = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    last_used_at: Optional[str] = None
    used_count: int = 0

    @classmethod
    def create(
        cls,
        memory_type: str,
        content: str,
        tags: Optional[list[str]] = None,
        use_rule: str = "",
        tone: str = "",
        confidence: float = 0.8,
        source: str = "manual",
        ttl_days: Optional[int] = None,
    ) -> "MemoryItem":
        if memory_type not in ALLOWED_MEMORY_TYPES:
            raise ValueError(f"Unsupported memory type: {memory_type}")
        now = utc_now_iso()
        return cls(
            id=new_id("mem"),
            type=memory_type,
            content=content.strip(),
            tags=tags or [],
            use_rule=use_rule.strip(),
            tone=tone.strip(),
            confidence=max(0.0, min(1.0, confidence)),
            source=source,
            ttl_days=ttl_days,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryItem":
        item = cls(
            id=str(data.get("id") or new_id("mem")),
            type=str(data.get("type") or "small_memory"),
            content=str(data.get("content") or ""),
            tags=list(data.get("tags") or []),
            use_rule=str(data.get("use_rule") or ""),
            tone=str(data.get("tone") or ""),
            confidence=float(data.get("confidence", 0.7)),
            source=str(data.get("source") or "manual"),
            status=str(data.get("status") or "active"),
            ttl_days=data.get("ttl_days"),
            created_at=str(data.get("created_at") or utc_now_iso()),
            updated_at=str(data.get("updated_at") or utc_now_iso()),
            last_used_at=data.get("last_used_at"),
            used_count=int(data.get("used_count") or 0),
        )
        if item.type not in ALLOWED_MEMORY_TYPES:
            item.type = "small_memory"
        if item.status not in ALLOWED_STATUSES:
            item.status = "active"
        item.confidence = max(0.0, min(1.0, item.confidence))
        item.tags = [str(tag).strip() for tag in item.tags if str(tag).strip()]
        return item

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        if not self.ttl_days:
            return False
        created = parse_iso(self.created_at)
        if not created:
            return False
        ref = now or datetime.now(timezone.utc)
        return (ref - created).days >= self.ttl_days


@dataclass
class CandidateMemory:
    id: str
    suggested_type: str
    content: str
    reason: str
    confidence: float = 0.7
    tags: list[str] = field(default_factory=list)
    use_rule: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def create(
        cls,
        suggested_type: str,
        content: str,
        reason: str,
        confidence: float,
        tags: Optional[list[str]] = None,
        use_rule: str = "",
    ) -> "CandidateMemory":
        if suggested_type not in ALLOWED_MEMORY_TYPES:
            suggested_type = "small_memory"
        return cls(
            id=new_id("cand"),
            suggested_type=suggested_type,
            content=content.strip(),
            reason=reason.strip(),
            confidence=max(0.0, min(1.0, confidence)),
            tags=tags or [],
            use_rule=use_rule.strip(),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateMemory":
        return cls(
            id=str(data.get("id") or new_id("cand")),
            suggested_type=str(data.get("suggested_type") or "small_memory"),
            content=str(data.get("content") or ""),
            reason=str(data.get("reason") or ""),
            confidence=float(data.get("confidence", 0.7)),
            tags=list(data.get("tags") or []),
            use_rule=str(data.get("use_rule") or ""),
            created_at=str(data.get("created_at") or utc_now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContextSummary:
    id: str
    session_id: str
    content: str
    tags: list[str] = field(default_factory=list)
    ttl_days: int = 3
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def create(
        cls,
        session_id: str,
        content: str,
        tags: Optional[list[str]] = None,
        ttl_days: int = 3,
    ) -> "ContextSummary":
        now = utc_now_iso()
        return cls(
            id=new_id("sum"),
            session_id=session_id,
            content=content.strip(),
            tags=tags or [],
            ttl_days=ttl_days,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextSummary":
        return cls(
            id=str(data.get("id") or new_id("sum")),
            session_id=str(data.get("session_id") or "default"),
            content=str(data.get("content") or ""),
            tags=list(data.get("tags") or []),
            ttl_days=int(data.get("ttl_days") or 3),
            created_at=str(data.get("created_at") or utc_now_iso()),
            updated_at=str(data.get("updated_at") or utc_now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        created = parse_iso(self.created_at)
        if not created:
            return False
        ref = now or datetime.now(timezone.utc)
        return (ref - created).days >= self.ttl_days
