from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models.memory_item import MemoryItem
from ..models.mirror import MirrorSlice
from ..models.recent_trace import RecentTrace
from .defaults import DEFAULT_CONFIG, SCENE_LIMITS
from .retriever import RetrievalResult
from .scene_router import SceneResult
from .text_utils import estimate_tokens


@dataclass
class InjectionPlan:
    text: str = ""
    tokens_est: int = 0
    selected_ids: list[str] = field(default_factory=list)
    filtered: list[str] = field(default_factory=list)
    flashback: bool = False
    mirror_keys: list[str] = field(default_factory=list)
    recent_trace_ids: list[str] = field(default_factory=list)


class Injector:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}

    def build(
        self,
        scene: SceneResult,
        retrieval: RetrievalResult,
        mirror_slices: list[tuple[str, MirrorSlice]],
        recent_traces: list[RecentTrace] | None = None,
    ) -> InjectionPlan:
        budget = int((self.config.get("injection_budgets") or {}).get(scene.primary_scene, 0))
        if budget <= 0:
            return InjectionPlan(filtered=[*retrieval.filtered, "zero_budget"])
        chunks: list[str] = []
        selected_ids: list[str] = []
        recent_traces = recent_traces or []
        if recent_traces:
            chunks.append(self._recent_trace_block(recent_traces))
        relevant_lines = self._memory_lines(retrieval.small_memories)
        if relevant_lines:
            chunks.append(
                '<aling_relevant_memory budget="low">\n'
                + "\n".join(relevant_lines)
                + "\n- 这些记忆只允许自然影响回复；如果使用，不要说“根据记忆”或“我检索到”。\n"
                + "</aling_relevant_memory>"
            )
            selected_ids.extend([item.id for item in retrieval.small_memories])
        project_lines = self._memory_lines(retrieval.project_contexts)
        if project_lines:
            chunks.append(
                '<aling_project_context budget="medium">\n'
                + "\n".join(project_lines)
                + "\n- 只在当前项目话题相关时使用；不要变成任务推进或催办。\n"
                + "</aling_project_context>"
            )
            selected_ids.extend([item.id for item in retrieval.project_contexts])
        if mirror_slices:
            mirror_lines = [f"- {slice_value.summary} {slice_value.usage}".strip() for _, slice_value in mirror_slices]
            chunks.append("<user_life_mirror_slice>\n" + "\n".join(mirror_lines) + "\n</user_life_mirror_slice>")
        text = "\n\n".join(chunks)
        text, filtered = self._fit_budget(text, budget)
        return InjectionPlan(
            text=text,
            tokens_est=estimate_tokens(text),
            selected_ids=selected_ids if text else [],
            filtered=[*retrieval.filtered, *filtered],
            flashback=retrieval.flashback and bool(text),
            mirror_keys=[key for key, _ in mirror_slices] if text else [],
            recent_trace_ids=[trace.id for trace in recent_traces] if text else [],
        )

    def mirror_limit(self, scene: str) -> int:
        return int(SCENE_LIMITS.get(scene, SCENE_LIMITS["daily_chat"]).get("mirror_slices") or 0)

    def _memory_lines(self, items: list[MemoryItem]) -> list[str]:
        lines = []
        for item in items:
            rule = item.use_rule or "当前话题明显相关时才可轻轻使用。"
            lines.append(f"- {item.content} {rule}".strip())
        return lines

    def _recent_trace_block(self, traces: list[RecentTrace]) -> str:
        max_chars = int(self.config.get("recent_trace_inject_max_chars") or 800)
        prefix = (
            "<recent_continuity>\n"
            "最近24-72h线索；只在用户延续话题时自然参考，不要说“根据记录显示”。\n"
        )
        suffix = "\n</recent_continuity>"
        lines: list[str] = []
        for trace in traces:
            line = f"- {trace.topic}: {trace.summary}"
            if trace.user_state:
                line += f" {trace.user_state}"
            if trace.bot_residue:
                line += f" {trace.bot_residue}"
            candidate_lines = [*lines, line.strip()]
            candidate = prefix + "\n".join(candidate_lines) + suffix
            if len(candidate) <= max_chars:
                lines.append(line.strip())
            elif not lines:
                room = max(20, max_chars - len(prefix) - len(suffix) - 4)
                lines.append(line.strip()[:room] + "...")
                break
            else:
                break
        return prefix + "\n".join(lines) + suffix

    def _fit_budget(self, text: str, budget: int) -> tuple[str, list[str]]:
        if estimate_tokens(text) <= budget:
            return text, []
        lines = text.splitlines()
        kept: list[str] = []
        filtered: list[str] = []
        for line in lines:
            candidate = "\n".join([*kept, line])
            if estimate_tokens(candidate) <= budget:
                kept.append(line)
            else:
                filtered.append("over_budget")
        fitted = "\n".join(kept).strip()
        if estimate_tokens(fitted) > budget:
            return "", ["over_budget_empty"]
        return fitted, filtered
