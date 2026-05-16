from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..models.memory_item import MemoryItem, parse_iso
from .defaults import DEFAULT_CONFIG, SCENE_LIMITS
from .flashback import FlashbackService
from .memory_store import MemoryStore
from .scene_router import SceneResult
from .text_utils import keyword_hits


@dataclass
class RetrievalResult:
    small_memories: list[MemoryItem] = field(default_factory=list)
    project_contexts: list[MemoryItem] = field(default_factory=list)
    filtered: list[str] = field(default_factory=list)
    flashback: bool = False
    flashback_memory_id: str | None = None

    @property
    def selected_ids(self) -> list[str]:
        return [item.id for item in [*self.small_memories, *self.project_contexts]]


class Retriever:
    def __init__(
        self,
        store: MemoryStore,
        flashback: FlashbackService,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self.flashback = flashback
        self.config = {**DEFAULT_CONFIG, **(config or {})}

    def retrieve(self, scope_id: str, text: str, scene: SceneResult) -> RetrievalResult:
        limits = SCENE_LIMITS.get(scene.primary_scene, SCENE_LIMITS["daily_chat"])
        result = RetrievalResult()
        if scene.primary_scene in {"idle_chat", "command"}:
            result.filtered.append("idle_or_command_no_memory")
            return result
        memories = self.store.list_memories(scope_id)
        scored: list[tuple[float, MemoryItem]] = []
        for item in memories:
            ok, reason = self._allowed_type(item, scene.primary_scene)
            if not ok:
                result.filtered.append(f"{item.id}:{reason}")
                continue
            score = self._score(item, text, scene)
            if score <= 0:
                result.filtered.append(f"{item.id}:tag_mismatch")
                continue
            scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        small_limit = int(limits.get("small_memory") or 0)
        project_limit = int(limits.get("project_context") or 0)
        for _, item in scored:
            if item.type == "project_context":
                if len(result.project_contexts) < project_limit:
                    result.project_contexts.append(item)
                else:
                    result.filtered.append(f"{item.id}:project_limit")
                continue
            if item.type in {"small_memory", "preference_memory", "relationship_memory", "life_signal", "context_summary"}:
                if len(result.small_memories) >= small_limit:
                    result.filtered.append(f"{item.id}:small_memory_limit")
                    continue
                if item.type == "small_memory":
                    can, reason = self.flashback.can_use(scope_id, item, scene.primary_scene)
                    if can and not result.flashback:
                        result.flashback = True
                        result.flashback_memory_id = item.id
                        result.small_memories.append(item)
                    elif can:
                        result.filtered.append(f"{item.id}:flashback_already_selected")
                    else:
                        if scene.primary_scene in {"study_help", "daily_chat", "emotional_support"} and len(result.small_memories) < small_limit:
                            result.small_memories.append(item)
                        result.filtered.append(f"{item.id}:{reason}")
                else:
                    result.small_memories.append(item)
        return result

    def _allowed_type(self, item: MemoryItem, scene: str) -> tuple[bool, str]:
        if item.status != "active":
            return False, "inactive"
        if item.is_expired():
            return False, "expired"
        if item.type == "project_context" and scene != "project_discussion":
            return False, "project_context_scene_mismatch"
        return True, "ok"

    def _score(self, item: MemoryItem, text: str, scene: SceneResult) -> float:
        lower = text.lower()
        score = item.confidence
        if item.source == "manual":
            score += 0.25
        if item.updated_at:
            updated = parse_iso(item.updated_at)
            if updated:
                age_days = max(0, (datetime.now(timezone.utc) - updated).days)
                score += max(0, 0.2 - age_days * 0.01)
        haystack = f"{item.content} {' '.join(item.tags)} {item.use_rule}".lower()
        hits = 0
        for tag in item.tags:
            if tag.lower() in lower:
                hits += 2
        for token in keyword_hits(lower, [part for part in haystack.split() if len(part) >= 2]):
            if token in lower:
                hits += 1
        for label in scene.labels:
            if label == "study_help" and any(word in haystack for word in ("课", "学习", "题", "考试", "物理", "高数", "水课")):
                hits += 2
            if label == "project_discussion" and item.type == "project_context":
                hits += 3
            if label == "emotional_support" and any(word in haystack for word in ("烦", "累", "难受", "焦虑")):
                hits += 1
        if hits == 0:
            return 0
        return score + hits
