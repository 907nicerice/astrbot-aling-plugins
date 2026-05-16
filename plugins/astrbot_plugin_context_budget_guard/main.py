import json
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register


DEFAULT_CONFIG = {
    "enabled": True,
    "dry_run": True,
    "log_each_request": True,
    "debug_dump_request_fields": False,
    "warn_total_tokens": 8000,
    "system_prompt_warn_tokens": 5000,
    "contexts_warn_tokens": 3000,
    "extra_warn_tokens": 1000,
    "tools_warn_tokens": 1500,
    "single_message_warn_tokens": 2000,
    "long_json_warn_chars": 3000,
    "preview_chars": 80,
    "history_size": 20,
    "detect_base64": True,
    "detect_long_json": True,
    "detect_plugin_state": True,
    "enable_extra_trim": False,
    "max_extra_chars": 1200,
    "enable_context_trim": False,
    "keep_recent_messages": 12,
    "enable_base64_omit": False,
}

REQUEST_FIELDS = (
    "system_prompt",
    "prompt",
    "contexts",
    "extra_user_content_parts",
    "tools",
    "func_tool",
    "functions",
    "messages",
    "image_urls",
)

TOOL_FIELDS = {"tools", "func_tool", "functions"}
BASE64_OMIT_TEXT = "[image/base64 content omitted by ContextBudgetGuard]"
EXTRA_TRIM_TEXT = "[ContextBudgetGuard: extra content truncated]"
MAX_PREVIEW_SOURCE_CHARS = 5000
PLUGIN_STATE_KEYWORDS = (
    "affection",
    "好感",
    "攻击性",
    "力比多",
    "shared_life_context",
    "current_activity",
    "daily_plan",
    "proactive",
    "qzone",
    "self_learning",
    "memory",
    "knowledge",
)

BASE64_RE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{1500,}={0,2}(?![A-Za-z0-9+/])")
JSON_HINTS = ('"role"', '"content"', '"metadata"', '"tool_calls"', "'role'", "'content'")
CJK_RE = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\u3040-\u30ff\uac00-\ud7af]"
)


@dataclass
class ItemStat:
    index: int
    role: str
    chars: int
    estimated_tokens: int
    preview: str
    risk_flags: list[str] = field(default_factory=list)


@dataclass
class PartStat:
    name: str
    chars: int = 0
    estimated_tokens: int = 0
    items: int = 0
    risk_flags: list[str] = field(default_factory=list)
    top_items: list[ItemStat] = field(default_factory=list)


def safe_getattr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def object_to_preview_text(obj: Any, max_chars: int = MAX_PREVIEW_SOURCE_CHARS) -> str:
    try:
        if obj is None:
            text = ""
        elif isinstance(obj, str):
            text = obj
        elif isinstance(obj, bytes):
            text = f"<bytes: {len(obj)} bytes>"
        elif isinstance(obj, (list, dict, tuple)):
            text = json.dumps(obj, ensure_ascii=False, default=str)
        else:
            text = str(obj)
    except Exception:
        return f"<unserializable: {type(obj).__name__}>"

    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars]
    return text


def _object_to_count_text(obj: Any) -> str:
    return object_to_preview_text(obj, max_chars=None)


