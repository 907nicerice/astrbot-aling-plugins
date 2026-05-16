from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..models.recent_trace import RecentTrace
from .defaults import DEFAULT_CONFIG, PLUGIN_NAME
from .json_store import JsonFile
from .text_utils import normalize_text, unique_keep_order

logger = logging.getLogger(PLUGIN_NAME)

RECENT_RECALL_TRIGGERS = [
    "昨天",
    "昨晚",
    "前天",
    "刚才",
    "刚刚",
    "前面",
    "上次",
    "之前",
    "继续",
    "接着",
    "你忘了",
    "还记得",
    "说到哪",
    "那个方案",
    "那个插件",
    "刚才那个",
    "memory",
    "截断",
    "recent_trace",
]

WRITE_SIGNALS = [
    "项目",
    "插件",
    "方案",
    "故障",
    "问题",
    "排查",
    "昨天",
    "昨晚",
    "刚才",
    "继续",
    "接着",
    "prompt",
    "memory",
    "截断",
    "AstrBot",
    "Napcat",
    "token",
]

STOP_HINTS = {"这个", "那个", "一下", "我们", "你们", "以及", "然后", "就是", "可以", "应该"}


class RecentTraceService:
    def __init__(self, data_dir: Path, config: dict[str, Any] | None = None) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.file = JsonFile(data_dir / "recent_trace.json", {"version": 1, "sessions": {}})

    def save_from_turn(self, session_id: str, user_text: str, bot_text: str) -> RecentTrace | None:
        if not self.config.get("recent_trace_enabled", True):
            return None
        try:
            user_text = normalize_text(user_text)
            bot_text = normalize_text(bot_text)
            if not self._should_save(user_text, bot_text):
                return None
            trace = RecentTrace.create(
                session_id=session_id,
                topic=self._topic(user_text, bot_text),
                summary=self._summary(user_text, bot_text),
                user_state=self._user_state(user_text),
                bot_residue="Keep a light sense of continuity if the user brings this up again; do not sound like reading logs.",
                recall_hints=self._hints(user_text, bot_text),
                importance=self._importance(user_text, bot_text),
                ttl_hours=int(self.config.get("recent_trace_ttl_hours") or 72),
            )
            root = self._root()
            session = self._session(root, session_id)
            if self._is_duplicate(session["items"], trace):
                return None
            session["items"].append(trace.to_dict())
            self._cleanup_root(root, session_id=session_id)
            self.file.save(root)
            logger.info(
                "[aling_memory][recent_trace] saved session=%s topic=%s importance=%.2f expires_at=%s",
                session_id,
                trace.topic,
                trace.importance,
                trace.expires_at,
            )
            return trace
        except Exception:
            logger.warning("[aling_memory][recent_trace] save failed session=%s", session_id, exc_info=True)
            return None

    def add_trace(self, session_id: str, trace: RecentTrace) -> RecentTrace:
        root = self._root()
        session = self._session(root, session_id)
        session["items"].append(trace.to_dict())
        self._cleanup_root(root, session_id=session_id)
        self.file.save(root)
        return trace

    def list_traces(self, session_id: str) -> list[RecentTrace]:
        root = self._root()
        self._cleanup_root(root, session_id=session_id)
        self.file.save(root)
        return [RecentTrace.from_dict(item) for item in self._session(root, session_id)["items"]]

    def clear(self, session_id: str) -> int:
        root = self._root()
        sessions = root.setdefault("sessions", {})
        count = len((sessions.get(session_id) or {}).get("items") or [])
        sessions.pop(session_id, None)
        self.file.save(root)
        logger.info("[aling_memory][recent_trace] clear session=%s traces=%s", session_id, count)
        return count

    def retrieve(self, session_id: str, query: str) -> list[RecentTrace]:
        if not self.config.get("recent_trace_enabled", True):
            return []
        try:
            query = normalize_text(query)
            traces = self.list_traces(session_id)
            min_importance = float(self.config.get("recent_trace_min_importance") or 0.35)
            scored: list[tuple[float, RecentTrace]] = []
            for trace in traces:
                if trace.importance < min_importance:
                    continue
                score = self._score(trace, query)
                if score > 0:
                    scored.append((score, trace))
            scored.sort(key=lambda item: item[0], reverse=True)
            selected = self._limit_chars(
                [trace for _, trace in scored],
                int(self.config.get("recent_trace_inject_max_items") or 3),
                int(self.config.get("recent_trace_inject_max_chars") or 800),
            )
            logger.info(
                "[aling_memory][recent_trace] query session=%s matched=%s injected_chars=%s",
                session_id,
                len(selected),
                sum(len(self.render_line(trace)) for trace in selected),
            )
            return selected
        except Exception:
            logger.warning("[aling_memory][recent_trace] retrieve failed session=%s", session_id, exc_info=True)
            return []

    def render_block(self, traces: list[RecentTrace]) -> str:
        if not traces:
            return ""
        lines = [self.render_line(trace) for trace in traces]
        return (
            "<recent_continuity>\n"
            "这些是最近 24-72 小时内的轻量连续性线索，只用于帮助你自然接上话题。\n"
            "不要复述记录，不要说“根据记录显示”，不要主动总结。只有当用户正在延续相关话题时，才自然参考。\n\n"
            + "\n".join(lines)
            + "\n</recent_continuity>"
        )

    def render_line(self, trace: RecentTrace) -> str:
        parts = [trace.summary]
        if trace.user_state:
            parts.append(trace.user_state)
        if trace.bot_residue:
            parts.append(trace.bot_residue)
        return f"- {trace.topic}: " + " ".join(parts)

    def _root(self) -> dict[str, Any]:
        data = self.file.load()
        data.setdefault("version", 1)
        data.setdefault("sessions", {})
        return data

    def _session(self, root: dict[str, Any], session_id: str) -> dict[str, Any]:
        session = root.setdefault("sessions", {}).setdefault(session_id, {"items": []})
        session.setdefault("items", [])
        return session

    def _cleanup_root(self, root: dict[str, Any], session_id: str | None = None) -> int:
        sessions = root.setdefault("sessions", {})
        ids = [session_id] if session_id else list(sessions)
        max_items = int(self.config.get("recent_trace_max_items_per_session") or 50)
        removed = 0
        for sid in ids:
            session = sessions.setdefault(sid, {"items": []})
            before = len(session.get("items") or [])
            items = [RecentTrace.from_dict(item) for item in session.get("items") or []]
            items = [item for item in items if not item.is_expired()]
            items.sort(key=lambda item: item.created_at)
            if len(items) > max_items:
                items = items[-max_items:]
            session["items"] = [item.to_dict() for item in items]
            removed += before - len(session["items"])
        if removed:
            logger.info("[aling_memory][recent_trace] cleanup removed=%s", removed)
        return removed

    def _should_save(self, user_text: str, bot_text: str) -> bool:
        if len(user_text) <= 4:
            return False
        if user_text.startswith("/mem"):
            return False
        if self._has_signal(user_text) or self._has_signal(bot_text):
            return True
        if len(user_text) >= 48:
            return True
        if any(word in bot_text for word in ("方案", "结论", "步骤", "计划", "修复", "实现", "排查")):
            return True
        return False

    def _has_signal(self, text: str) -> bool:
        return any(word.lower() in text.lower() for word in WRITE_SIGNALS)

    def _topic(self, user_text: str, bot_text: str) -> str:
        hints = self._hints(user_text, bot_text)
        if hints:
            return " / ".join(hints[:4])[:80]
        return user_text[:36] or "recent conversation"

    def _summary(self, user_text: str, bot_text: str) -> str:
        user_part = user_text[:110]
        bot_part = bot_text[:110]
        if bot_part:
            return f"User brought up {user_part}; reply focused on {bot_part}."
        return f"User brought up {user_part}."

    def _user_state(self, user_text: str) -> str:
        if any(word in user_text for word in ("问题", "故障", "报错", "排查", "忘了", "截断")):
            return "用户正在排查一个需要短期连续性的上下文问题。"
        if any(word in user_text for word in ("继续", "接着", "昨天", "刚才")):
            return "用户正在延续最近一两天内的话题。"
        return "用户可能希望下次能自然接上这个话题。"

    def _hints(self, user_text: str, bot_text: str) -> list[str]:
        text = f"{user_text} {bot_text}"
        hints: list[str] = []
        for trigger in RECENT_RECALL_TRIGGERS + WRITE_SIGNALS:
            if trigger.lower() in text.lower():
                hints.append(trigger)
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,6}", text):
            if token not in STOP_HINTS and len(token) >= 2:
                hints.append(token)
        return unique_keep_order(hints)[:12]

    def _importance(self, user_text: str, bot_text: str) -> float:
        score = 0.35
        if self._has_signal(user_text):
            score += 0.2
        if len(user_text) >= 48:
            score += 0.15
        if any(word in user_text for word in ("报错", "故障", "方案", "继续", "昨天", "忘了", "截断")):
            score += 0.15
        if any(word in bot_text for word in ("方案", "结论", "修复", "实现")):
            score += 0.1
        return min(1.0, score)

    def _score(self, trace: RecentTrace, query: str) -> float:
        lower = query.lower()
        trigger_bonus = 1.5 if any(trigger.lower() in lower for trigger in RECENT_RECALL_TRIGGERS) else 0.0
        overlap = 0
        for hint in trace.recall_hints:
            if hint and hint.lower() in lower:
                overlap += 1
        if overlap == 0 and trigger_bonus <= 0:
            return 0.0
        recency_bonus = max(0.0, 1.0 - trace.age_hours() / max(1, int(self.config.get("recent_trace_ttl_hours") or 72)))
        return overlap * 2.0 + trigger_bonus + trace.importance + recency_bonus

    def _limit_chars(self, traces: list[RecentTrace], max_items: int, max_chars: int) -> list[RecentTrace]:
        selected: list[RecentTrace] = []
        total = 0
        for trace in traces:
            line_len = len(self.render_line(trace))
            if len(selected) >= max_items:
                break
            if selected and total + line_len > max_chars:
                break
            if not selected and line_len > max_chars:
                shortened = RecentTrace.from_dict(trace.to_dict())
                shortened.summary = shortened.summary[: max(40, max_chars - len(shortened.topic) - 80)]
                selected.append(shortened)
                break
            selected.append(trace)
            total += line_len
        return selected


def expired_trace_for_test(session_id: str, topic: str = "expired") -> RecentTrace:
    trace = RecentTrace.create(session_id, topic, "expired summary", recall_hints=[topic], ttl_hours=1)
    trace.expires_at = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0).isoformat()
    return trace
