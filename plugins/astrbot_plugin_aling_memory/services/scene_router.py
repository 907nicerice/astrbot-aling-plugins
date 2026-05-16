from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .defaults import DEFAULT_CONFIG
from .text_utils import keyword_hits, normalize_text


@dataclass
class SceneResult:
    primary_scene: str
    labels: list[str]
    reasons: list[str]


class SceneRouter:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}

    def classify(self, text: str) -> SceneResult:
        normalized = normalize_text(text)
        labels: list[str] = []
        reasons: list[str] = []
        if not normalized:
            return SceneResult("idle_chat", ["idle_chat"], ["empty_text"])
        if normalized.startswith("/mem") or normalized.startswith("／mem"):
            return SceneResult("command", ["command"], ["memory_command"])
        project_hits = keyword_hits(normalized, list(self.config.get("project_keywords") or []))
        study_hits = keyword_hits(normalized, list(self.config.get("study_keywords") or []))
        emotion_hits = keyword_hits(normalized, list(self.config.get("emotion_keywords") or []))
        if project_hits:
            labels.append("project_discussion")
            reasons.append("project_keywords:" + ",".join(project_hits[:5]))
        if study_hits:
            labels.append("study_help")
            reasons.append("study_keywords:" + ",".join(study_hits[:5]))
        if emotion_hits:
            labels.append("emotional_support")
            reasons.append("emotion_keywords:" + ",".join(emotion_hits[:5]))
        if self._is_idle(normalized) and not labels:
            return SceneResult("idle_chat", ["idle_chat"], ["short_ping"])
        if not labels:
            labels.append("daily_chat")
            reasons.append("fallback_daily")
        primary = self._choose_primary(labels)
        return SceneResult(primary, labels, reasons)

    def _choose_primary(self, labels: list[str]) -> str:
        for scene in ("project_discussion", "emotional_support", "study_help", "daily_chat"):
            if scene in labels:
                return scene
        return labels[0] if labels else "daily_chat"

    def _is_idle(self, text: str) -> bool:
        compact = text.replace(" ", "")
        idle_words = {"阿绫", "在吗", "嗯？", "嗯?", "喂", "hello", "hi", "？", "?"}
        return compact in idle_words or (len(compact) <= 3 and compact.endswith(("?", "？")))
