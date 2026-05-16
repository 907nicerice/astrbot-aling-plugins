from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from ..models.memory_item import (
    ALLOWED_MEMORY_TYPES,
    CandidateMemory,
    ContextSummary,
    MemoryItem,
    utc_now_iso,
)
from .defaults import DEFAULT_CONFIG, PLUGIN_NAME
from .json_store import JsonFile

logger = logging.getLogger(PLUGIN_NAME)


class MemoryStore:
    def __init__(self, data_dir: Path, config: Optional[dict[str, Any]] = None) -> None:
        self.data_dir = data_dir
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.memory_file = JsonFile(data_dir / "memory_store.json", {"version": 1, "scopes": {}})
        self.summary_file = JsonFile(data_dir / "context_summaries.json", {"version": 1, "scopes": {}})
        self.config_file = JsonFile(data_dir / "config.json", {"version": 1, **DEFAULT_CONFIG})

    def ensure_config_file(self) -> dict[str, Any]:
        existing = self.config_file.load()
        merged = {"version": 1, **DEFAULT_CONFIG, **existing, **self.config}
        self.config_file.save(merged)
        return merged

    def _load_memory_root(self) -> dict[str, Any]:
        data = self.memory_file.load()
        data.setdefault("version", 1)
        data.setdefault("scopes", {})
        return data

    def _scope(self, root: dict[str, Any], scope_id: str) -> dict[str, Any]:
        scopes = root.setdefault("scopes", {})
        scope = scopes.setdefault(scope_id, {"memories": [], "candidates": []})
        scope.setdefault("memories", [])
        scope.setdefault("candidates", [])
        return scope

    def list_memories(self, scope_id: str, include_inactive: bool = False) -> list[MemoryItem]:
        root = self._load_memory_root()
        items = [MemoryItem.from_dict(data) for data in self._scope(root, scope_id)["memories"]]
        if include_inactive:
            return items
        return [item for item in items if item.status == "active" and not item.is_expired()]

    def add_memory(
        self,
        scope_id: str,
        memory_type: str,
        content: str,
        tags: Optional[list[str]] = None,
        use_rule: str = "",
        tone: str = "",
        confidence: float = 0.8,
        source: str = "manual",
        ttl_days: Optional[int] = None,
    ) -> MemoryItem:
        if memory_type not in ALLOWED_MEMORY_TYPES:
            raise ValueError(f"Unsupported memory type: {memory_type}")
        item = MemoryItem.create(
            memory_type,
            content,
            tags=tags,
            use_rule=use_rule,
            tone=tone,
            confidence=confidence,
            source=source,
            ttl_days=ttl_days,
        )
        root = self._load_memory_root()
        scope = self._scope(root, scope_id)
        scope["memories"].append(item.to_dict())
        max_total = int(self.config.get("max_memory_items_total") or 500)
        scope["memories"] = scope["memories"][-max_total:]
        self.memory_file.save(root)
        logger.info("[aling_memory] add memory id=%s type=%s scope=%s", item.id, item.type, scope_id)
        return item

    def get_memory(self, scope_id: str, memory_id: str) -> Optional[MemoryItem]:
        for item in self.list_memories(scope_id, include_inactive=True):
            if item.id == memory_id:
                return item
        return None

    def update_memory(
        self,
        scope_id: str,
        memory_id: str,
        content: Optional[str] = None,
        tags: Optional[list[str]] = None,
        status: Optional[str] = None,
        mark_used: bool = False,
    ) -> Optional[MemoryItem]:
        root = self._load_memory_root()
        scope = self._scope(root, scope_id)
        updated: Optional[MemoryItem] = None
        for index, data in enumerate(scope["memories"]):
            item = MemoryItem.from_dict(data)
            if item.id != memory_id:
                continue
            if content is not None:
                item.content = content.strip()
            if tags is not None:
                item.tags = tags
            if status is not None:
                item.status = status
            if mark_used:
                item.last_used_at = utc_now_iso()
                item.used_count += 1
            item.updated_at = utc_now_iso()
            scope["memories"][index] = item.to_dict()
            updated = item
            break
        if updated:
            self.memory_file.save(root)
            logger.info("[aling_memory] update memory id=%s scope=%s", memory_id, scope_id)
        return updated

    def delete_memory(self, scope_id: str, memory_id: str) -> bool:
        root = self._load_memory_root()
        scope = self._scope(root, scope_id)
        before = len(scope["memories"])
        scope["memories"] = [data for data in scope["memories"] if data.get("id") != memory_id]
        deleted = len(scope["memories"]) != before
        if deleted:
            self.memory_file.save(root)
            logger.info("[aling_memory] delete memory id=%s scope=%s", memory_id, scope_id)
        return deleted

    def clear_scope(self, scope_id: str) -> dict[str, int]:
        root = self._load_memory_root()
        scope = self._scope(root, scope_id)
        counts = {
            "memories": len(scope.get("memories") or []),
            "candidates": len(scope.get("candidates") or []),
        }
        scope["memories"] = []
        scope["candidates"] = []
        self.memory_file.save(root)
        logger.info(
            "[aling_memory] clear scope=%s memories=%s candidates=%s",
            scope_id,
            counts["memories"],
            counts["candidates"],
        )
        return counts

    def search_memories(self, scope_id: str, keyword: str) -> list[MemoryItem]:
        key = keyword.lower()
        result: list[MemoryItem] = []
        for item in self.list_memories(scope_id, include_inactive=True):
            haystack = " ".join([item.content, item.use_rule, " ".join(item.tags)]).lower()
            if key in haystack:
                result.append(item)
        return result

    def list_candidates(self, scope_id: str) -> list[CandidateMemory]:
        root = self._load_memory_root()
        return [CandidateMemory.from_dict(data) for data in self._scope(root, scope_id)["candidates"]]

    def add_candidate(self, scope_id: str, candidate: CandidateMemory) -> CandidateMemory:
        root = self._load_memory_root()
        scope = self._scope(root, scope_id)
        if any(existing.get("content") == candidate.content for existing in scope["candidates"]):
            return candidate
        scope["candidates"].append(candidate.to_dict())
        max_total = int(self.config.get("max_candidates_total") or 100)
        scope["candidates"] = scope["candidates"][-max_total:]
        self.memory_file.save(root)
        return candidate

    def remove_candidate(self, scope_id: str, candidate_id: str) -> Optional[CandidateMemory]:
        root = self._load_memory_root()
        scope = self._scope(root, scope_id)
        removed: Optional[CandidateMemory] = None
        kept = []
        for data in scope["candidates"]:
            if data.get("id") == candidate_id:
                removed = CandidateMemory.from_dict(data)
            else:
                kept.append(data)
        if removed:
            scope["candidates"] = kept
            self.memory_file.save(root)
        return removed

    def approve_candidate(self, scope_id: str, candidate_id: str) -> Optional[MemoryItem]:
        candidate = self.remove_candidate(scope_id, candidate_id)
        if not candidate:
            return None
        return self.add_memory(
            scope_id,
            candidate.suggested_type,
            candidate.content,
            tags=candidate.tags,
            use_rule=candidate.use_rule,
            confidence=candidate.confidence,
            source="auto_confirmed",
        )

    def _load_summary_root(self) -> dict[str, Any]:
        data = self.summary_file.load()
        data.setdefault("version", 1)
        data.setdefault("scopes", {})
        return data

    def _summary_scope(self, root: dict[str, Any], scope_id: str) -> dict[str, Any]:
        scope = root.setdefault("scopes", {}).setdefault(
            scope_id, {"summaries": [], "recent_messages": [], "turn_count": 0}
        )
        scope.setdefault("summaries", [])
        scope.setdefault("recent_messages", [])
        scope.setdefault("turn_count", 0)
        return scope

    def record_message(self, scope_id: str, role: str, content: str, max_recent: int = 60) -> int:
        root = self._load_summary_root()
        scope = self._summary_scope(root, scope_id)
        if content.strip():
            scope["recent_messages"].append({"role": role, "content": content.strip(), "at": utc_now_iso()})
            scope["recent_messages"] = scope["recent_messages"][-max_recent:]
        if role == "user":
            scope["turn_count"] = int(scope.get("turn_count") or 0) + 1
        self.summary_file.save(root)
        return int(scope.get("turn_count") or 0)

    def recent_messages(self, scope_id: str) -> list[dict[str, str]]:
        root = self._load_summary_root()
        return list(self._summary_scope(root, scope_id)["recent_messages"])

    def add_summary(self, scope_id: str, summary: ContextSummary) -> ContextSummary:
        root = self._load_summary_root()
        scope = self._summary_scope(root, scope_id)
        scope["summaries"].append(summary.to_dict())
        scope["summaries"] = scope["summaries"][-50:]
        scope["recent_messages"] = []
        self.summary_file.save(root)
        self.add_memory(
            scope_id,
            "context_summary",
            summary.content,
            tags=summary.tags,
            use_rule="短期辅助理解最近对话；不要当作长期设定。",
            confidence=0.65,
            source="compression",
            ttl_days=summary.ttl_days,
        )
        return summary

    def list_summaries(self, scope_id: str, include_expired: bool = False) -> list[ContextSummary]:
        root = self._load_summary_root()
        summaries = [ContextSummary.from_dict(data) for data in self._summary_scope(root, scope_id)["summaries"]]
        if include_expired:
            return summaries
        return [summary for summary in summaries if not summary.is_expired()]

    def clear_summaries(self, scope_id: str) -> None:
        root = self._load_summary_root()
        scope = self._summary_scope(root, scope_id)
        scope["summaries"] = []
        scope["recent_messages"] = []
        self.summary_file.save(root)
