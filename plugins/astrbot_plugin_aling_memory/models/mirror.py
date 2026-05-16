from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .memory_item import utc_now_iso


@dataclass
class MirrorSlice:
    summary: str = ""
    usage: str = ""
    source: str = "auto"
    updated_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MirrorSlice":
        return cls(
            summary=str(data.get("summary") or ""),
            usage=str(data.get("usage") or ""),
            source=str(data.get("source") or "auto"),
            updated_at=str(data.get("updated_at") or utc_now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
