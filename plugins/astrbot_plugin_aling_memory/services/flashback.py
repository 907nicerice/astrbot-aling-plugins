from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models.memory_item import MemoryItem, parse_iso, utc_now_iso
from .defaults import DEFAULT_CONFIG
from .json_store import JsonFile


class FlashbackService:
    def __init__(self, data_dir: Path, config: dict[str, Any] | None = None) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.file = JsonFile(data_dir / "flashback_state.json", {"version": 1, "scopes": {}})

    def _root(self) -> dict[str, Any]:
        data = self.file.load()
        data.setdefault("version", 1)
        data.setdefault("scopes", {})
        return data

    def _scope(self, root: dict[str, Any], scope_id: str) -> dict[str, Any]:
        scope = root.setdefault("scopes", {}).setdefault(
            scope_id,
            {
                "last_flashback_at": None,
                "last_flashback_turn": 0,
                "daily": {},
                "memory_usage": {},
            },
        )
        scope.setdefault("daily", {})
        scope.setdefault("memory_usage", {})
        scope.setdefault("last_flashback_turn", 0)
        return scope

    def current_turn(self, scope_id: str) -> int:
        root = self._root()
        return int(self._scope(root, scope_id).get("turn", 0) or 0)

    def bump_turn(self, scope_id: str) -> int:
        root = self._root()
        scope = self._scope(root, scope_id)
        scope["turn"] = int(scope.get("turn") or 0) + 1
        self.file.save(root)
        return int(scope["turn"])

    def can_use(self, scope_id: str, memory: MemoryItem, scene: str) -> tuple[bool, str]:
        if scene in {"idle_chat", "command"}:
            return False, "scene_disallows_flashback"
        root = self._root()
        scope = self._scope(root, scope_id)
        turn = int(scope.get("turn") or 0)
        last_turn = int(scope.get("last_flashback_turn") or 0)
        min_gap = int(self.config.get("flashback_min_turn_gap") or 10)
        if turn - last_turn < min_gap:
            return False, "global_turn_gap"
        today = datetime.now(timezone.utc).date().isoformat()
        daily_count = int(scope.get("daily", {}).get(today) or 0)
        if daily_count >= int(self.config.get("max_flashback_per_day") or 5):
            return False, "daily_limit"
        usage = scope.get("memory_usage", {}).get(memory.id, {})
        last_used = parse_iso(usage.get("last_used_at") or memory.last_used_at)
        if last_used:
            age_hours = (datetime.now(timezone.utc) - last_used).total_seconds() / 3600
            if age_hours < float(self.config.get("same_memory_min_hours") or 48):
                return False, "recently_used"
        return True, "allowed"

    def mark_used(self, scope_id: str, memory_id: str) -> None:
        root = self._root()
        scope = self._scope(root, scope_id)
        today = datetime.now(timezone.utc).date().isoformat()
        now = utc_now_iso()
        usage = scope.setdefault("memory_usage", {}).setdefault(memory_id, {"used_count": 0})
        usage["last_used_at"] = now
        usage["used_count"] = int(usage.get("used_count") or 0) + 1
        scope["last_flashback_at"] = now
        scope["last_flashback_turn"] = int(scope.get("turn") or 0)
        scope.setdefault("daily", {})[today] = int(scope.get("daily", {}).get(today) or 0) + 1
        self.file.save(root)
