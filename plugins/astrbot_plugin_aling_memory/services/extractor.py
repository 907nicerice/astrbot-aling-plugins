from __future__ import annotations

import re
from typing import Any

from ..models.memory_item import CandidateMemory, MemoryItem
from .defaults import DEFAULT_CONFIG


STRONG_SIGNALS = ["记住", "以后别", "我希望", "我不想", "以后不要", "以后可以", "别再", "我喜欢", "我讨厌"]


class Extractor:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}

    def should_extract_from_user_text(self, text: str) -> bool:
        return any(signal in text for signal in STRONG_SIGNALS)

    def extract_from_user_text(self, text: str) -> list[CandidateMemory]:
        if not self.should_extract_from_user_text(text):
            return []
        content = self._candidate_content(text)
        if not content:
            return []
        suggested_type = self._type_for(text)
        tags = self._tags_for(text)
        use_rule = self._use_rule_for(suggested_type)
        return [
            CandidateMemory.create(
                suggested_type,
                content,
                reason="用户消息包含明确长期偏好或记忆强信号。",
                confidence=0.9 if suggested_type == "preference_memory" else 0.82,
                tags=tags,
                use_rule=use_rule,
            )
        ]

    def extract_from_summary(self, summary: str) -> list[CandidateMemory]:
        text = summary.strip()
        if not text:
            return []
        if any(word in text for word in ("插件", "AstrBot", "prompt", "QQ bot", "token", "Napcat")):
            return [
                CandidateMemory.create(
                    "project_context",
                    "用户正在做阿绫 QQ bot，关注人格自然度、长期记忆、上下文压缩和 token 控制。",
                    reason="摘要中出现稳定项目背景。",
                    confidence=0.76,
                    tags=["project", "bot"],
                    use_rule="只有用户主动提到 bot、插件、prompt、AstrBot、QQ 空间、上下文或 token 时使用。",
                )
            ]
        return []

    def auto_confirmable(self, candidate: CandidateMemory) -> bool:
        return (
            bool(self.config.get("auto_confirm_safe_preferences"))
            and candidate.suggested_type == "preference_memory"
            and candidate.confidence >= 0.9
        )

    def _candidate_content(self, text: str) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        if not clean:
            return ""
        return f"用户表达过：{clean[:160]}"

    def _type_for(self, text: str) -> str:
        if any(word in text for word in ("短", "自然", "助手", "留白", "别", "希望", "喜欢", "讨厌")):
            return "preference_memory"
        if any(word in text for word in ("亲近", "边界", "表白", "关系", "偏心")):
            return "relationship_memory"
        if any(word in text for word in ("插件", "AstrBot", "prompt", "Napcat", "QQ空间", "token", "bot")):
            return "project_context"
        return "small_memory"

    def _tags_for(self, text: str) -> list[str]:
        tags: list[str] = []
        if any(word in text for word in ("课", "考试", "物理", "高数", "题")):
            tags.append("study")
        if any(word in text for word in ("插件", "AstrBot", "prompt", "bot", "token")):
            tags.append("project")
        if any(word in text for word in ("短", "自然", "助手", "留白")):
            tags.append("style")
        if "记住" in text or "记忆" in text:
            tags.append("memory")
        return tags or ["daily"]

    def _use_rule_for(self, suggested_type: str) -> str:
        if suggested_type == "project_context":
            return "只有用户主动提到项目、bot、插件、prompt、AstrBot 或 token 时使用。"
        if suggested_type == "preference_memory":
            return "自然影响回复风格，不要显式说在套用偏好。"
        return "只有当前话题明显相关时轻轻带一句，不要主动展开。"
