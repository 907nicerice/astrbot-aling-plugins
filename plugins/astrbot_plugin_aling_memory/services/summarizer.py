from __future__ import annotations

from typing import Any

from ..models.memory_item import ContextSummary
from .defaults import DEFAULT_CONFIG
from .scene_router import SceneRouter
from .text_utils import normalize_text


class Summarizer:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.router = SceneRouter(self.config)

    def summarize(self, scope_id: str, messages: list[dict[str, str]]) -> ContextSummary | None:
        clean = [
            f"{item.get('role', 'unknown')}: {normalize_text(item.get('content', ''))}"
            for item in messages
            if normalize_text(item.get("content", ""))
        ]
        if not clean:
            return None
        text = " / ".join(clean[-12:])
        tags = self._tags(text)
        content = self._compress(text)
        return ContextSummary.create(
            session_id=scope_id,
            content=content,
            tags=tags,
            ttl_days=int(self.config.get("summary_ttl_days") or 3),
        )

    def _compress(self, text: str) -> str:
        if len(text) <= 260:
            return f"最近对话大意：{text}"
        return f"最近对话大意：{text[:240]}..."

    def _tags(self, text: str) -> list[str]:
        scene = self.router.classify(text)
        tags: list[str] = []
        mapping = {
            "study_help": "study",
            "project_discussion": "project",
            "emotional_support": "emotion",
            "daily_chat": "daily",
        }
        for label in scene.labels:
            mapped = mapping.get(label)
            if mapped and mapped not in tags:
                tags.append(mapped)
        return tags or ["daily"]
