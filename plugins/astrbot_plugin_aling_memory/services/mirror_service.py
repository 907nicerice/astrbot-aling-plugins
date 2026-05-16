from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models.memory_item import MemoryItem, utc_now_iso
from ..models.mirror import MirrorSlice
from .defaults import DEFAULT_CONFIG, MIRROR_KEYS
from .json_store import JsonFile


class MirrorService:
    def __init__(self, data_dir: Path, config: dict[str, Any] | None = None) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.file = JsonFile(data_dir / "user_life_mirror.json", {"version": 1, "scopes": {}})

    def _root(self) -> dict[str, Any]:
        data = self.file.load()
        data.setdefault("version", 1)
        data.setdefault("scopes", {})
        return data

    def _empty_slice(self) -> dict[str, str]:
        return MirrorSlice().to_dict()

    def _scope(self, root: dict[str, Any], scope_id: str) -> dict[str, Any]:
        scope = root.setdefault("scopes", {}).setdefault(scope_id, {})
        for key in MIRROR_KEYS:
            scope.setdefault(key, self._empty_slice())
        scope.setdefault("updated_at", utc_now_iso())
        return scope

    def get(self, scope_id: str) -> dict[str, MirrorSlice]:
        root = self._root()
        scope = self._scope(root, scope_id)
        return {key: MirrorSlice.from_dict(scope.get(key) or {}) for key in MIRROR_KEYS}

    def clear(self, scope_id: str) -> int:
        root = self._root()
        scopes = root.setdefault("scopes", {})
        existed = 1 if scope_id in scopes else 0
        scopes.pop(scope_id, None)
        self.file.save(root)
        return existed

    def refresh(self, scope_id: str, memories: list[MemoryItem], manual: bool = False) -> dict[str, MirrorSlice]:
        root = self._root()
        scope = self._scope(root, scope_id)
        generated = self._generate(memories)
        allow_manual_overwrite = bool(self.config.get("allow_auto_overwrite_manual_mirror"))
        for key, slice_value in generated.items():
            existing = MirrorSlice.from_dict(scope.get(key) or {})
            if existing.source == "manual" and not manual and not allow_manual_overwrite:
                continue
            if slice_value.summary:
                slice_value.source = "manual" if manual else "auto"
                scope[key] = slice_value.to_dict()
        scope["updated_at"] = utc_now_iso()
        self.file.save(root)
        return self.get(scope_id)

    def select_slices(self, scope_id: str, scene: str, limit: int) -> list[tuple[str, MirrorSlice]]:
        if limit <= 0:
            return []
        mirror = self.get(scope_id)
        if scene == "project_discussion":
            order = ["project_life", "interaction_style", "memory_preference"]
        elif scene == "study_help":
            order = ["study_life", "interaction_style"]
        elif scene == "emotional_support":
            order = ["relationship_texture", "interaction_style", "memory_preference"]
        else:
            order = ["interaction_style", "study_life", "relationship_texture"]
        result: list[tuple[str, MirrorSlice]] = []
        for key in order:
            item = mirror.get(key)
            if item and item.summary:
                result.append((key, item))
            if len(result) >= limit:
                break
        return result

    def _generate(self, memories: list[MemoryItem]) -> dict[str, MirrorSlice]:
        buckets = {key: [] for key in MIRROR_KEYS}
        for item in memories:
            text = item.content
            tags = " ".join(item.tags)
            haystack = f"{text} {tags}"
            if item.type == "project_context":
                buckets["project_life"].append(text)
            if item.type in {"preference_memory", "relationship_memory"}:
                if any(word in haystack for word in ("短", "自然", "助手", "QQ", "留白", "聊天")):
                    buckets["interaction_style"].append(text)
                if any(word in haystack for word in ("亲近", "边界", "偏心", "表白", "关系")):
                    buckets["relationship_texture"].append(text)
                if any(word in haystack for word in ("记住", "记忆", "闪回", "小事")):
                    buckets["memory_preference"].append(text)
            if item.type in {"life_signal", "small_memory"} and any(
                word in haystack for word in ("课", "学习", "题", "考试", "物理", "高数", "水课")
            ):
                buckets["study_life"].append(text)
        return {
            "study_life": MirrorSlice(
                summary=self._join(buckets["study_life"], "用户近期会聊学习、课程或题目，也可能吐槽课程无聊。"),
                usage="当用户提到学习、上课或题目时自然顺着聊；不要像老师一样长篇说教。",
            ),
            "project_life": MirrorSlice(
                summary=self._join(buckets["project_life"], "用户在做阿绫 QQ bot，关注人格自然度、记忆、主动对话和 token 控制。"),
                usage="只有用户主动提到 bot、插件、prompt、AstrBot、QQ 空间、token 等话题时使用。",
            ),
            "interaction_style": MirrorSlice(
                summary=self._join(buckets["interaction_style"], "用户希望阿绫像日常 QQ 聊天，短、顺、有留白，不要助手味。"),
                usage="持续影响回复风格，但不要显式复述。",
            ),
            "relationship_texture": MirrorSlice(
                summary=self._join(buckets["relationship_texture"], "用户喜欢阿绫有亲近感和小情绪，但需要保留关系边界。"),
                usage="影响语气边界，不主动把关系推得过满。",
            ),
            "memory_preference": MirrorSlice(
                summary=self._join(buckets["memory_preference"], "用户希望阿绫记住小事，偶尔自然闪回，而不是追踪任务。"),
                usage="记忆调用优先生活感和小事，避免催办式表达。",
            ),
        }

    def _join(self, values: list[str], fallback: str) -> str:
        if not values:
            return fallback
        compact = "；".join(values[:3])
        return compact[:180]