def contains_base64_like(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if (
        "data:image/" in lowered
        or "base64," in lowered
        or "image/png" in lowered
        or "image/jpeg" in lowered
        or "image/webp" in lowered
    ):
        return True

    for match in BASE64_RE.finditer(text):
        candidate = match.group(0)
        classes = 0
        classes += bool(re.search(r"[a-z]", candidate))
        classes += bool(re.search(r"[A-Z]", candidate))
        classes += bool(re.search(r"[0-9]", candidate))
        classes += bool(re.search(r"[+/=]", candidate))
        if classes >= 3:
            return True
    return False


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk_count = 0
    other_count = 0
    for char in text:
        if char.isspace():
            continue
        if CJK_RE.match(char):
            cjk_count += 1
        else:
            other_count += 1
    divisor = 3 if contains_base64_like(text) else 4
    return int(cjk_count + (other_count + divisor - 1) // divisor)


def _dedupe(flags: list[str]) -> list[str]:
    seen = set()
    result = []
    for flag in flags:
        if flag not in seen:
            result.append(flag)
            seen.add(flag)
    return result


def _safe_role(item: Any) -> str:
    if isinstance(item, dict):
        role = item.get("role") or item.get("type") or item.get("name")
    else:
        role = safe_getattr(item, "role") or safe_getattr(item, "type") or safe_getattr(item, "name")
    return str(role or "unknown")


def _message_content(item: Any) -> Any:
    if isinstance(item, dict):
        for key in ("content", "text", "message", "value"):
            if key in item:
                return item.get(key)
        return item
    for key in ("content", "text", "message", "value"):
        value = safe_getattr(item, key, None)
        if value is not None:
            return value
    return item


def _has_tool_pairing_risk(messages: list[Any]) -> bool:
    for item in messages:
        text = object_to_preview_text(item, max_chars=MAX_PREVIEW_SOURCE_CHARS).lower()
        role = _safe_role(item).lower()
        if role in {"tool", "function"}:
            return True
        if "tool_call" in text or "function_call" in text or '"tool_calls"' in text:
            return True
    return False


class BudgetAnalyzer:
    def __init__(self, cfg_getter):
        self.cfg = cfg_getter

    def risk_flags_for_text(self, text: str) -> list[str]:
        flags = []
        lowered = text.lower()
        stripped = text.lstrip()

        if self.cfg("detect_base64") and contains_base64_like(text):
            flags.append("base64_like_content")

        if self.cfg("detect_long_json"):
            json_threshold = int(self.cfg("long_json_warn_chars"))
            json_like = stripped.startswith("{") or stripped.startswith("[")
            hint_count = sum(text.count(hint) for hint in JSON_HINTS)
            if len(text) >= json_threshold and (json_like or hint_count >= 8):
                flags.append("long_json_like_content")

        if self.cfg("detect_plugin_state"):
            plugin_threshold = max(800, int(self.cfg("long_json_warn_chars")) // 2)
            if len(text) >= plugin_threshold:
                if any(keyword.lower() in lowered for keyword in PLUGIN_STATE_KEYWORDS):
                    flags.append("plugin_state_like_content")

        return flags

    def analyze_field(self, name: str, value: Any) -> PartStat:
        if isinstance(value, (list, tuple)):
            return self._analyze_sequence(name, list(value))

        text = _object_to_count_text(value)
        stat = PartStat(
            name=name,
            chars=len(text),
            estimated_tokens=estimate_tokens(text),
            items=0 if value is None else 1,
            risk_flags=self.risk_flags_for_text(text),
        )
        self._apply_field_thresholds(stat)
        return stat

    def _analyze_sequence(self, name: str, items: list[Any]) -> PartStat:
        stat = PartStat(name=name, items=len(items))
        item_stats: list[ItemStat] = []

        for index, item in enumerate(items):
            content = _message_content(item)
            text = _object_to_count_text(content)
            flags = self.risk_flags_for_text(text)
            tokens = estimate_tokens(text)
            chars = len(text)

            if tokens >= int(self.cfg("single_message_warn_tokens")):
                flags.append("single_message_too_large")

            item_stats.append(
                ItemStat(
                    index=index,
                    role=_safe_role(item),
                    chars=chars,
                    estimated_tokens=tokens,
                    preview=_truncate(
                        object_to_preview_text(content, max_chars=MAX_PREVIEW_SOURCE_CHARS).replace("\n", "\\n"),
                        int(self.cfg("preview_chars")),
                    ),
                    risk_flags=_dedupe(flags),
                )
            )
            stat.chars += chars
            stat.estimated_tokens += tokens
            stat.risk_flags.extend(flags)

        stat.risk_flags = _dedupe(stat.risk_flags)
        stat.top_items = sorted(item_stats, key=lambda item: item.estimated_tokens, reverse=True)[:3]
        self._apply_field_thresholds(stat)
        return stat

    def _apply_field_thresholds(self, stat: PartStat) -> None:
        if stat.name == "system_prompt" and stat.estimated_tokens >= int(self.cfg("system_prompt_warn_tokens")):
            stat.risk_flags.append("system_prompt_too_large")
        elif stat.name == "contexts" and stat.estimated_tokens >= int(self.cfg("contexts_warn_tokens")):
            stat.risk_flags.append("contexts_too_large")
        elif stat.name == "extra_user_content_parts" and stat.estimated_tokens >= int(self.cfg("extra_warn_tokens")):
            stat.risk_flags.append("extra_too_large")
        elif stat.name in TOOL_FIELDS and stat.estimated_tokens >= int(self.cfg("tools_warn_tokens")):
            stat.risk_flags.append("tools_too_large")

        stat.risk_flags = _dedupe(stat.risk_flags)


@register(
    "astrbot_plugin_context_budget_guard",
    "sandriver",
    "Diagnose and guard LLM request token budget before model calls.",
    "0.1.0",
    "",
)
class ContextBudgetGuardPlugin(Star):
    def __init__(self, context: Context, config: Any = None):
        super().__init__(context)
        self.config = config or {}
        self.history: deque[dict[str, Any]] = deque(maxlen=int(self.cfg("history_size")))
        self.analyzer = BudgetAnalyzer(self.cfg)

    def cfg(self, name: str) -> Any:
        try:
            if isinstance(self.config, dict) and name in self.config:
                return self.config[name]
            value = self.config.get(name, DEFAULT_CONFIG.get(name))  # AstrBotConfig is dict-like.
            if value is not None:
                return value
        except Exception:
            pass
        return DEFAULT_CONFIG.get(name)

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        try:
            if not bool(self.cfg("enabled")):
                return

            if bool(self.cfg("debug_dump_request_fields")):
                self._log_request_field_names(req)

            parts = self._analyze_request(req)
            total_tokens = sum(part.estimated_tokens for part in parts.values())
            total_chars = sum(part.chars for part in parts.values())
            flags = self._collect_flags(parts, total_tokens)
            session = self._session_id(event)
            record = self._make_history_record(session, total_tokens, total_chars, flags, parts)
            self._append_history(record)

            if bool(self.cfg("log_each_request")) or flags:
                self._log_summary(record, parts, flags)

            self._maybe_apply_trims(req, flags)
        except Exception as exc:
            logger.error(f"[ContextBudgetGuard] failed to inspect LLM request: {type(exc).__name__}: {exc}")

    @filter.command("cbg")
    async def cbg(self, event: AstrMessageEvent, subcommand: str = "status", value: str = ""):
        """Context Budget Guard status/report/dryrun."""
        try:
            subcommand = (subcommand or "status").strip().lower()
            value = (value or "").strip().lower()

            if subcommand == "report":
                yield event.plain_result(self._render_report())
                return

            if subcommand == "dryrun":
                if value not in {"on", "off"}:
                    yield event.plain_result("用法：/cbg dryrun on 或 /cbg dryrun off")
                    return
                enabled = value == "on"
                self._set_config_value("dry_run", enabled)
                yield event.plain_result(f"ContextBudgetGuard dry_run 已设置为 {str(enabled).lower()}。")
                return

            yield event.plain_result(self._render_status())
        except Exception as exc:
            logger.error(f"[ContextBudgetGuard] command failed: {type(exc).__name__}: {exc}")
            yield event.plain_result("ContextBudgetGuard 执行失败，详情请查看 AstrBot 日志。")

    def _analyze_request(self, req: ProviderRequest) -> dict[str, PartStat]:
        parts: dict[str, PartStat] = {}
        for name in REQUEST_FIELDS:
            value = safe_getattr(req, name, None)
            parts[name] = self.analyzer.analyze_field(name, value)

        unknown = self._analyze_unknown_fields(req)
        if unknown.items or unknown.chars:
            parts["unknown_extra_fields"] = unknown
        return parts

    def _analyze_unknown_fields(self, req: ProviderRequest) -> PartStat:
        names = []
        try:
            names = [name for name in vars(req).keys() if name not in REQUEST_FIELDS and not name.startswith("_")]
        except Exception:
            names = []

        stat = PartStat(name="unknown_extra_fields", items=len(names))
        top_items: list[ItemStat] = []
        for index, name in enumerate(sorted(names)[:30]):
            value = safe_getattr(req, name, None)
            if callable(value):
                continue
            text = _object_to_count_text(value)
            tokens = estimate_tokens(text)
            flags = self.analyzer.risk_flags_for_text(text)
            stat.chars += len(text)
            stat.estimated_tokens += tokens
            stat.risk_flags.extend(flags)
            top_items.append(
                ItemStat(
                    index=index,
                    role=name,
                    chars=len(text),
                    estimated_tokens=tokens,
                    preview=_truncate(
                        object_to_preview_text(value, max_chars=MAX_PREVIEW_SOURCE_CHARS).replace("\n", "\\n"),
                        int(self.cfg("preview_chars")),
                    ),
                    risk_flags=_dedupe(flags),
                )
            )
        stat.top_items = sorted(top_items, key=lambda item: item.estimated_tokens, reverse=True)[:3]
        stat.risk_flags = _dedupe(stat.risk_flags)
        return stat

    def _collect_flags(self, parts: dict[str, PartStat], total_tokens: int) -> list[str]:
        flags = []
        if total_tokens >= int(self.cfg("warn_total_tokens")):
            flags.append("total_too_large")
        for part in parts.values():
            flags.extend(part.risk_flags)
        return _dedupe(flags)

    def _make_history_record(
        self,
        session: str,
        total_tokens: int,
        total_chars: int,
        flags: list[str],
        parts: dict[str, PartStat],
    ) -> dict[str, Any]:
        return {
            "session": session,
            "total_est_tokens": total_tokens,
            "total_chars": total_chars,
            "risk_flags": flags,
            "parts": {
                name: {
                    "tokens": part.estimated_tokens,
                    "chars": part.chars,
                    "items": part.items,
                    "risk_flags": part.risk_flags,
                    "top_items": [
                        {
                            "index": item.index,
                            "role": item.role,
                            "tokens": item.estimated_tokens,
                            "chars": item.chars,
                            "preview": item.preview,
                            "risk_flags": item.risk_flags,
                        }
                        for item in part.top_items
                    ],
                }
                for name, part in parts.items()
            },
        }

    def _append_history(self, record: dict[str, Any]) -> None:
        target_size = max(1, int(self.cfg("history_size")))
        if self.history.maxlen != target_size:
            self.history = deque(list(self.history)[-target_size:], maxlen=target_size)
        self.history.appendleft(record)

    def _log_summary(self, record: dict[str, Any], parts: dict[str, PartStat], flags: list[str]) -> None:
        lines = [
            "[ContextBudgetGuard] "
            f"session={record['session']} "
            f"total_est_tokens={record['total_est_tokens']} "
            f"total_chars={record['total_chars']}"
        ]
        for name in (*REQUEST_FIELDS, "unknown_extra_fields"):
            part = parts.get(name)
            if not part:
                continue
            item_suffix = f" / items={part.items}" if part.items else ""
            lines.append(f"  {name}: {part.estimated_tokens} tok / {part.chars} chars{item_suffix}")
            for item in part.top_items:
                if item.risk_flags or item.estimated_tokens >= int(self.cfg("single_message_warn_tokens")):
                    lines.append(
                        "    "
                        f"top index={item.index} role={item.role} "
                        f"{item.estimated_tokens} tok / {item.chars} chars "
                        f"flags={item.risk_flags} preview=\"{item.preview}\""
                    )
        lines.append(f"  risk_flags={flags}")
        message = "\n".join(lines)
        if flags:
            logger.warning(message)
        else:
            logger.info(message)

    def _render_status(self) -> str:
        latest = self.history[0] if self.history else None
        latest_total = latest["total_est_tokens"] if latest else "N/A"
        latest_flags = latest["risk_flags"] if latest else []
        return (
            "ContextBudgetGuard 状态\n"
            f"enabled={bool(self.cfg('enabled'))}\n"
            f"dry_run={bool(self.cfg('dry_run'))}\n"
            f"log_each_request={bool(self.cfg('log_each_request'))}\n"
            f"warn_total_tokens={self.cfg('warn_total_tokens')}\n"
            f"system_prompt_warn_tokens={self.cfg('system_prompt_warn_tokens')}\n"
            f"contexts_warn_tokens={self.cfg('contexts_warn_tokens')}\n"
            f"extra_warn_tokens={self.cfg('extra_warn_tokens')}\n"
            f"tools_warn_tokens={self.cfg('tools_warn_tokens')}\n"
            f"single_message_warn_tokens={self.cfg('single_message_warn_tokens')}\n"
            f"recent_history={len(self.history)}/{self.cfg('history_size')}\n"
            f"last_total_est_tokens={latest_total}\n"
            f"last_risk_flags={latest_flags}"
        )

    def _render_report(self) -> str:
        if not self.history:
            return "ContextBudgetGuard 暂无请求统计。先触发一次普通对话后再查看 /cbg report。"

        records = list(self.history)[:10]
        lines = ["ContextBudgetGuard 最近请求摘要"]
        source_totals: dict[str, list[int]] = {}
        for idx, record in enumerate(records, start=1):
            parts = record["parts"]
            for source, stat in parts.items():
                source_totals.setdefault(source, []).append(int(stat.get("tokens", 0)))
            lines.append(
                f"#{idx} total={record['total_est_tokens']} "
                f"system={self._part_tokens(parts, 'system_prompt')} "
                f"contexts={self._part_tokens(parts, 'contexts')} "
                f"extra={self._part_tokens(parts, 'extra_user_content_parts')} "
                f"tools={self._part_tokens(parts, 'tools') + self._part_tokens(parts, 'func_tool') + self._part_tokens(parts, 'functions')} "
                f"flags={','.join(record['risk_flags']) or 'none'}"
            )

        averages = []
        for source, values in source_totals.items():
            if values:
                averages.append((source, sum(values) // len(values)))
        averages.sort(key=lambda item: item[1], reverse=True)

        lines.append("")
        lines.append("Top sources:")
        for idx, (source, avg_tokens) in enumerate(averages[:5], start=1):
            lines.append(f"{idx}. {source} avg {avg_tokens} tokens")
        return "\n".join(lines)

    @staticmethod
    def _part_tokens(parts: dict[str, Any], name: str) -> int:
        return int(parts.get(name, {}).get("tokens", 0))

    def _set_config_value(self, name: str, value: Any) -> None:
        try:
            self.config[name] = value
            save_config = safe_getattr(self.config, "save_config", None)
            if callable(save_config):
                save_config()
        except Exception as exc:
            logger.error(f"[ContextBudgetGuard] failed to save config {name}: {type(exc).__name__}: {exc}")

    def _log_request_field_names(self, req: ProviderRequest) -> None:
        try:
            useful = []
            for name in dir(req):
                if name.startswith("_"):
                    continue
                value = safe_getattr(req, name, None)
                if callable(value):
                    continue
                useful.append(name)
            logger.debug(f"[ContextBudgetGuard] ProviderRequest fields={sorted(useful)}")
        except Exception as exc:
            logger.error(f"[ContextBudgetGuard] failed to dump request fields: {type(exc).__name__}: {exc}")

    def _session_id(self, event: AstrMessageEvent) -> str:
        for attr in ("get_session_id", "get_sender_id", "get_group_id"):
            func = safe_getattr(event, attr, None)
            if callable(func):
                try:
                    value = func()
                    if value:
                        return _truncate(str(value), 32)
                except Exception:
                    pass
        for attr in ("session_id", "unified_msg_origin"):
            value = safe_getattr(event, attr, None)
            if value:
                return _truncate(str(value), 32)
        return "unknown"

    def _maybe_apply_trims(self, req: ProviderRequest, flags: list[str]) -> None:
        if bool(self.cfg("dry_run")):
            return

        if bool(self.cfg("enable_base64_omit")) and "base64_like_content" in flags:
            self._omit_base64_from_safe_fields(req)

        if bool(self.cfg("enable_extra_trim")):
            self._trim_extra_user_content(req)

        if bool(self.cfg("enable_context_trim")):
            self._trim_contexts(req)

    def _omit_base64_from_safe_fields(self, req: ProviderRequest) -> None:
        try:
            for name in ("prompt",):
                value = safe_getattr(req, name, None)
                if isinstance(value, str) and contains_base64_like(value):
                    setattr(req, name, self._replace_base64(value))

            extra = safe_getattr(req, "extra_user_content_parts", None)
            if isinstance(extra, list):
                for item in extra:
                    self._replace_text_attr_or_dict_value(item)
        except Exception as exc:
            logger.error(f"[ContextBudgetGuard] base64 omit failed: {type(exc).__name__}: {exc}")

    def _replace_text_attr_or_dict_value(self, item: Any) -> None:
        if isinstance(item, dict):
            for key in ("text", "content"):
                value = item.get(key)
                if isinstance(value, str) and contains_base64_like(value):
                    item[key] = self._replace_base64(value)
            return
        for key in ("text", "content"):
            value = safe_getattr(item, key, None)
            if isinstance(value, str) and contains_base64_like(value):
                try:
                    setattr(item, key, self._replace_base64(value))
                except Exception:
                    pass

    @staticmethod
    def _replace_base64(text: str) -> str:
        text = re.sub(r"data:image/[^,\s]+,?[A-Za-z0-9+/=\s]+", BASE64_OMIT_TEXT, text)
        text = BASE64_RE.sub(BASE64_OMIT_TEXT, text)
        return text

    def _trim_extra_user_content(self, req: ProviderRequest) -> None:
        try:
            extra = safe_getattr(req, "extra_user_content_parts", None)
            max_chars = max(0, int(self.cfg("max_extra_chars")))
            if isinstance(extra, str):
                if len(extra) > max_chars:
                    setattr(req, "extra_user_content_parts", extra[:max_chars] + "\n" + EXTRA_TRIM_TEXT)
                return
            if not isinstance(extra, list):
                return

            remaining = max_chars
            for index, item in enumerate(extra):
                if isinstance(item, str):
                    if len(item) <= remaining:
                        remaining -= len(item)
                        continue
                    extra[index] = item[: max(0, remaining)] + "\n" + EXTRA_TRIM_TEXT
                    del extra[index + 1 :]
                    return

                text_value, setter = self._extract_mutable_text(item)
                if text_value is None or setter is None:
                    continue
                if len(text_value) <= remaining:
                    remaining -= len(text_value)
                    continue
                setter(text_value[: max(0, remaining)] + "\n" + EXTRA_TRIM_TEXT)
                del extra[index + 1 :]
                return
        except Exception as exc:
            logger.error(f"[ContextBudgetGuard] extra trim failed: {type(exc).__name__}: {exc}")

    def _extract_mutable_text(self, item: Any):
        if isinstance(item, str):
            return None, None
        if isinstance(item, dict):
            for key in ("text", "content"):
                if isinstance(item.get(key), str):
                    return item[key], lambda value, target=item, field=key: target.__setitem__(field, value)
            return None, None
        for key in ("text", "content"):
            value = safe_getattr(item, key, None)
            if isinstance(value, str):
                return value, lambda new_value, target=item, field=key: setattr(target, field, new_value)
        return None, None

    def _trim_contexts(self, req: ProviderRequest) -> None:
        try:
            contexts = safe_getattr(req, "contexts", None)
            if not isinstance(contexts, list):
                return
            if _has_tool_pairing_risk(contexts):
                logger.warning("[ContextBudgetGuard] skip context trim because tool/function pairing may exist")
                return

            keep_recent = max(1, int(self.cfg("keep_recent_messages")))
            system_messages = [item for item in contexts if _safe_role(item).lower() == "system"]
            non_system = [item for item in contexts if _safe_role(item).lower() != "system"]
            trimmed = system_messages + non_system[-keep_recent:]
            if len(trimmed) < len(contexts):
                setattr(req, "contexts", trimmed)
        except Exception as exc:
            logger.error(f"[ContextBudgetGuard] context trim failed: {type(exc).__name__}: {exc}")

    async def terminate(self):
        pass
