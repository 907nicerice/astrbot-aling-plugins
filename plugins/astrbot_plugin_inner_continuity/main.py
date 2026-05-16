from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, AsyncGenerator

try:
    from astrbot.api.event import AstrMessageEvent, filter
    from astrbot.api.star import Context, Star, register
except Exception:  # pragma: no cover - local compile/test fallback
    AstrMessageEvent = Any
    Context = Any

    class _FilterFallback:
        @staticmethod
        def command(*args: Any, **kwargs: Any) -> Any:
            def deco(fn: Any) -> Any:
                return fn

            return deco

        @staticmethod
        def on_llm_request(*args: Any, **kwargs: Any) -> Any:
            def deco(fn: Any) -> Any:
                return fn

            return deco

        @staticmethod
        def on_llm_response(*args: Any, **kwargs: Any) -> Any:
            def deco(fn: Any) -> Any:
                return fn

            return deco

    filter = _FilterFallback()

    class Star:  # type: ignore[no-redef]
        def __init__(self, context: Any = None) -> None:
            self.context = context

    def register(*args: Any, **kwargs: Any) -> Any:
        def deco(cls: Any) -> Any:
            return cls

        return deco

try:
    from astrbot.api.provider import LLMResponse, ProviderRequest
except Exception:  # pragma: no cover - AstrBot has moved these between versions
    LLMResponse = Any
    ProviderRequest = Any


PLUGIN_NAME = "astrbot_plugin_inner_continuity"
logger = logging.getLogger(PLUGIN_NAME)

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "inject_enabled": True,
    "update_enabled": True,
    "use_llm_update": True,
    "read_shared_life_context": True,
    "max_residue_items": 5,
    "max_micro_details": 6,
    "max_flashback_candidates": 4,
    "default_ttl_minutes": 180,
    "strong_ttl_minutes": 720,
    "max_injected_chars": 900,
    "min_update_interval_seconds": 60,
    "flashback_cooldown_seconds": 300,
    "debug": False,
}

DEFAULT_STATE: dict[str, Any] = {
    "schema_version": 1,
    "updated_at": 0,
    "last_update_attempt_at": 0,
    "mood_hint": {
        "label": "平静",
        "energy": "中",
        "expression_tendency": "正常",
    },
    "residue": [],
    "micro_details": [],
    "flashback_candidates": [],
    "cooldown": {
        "last_injected_at": 0,
        "last_used_flashback_at": 0,
    },
}

SHORT_GREETING_RE = re.compile(r"^(阿绫|aling|hi|hello|嗨|哈喽|在吗|嗯|哦|好|？|\?|。|\.|,|，|喂)$", re.I)
UPDATE_KEYWORDS = (
    "我想",
    "我怕",
    "我担心",
    "担心",
    "之前",
    "刚才",
    "刚刚",
    "记住",
    "token",
    "插件",
    "prompt",
    "效果",
    "闪回",
    "小细节",
    "注入",
    "检索",
    "memory",
    "aling_memory",
    "shared_life_context",
    "slc",
    "Inner Continuity",
    "affective",
)


@register(
    "astrbot_plugin_inner_continuity",
    "Codex",
    "Inner Continuity Engine / 阿绫短期内在连续性与闪回缓存",
    "0.1.0",
)
class InnerContinuityPlugin(Star):
    def __init__(self, context: Context, config: Any = None) -> None:
        super().__init__(context)
        self.config = self._merge_config(config)
        plugin_dir = Path(__file__).resolve().parent
        self.data_root = resolve_data_dir(context, plugin_dir)
        self.state_dir = self.data_root / "data" / "inner_continuity"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._pending_user_text: dict[str, str] = {}

    @filter.command("inner")
    async def inner(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        try:
            scope_id = scope_from_event(event)
            reply = self._cmd_inner(scope_id)
        except Exception:
            logger.exception("[inner_continuity] /inner failed")
            reply = "Inner Continuity 刚刚读取状态失败，已经写入日志。"
        yield event.plain_result(reply)

    @filter.command("inner_clear")
    async def inner_clear(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        try:
            scope_id = scope_from_event(event)
            self.save_state(scope_id, deepcopy(DEFAULT_STATE))
            reply = "已清空当前用户的 Inner Continuity 状态。"
        except Exception:
            logger.exception("[inner_continuity] /inner_clear failed")
            reply = "清空失败，已经写入日志。"
        yield event.plain_result(reply)

    @filter.command("inner_debug")
    async def inner_debug(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        try:
            raw = extract_text(event=event)
            value = raw.replace("/inner_debug", "", 1).strip().lower()
            if value not in {"on", "off"}:
                reply = "用法：/inner_debug on 或 /inner_debug off"
            else:
                self.config["debug"] = value == "on"
                reply = "Inner Continuity debug 已开启。" if value == "on" else "Inner Continuity debug 已关闭。"
        except Exception:
            logger.exception("[inner_continuity] /inner_debug failed")
            reply = "debug 设置失败，已经写入日志。"
        yield event.plain_result(reply)

    @filter.command("inner_dump")
    async def inner_dump(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        try:
            if not is_admin_event(event):
                reply = "只有管理员可以使用 /inner_dump。"
            else:
                scope_id = scope_from_event(event)
                state = self.load_state(scope_id)
                reply = json.dumps(state, ensure_ascii=False, indent=2)
        except Exception:
            logger.exception("[inner_continuity] /inner_dump failed")
            reply = "dump 失败，已经写入日志。"
        yield event.plain_result(reply)

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        try:
            if not self.config.get("enabled", True):
                return
            scope_id = scope_from_event(event)
            user_text = extract_text(event=event, req=req)
            if user_text:
                self._pending_user_text[scope_id] = user_text
            if not self.config.get("inject_enabled", True):
                return
            state = self.load_state(scope_id)
            rendered, used_ids = self.render_injection(scope_id, state, user_text)
            if not rendered:
                return
            ok = inject_temporary_text(req, rendered)
            if ok:
                self._mark_injected(scope_id, state, used_ids)
                if self.config.get("debug"):
                    logger.info("[inner_continuity] injected temporary context chars=%s", len(rendered))
        except Exception:
            logger.warning("[inner_continuity] on_llm_request failed", exc_info=True)

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp: LLMResponse) -> None:
        try:
            if not self.config.get("enabled", True) or not self.config.get("update_enabled", True):
                return
            scope_id = scope_from_event(event)
            user_text = self._pending_user_text.pop(scope_id, "") or extract_text(event=event)
            bot_text = extract_response_text(resp)
            if not user_text or is_trivial_user_text(user_text):
                return
            state = self.load_state(scope_id)
            now = now_ts()
            min_interval = int(self.config.get("min_update_interval_seconds") or 0)
            last_attempt = int(state.get("last_update_attempt_at") or 0)
            if min_interval > 0 and now - last_attempt < min_interval:
                if self.config.get("debug"):
                    logger.info("[inner_continuity] skipped update: min interval")
                return
            state["last_update_attempt_at"] = now
            self.save_state(scope_id, state)
            asyncio.create_task(self._update_state_after_response(scope_id, user_text, bot_text))
        except Exception:
            logger.warning("[inner_continuity] on_llm_response failed", exc_info=True)

    async def _update_state_after_response(self, scope_id: str, user_text: str, bot_text: str) -> None:
        try:
            state = self.load_state(scope_id)
            result: dict[str, Any] | None = None
            if self.config.get("use_llm_update", True):
                result = await self._try_llm_update(state, user_text, bot_text)
            if not result:
                result = self._rule_fallback_update(user_text)
            if not result:
                return
            self.apply_update(scope_id, state, result)
        except Exception:
            logger.warning("[inner_continuity] update task failed", exc_info=True)

    async def _try_llm_update(self, state: dict[str, Any], user_text: str, bot_text: str) -> dict[str, Any] | None:
        prompt = self._build_update_prompt(state, user_text, bot_text)
        provider = get_provider(self.context)
        if inspect.isawaitable(provider):
            provider = await provider
        if provider is None:
            return None
        response: Any = None
        for method_name in ("text_chat", "chat", "generate", "ask", "completion"):
            method = getattr(provider, method_name, None)
            if not callable(method):
                continue
            try:
                response = method(prompt)
                if inspect.isawaitable(response):
                    response = await response
                break
            except Exception:
                logger.warning("[inner_continuity] provider method %s failed", method_name, exc_info=True)
                return None
        text = extract_response_text(response) if response is not None else ""
        if not text and isinstance(response, str):
            text = response
        parsed = parse_json_object(text)
        return parsed if isinstance(parsed, dict) else None

    def _build_update_prompt(self, state: dict[str, Any], user_text: str, bot_text: str) -> str:
        slc = self._read_shared_life_context_summary() if self.config.get("read_shared_life_context", True) else {}
        summary = {
            "mood_hint": state.get("mood_hint") or {},
            "residue": [item.get("text", "") for item in state.get("residue", [])[:3]],
            "micro_details": [item.get("text", "") for item in state.get("micro_details", [])[:3]],
            "flashback_candidates": [item.get("text", "") for item in state.get("flashback_candidates", [])[:3]],
        }
        return (
            "你是 Inner Continuity Engine 的状态更新器。\n"
            "你的任务不是生成回复，而是根据最近一轮对话，更新阿绫的短期内在连续性。\n\n"
            "请提取：\n"
            "1. residue：这几轮对话后阿绫可能还挂着的残留感。\n"
            "2. micro_details：不值得进入长期记忆、但接下来几轮可能自然回勾的小细节。\n"
            "3. flashback_candidates：可以自然带出的短句闪回素材。\n"
            "4. mood_hint：轻量情绪/表达倾向。\n\n"
            "要求：\n"
            "- 只记录短期内容，不记录长期事实。\n"
            "- 不要写好感度、恋爱值、依赖度。\n"
            "- 不要把临时情绪夸大成永久关系。\n"
            "- 不要记录用户隐私、敏感身份、过度个人信息。\n"
            "- 不要记录无意义寒暄。\n"
            "- 如果本轮没有值得记录的内容，返回空数组。\n"
            "- flashback_candidates 必须像聊天里顺口想起的一小句，不能像总结报告。\n"
            "- 所有项目都要有 strength，范围 0 到 1。\n"
            "- 所有项目都要有 ttl_minutes。\n"
            "- 输出严格 JSON，不要输出解释。\n\n"
            "期望输出格式：\n"
            "{\n"
            '  "mood_hint": {"label": "有点认真", "energy": "中", "expression_tendency": "正常"},\n'
            '  "residue_add": [{"text": "用户担心弱状态注入达不到闪回和小细节效果。", "strength": 0.85, "ttl_minutes": 180}],\n'
            '  "micro_details_add": [{"text": "用户想把旧 affective_engine 改造成 Inner Continuity Engine。", "strength": 0.75, "ttl_minutes": 360}],\n'
            '  "flashback_candidates_add": [{"text": "你要的不是 mood 标签，是她能顺手想起一点细节。", "strength": 0.8, "ttl_minutes": 360}],\n'
            '  "remove_or_decay": []\n'
            "}\n\n"
            f"当前短期状态摘要：{json.dumps(summary, ensure_ascii=False)}\n"
            f"shared_life_context 摘要（仅作语气背景，可为空）：{json.dumps(slc, ensure_ascii=False)}\n"
            f"用户最新原始消息：{limit_text(user_text, 600)}\n"
            f"阿绫最新回复：{limit_text(bot_text, 600)}\n"
        )

    def _rule_fallback_update(self, user_text: str) -> dict[str, Any] | None:
        lowered = user_text.lower()
        if not any(keyword.lower() in lowered for keyword in UPDATE_KEYWORDS):
            return None
        residue: list[dict[str, Any]] = []
        micro: list[dict[str, Any]] = []
        flashbacks: list[dict[str, Any]] = []
        mood = {"label": "有点认真", "energy": "中", "expression_tendency": "正常"}

        if "token" in lowered:
            residue.append({"text": "用户刚刚担心这个插件又把 token 搞上去。", "strength": 0.75, "ttl_minutes": 180})
            flashbacks.append({"text": "你之前就是怕它又把 token 搞上去嘛。", "strength": 0.72, "ttl_minutes": 180})
        if "闪回" in user_text or "小细节" in user_text or "mood" in lowered or "情绪" in user_text:
            micro.append({"text": "用户想要的是闪回和小细节，不是单纯情绪标签。", "strength": 0.78, "ttl_minutes": 360})
            flashbacks.append({"text": "你要的不是 mood 标签，是她能顺手想起一点细节。", "strength": 0.78, "ttl_minutes": 360})
        if "memory" in lowered or "检索" in user_text or "aling_memory" in lowered:
            residue.append({"text": "用户在意 Inner Continuity 不能污染 aling_memory 的检索。", "strength": 0.8, "ttl_minutes": 360})
            flashbacks.append({"text": "这个得和 aling_memory 隔开，不然又会污染检索。", "strength": 0.8, "ttl_minutes": 360})
        if "shared_life_context" in lowered or "slc" in lowered:
            micro.append({"text": "用户在讨论 Inner Continuity 和 shared_life_context 的边界。", "strength": 0.72, "ttl_minutes": 240})
            flashbacks.append({"text": "SLC 是今天的生活背景，Inner Continuity 是刚刚还挂着什么。", "strength": 0.72, "ttl_minutes": 240})
        if not residue and not micro and not flashbacks:
            residue.append({"text": "用户刚刚在认真推进 Inner Continuity Engine 的插件方案。", "strength": 0.55, "ttl_minutes": 120})

        return {
            "mood_hint": mood,
            "residue_add": residue[:3],
            "micro_details_add": micro[:3],
            "flashback_candidates_add": flashbacks[:3],
            "remove_or_decay": [],
        }

    def apply_update(self, scope_id: str, state: dict[str, Any], result: dict[str, Any]) -> None:
        now = now_ts()
        mood = result.get("mood_hint")
        if isinstance(mood, dict):
            state["mood_hint"] = normalize_mood(mood)
        added_counts = {"residue": 0, "micro_details": 0, "flashback_candidates": 0}
        for key, prefix, source_key in (
            ("residue", "r", "residue_add"),
            ("micro_details", "m", "micro_details_add"),
            ("flashback_candidates", "f", "flashback_candidates_add"),
        ):
            items = result.get(source_key) or []
            if not isinstance(items, list):
                continue
            for raw in items:
                item = make_item(prefix, raw, now, self.config)
                if item:
                    merge_or_append_item(state.setdefault(key, []), item)
                    added_counts[key] += 1
        for item_id in result.get("remove_or_decay") or []:
            decay_item(state, str(item_id))
        state["updated_at"] = now
        cleanup_state(state, self.config)
        self.save_state(scope_id, state)
        if self.config.get("debug"):
            logger.info(
                "[inner_continuity] update result residue=%s micro=%s flashback=%s",
                added_counts["residue"],
                added_counts["micro_details"],
                added_counts["flashback_candidates"],
            )

    def render_injection(self, scope_id: str, state: dict[str, Any], user_text: str) -> tuple[str, dict[str, list[str]]]:
        cleanup_state(state, self.config)
        if self._state_path(scope_id).exists():
            self.save_state(scope_id, state)

        selected_residue = select_items(state.get("residue", []), user_text, 3)
        selected_micro = select_items(state.get("micro_details", []), user_text, 3)
        selected_flashback: list[dict[str, Any]] = []
        cooldown = state.get("cooldown") or {}
        now = now_ts()
        flashback_cooldown = int(self.config.get("flashback_cooldown_seconds") or 0)
        if now - int(cooldown.get("last_used_flashback_at") or 0) >= flashback_cooldown:
            selected_flashback = select_items(state.get("flashback_candidates", []), user_text, 3)
        elif self.config.get("debug"):
            logger.info("[inner_continuity] skipped flashback injection: cooldown")

        if not selected_residue and not selected_micro and not selected_flashback:
            return "", {"residue": [], "micro_details": [], "flashback_candidates": []}

        mood = normalize_mood(state.get("mood_hint") or {})
        lines = [
            "<inner_continuity>",
            "这是阿绫这几轮对话里还挂着的短期印象。",
            "它不是长期记忆，不要逐条复述，不要每次都使用。",
            "如果贴合用户最新消息，可以自然带出一个很短的回勾或闪回。",
            "用户最新消息永远优先。",
            "",
            "情绪/表达倾向：",
            f"- mood: {mood['label']}",
            f"- energy: {mood['energy']}",
            f"- expression: {mood['expression_tendency']}",
        ]
        append_section(lines, "残留感：", selected_residue)
        append_section(lines, "小细节：", selected_micro)
        append_section(lines, "可选闪回短句：", selected_flashback, quote=True)
        lines.extend(
            [
                "",
                "使用限制：",
                "- 只在贴合当前消息时使用。",
                "- 最多使用一个闪回点。",
                "- 不要为了闪回而偏离用户最新问题。",
                "- 不要解释本段内容，不要说“根据我的短期连续性记录”。",
                "</inner_continuity>",
            ]
        )
        rendered = trim_to_chars("\n".join(lines), int(self.config.get("max_injected_chars") or 900))
        used = {
            "residue": [str(item.get("id")) for item in selected_residue],
            "micro_details": [str(item.get("id")) for item in selected_micro],
            "flashback_candidates": [str(item.get("id")) for item in selected_flashback],
        }
        return rendered, used

    def _mark_injected(self, scope_id: str, state: dict[str, Any], used_ids: dict[str, list[str]]) -> None:
        now = now_ts()
        any_used = False
        flashback_used = False
        for key, ids in used_ids.items():
            id_set = set(ids)
            if not id_set:
                continue
            for item in state.get(key, []):
                if str(item.get("id")) in id_set:
                    item["used_count"] = int(item.get("used_count") or 0) + 1
                    any_used = True
                    if key == "flashback_candidates":
                        flashback_used = True
        cooldown = state.setdefault("cooldown", {})
        if any_used:
            cooldown["last_injected_at"] = now
        if flashback_used:
            cooldown["last_used_flashback_at"] = now
        cleanup_state(state, self.config)
        self.save_state(scope_id, state)

    def load_state(self, scope_id: str) -> dict[str, Any]:
        path = self._state_path(scope_id)
        if not path.exists():
            return deepcopy(DEFAULT_STATE)
        try:
            with path.open("r", encoding="utf-8-sig") as file:
                data = json.load(file)
            if not isinstance(data, dict):
                raise ValueError("state JSON top-level is not an object")
        except Exception as exc:
            backup = path.with_suffix(path.suffix + ".broken")
            try:
                os.replace(path, backup)
            except OSError:
                logger.warning("[inner_continuity] failed to backup broken state %s", path, exc_info=True)
            logger.warning("[inner_continuity] rebuilt broken state %s: %s", path, exc)
            data = deepcopy(DEFAULT_STATE)
        state = merge_state_defaults(data)
        expired = cleanup_state(state, self.config)
        if expired and self.config.get("debug"):
            logger.info("[inner_continuity] cleanup expired=%s", expired)
        return state

    def save_state(self, scope_id: str, state: dict[str, Any]) -> None:
        path = self._state_path(scope_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(tmp, path)

    def _state_path(self, scope_id: str) -> Path:
        return self.state_dir / f"{safe_filename(scope_id)}.json"

    def _cmd_inner(self, scope_id: str) -> str:
        state = self.load_state(scope_id)
        mood = normalize_mood(state.get("mood_hint") or {})
        lines = [
            "Inner Continuity 当前状态：",
            f"mood: {mood['label']} / energy: {mood['energy']}",
        ]
        lines.extend(format_items("residue", state.get("residue", [])))
        lines.extend(format_items("micro_details", state.get("micro_details", [])))
        lines.extend(format_items("flashbacks", state.get("flashback_candidates", [])))
        return "\n".join(lines)

    def _read_shared_life_context_summary(self) -> dict[str, Any]:
        keys = {"current_activity", "energy_level", "ambient_mood", "current_period"}
        candidates: list[Path] = []
        parent = self.data_root.parent
        for dirname in ("shared_life_context", "astrbot_plugin_shared_life_context"):
            root = parent / dirname
            if root.exists():
                candidates.extend(root.glob("*.json"))
                candidates.extend(root.glob("**/*.json"))
        for path in candidates[:20]:
            try:
                with path.open("r", encoding="utf-8-sig") as file:
                    data = json.load(file)
                found = pick_nested_keys(data, keys)
                if found:
                    return found
            except Exception:
                continue
        return {}

    def _merge_config(self, config: Any) -> dict[str, Any]:
        merged = dict(DEFAULT_CONFIG)
        if isinstance(config, dict):
            merged.update(config)
        elif config is not None:
            for key in DEFAULT_CONFIG:
                try:
                    value = getattr(config, key)
                    if value is not None:
                        merged[key] = value
                except Exception:
                    try:
                        value = config.get(key)  # type: ignore[attr-defined]
                        if value is not None:
                            merged[key] = value
                    except Exception:
                        continue
        return merged


def resolve_data_dir(context: Any = None, plugin_dir: Path | None = None) -> Path:
    candidates: list[Path] = []
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path  # type: ignore

        candidates.append(Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME)
    except Exception:
        pass
    for attr in ("get_plugin_data_dir", "get_data_dir"):
        fn = getattr(context, attr, None)
        if callable(fn):
            try:
                value = fn(PLUGIN_NAME)
            except TypeError:
                try:
                    value = fn()
                except Exception:
                    value = None
            except Exception:
                value = None
            if value:
                candidates.append(Path(value))
    candidates.append(Path.cwd() / "data" / "plugin_data" / PLUGIN_NAME)
    if plugin_dir:
        candidates.append(plugin_dir / "data")
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except OSError:
            continue
    fallback = Path(__file__).resolve().parent / "data"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def inject_temporary_text(req: Any, text: str) -> bool:
    if not text:
        return True
    try:
        if hasattr(req, "extra_user_content_parts"):
            parts = getattr(req, "extra_user_content_parts", None)
            if not hasattr(parts, "append"):
                parts = list(parts or [])
                setattr(req, "extra_user_content_parts", parts)
            part = make_text_part(text)
            mark_as_temp = getattr(part, "mark_as_temp", None)
            if callable(mark_as_temp):
                mark_as_temp()
            parts.append(part)
            return True
        if append_to_known_prompt_field(req, text):
            logger.warning("[inner_continuity] used prompt fallback injection; extra_user_content_parts unavailable")
            return True
        logger.warning("[inner_continuity] no compatible ProviderRequest injection field found")
        return False
    except Exception:
        logger.warning("[inner_continuity] failed to inject temporary context", exc_info=True)
        return False


def make_text_part(text: str) -> Any:
    TextPart = load_text_part()
    try:
        return TextPart(text=text)
    except TypeError:
        return TextPart(content=text)


def load_text_part() -> Any:
    try:
        from astrbot.core.provider.entities import TextPart as ImportedTextPart  # type: ignore

        return ImportedTextPart
    except Exception:
        from astrbot.core.provider.schema import TextPart as ImportedTextPart  # type: ignore

        return ImportedTextPart


def append_to_known_prompt_field(req: Any, text: str) -> bool:
    for name in ("prompt", "user_prompt", "content"):
        value = safe_get(req, name)
        if isinstance(value, str):
            setattr(req, name, value + "\n\n" + text)
            return True
    return False


def scope_from_event(event: Any) -> str:
    for name in ("user_id", "sender_id", "sender"):
        value = safe_get(event, name)
        if value:
            return f"private:{value}"
    value = safe_get(event, "unified_msg_origin") or safe_get(event, "session_id")
    if value:
        return str(value)
    return "private:default"


def extract_text(event: Any = None, req: Any = None) -> str:
    for obj in (event, req):
        if obj is None:
            continue
        for name in ("message_str", "message", "content", "prompt", "query", "text"):
            value = safe_get(obj, name)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if callable(value):
                try:
                    called = value()
                    if isinstance(called, str) and called.strip():
                        return called.strip()
                except Exception:
                    continue
    messages = safe_get(req, "messages")
    if isinstance(messages, list):
        for item in reversed(messages):
            if role_of(item) == "user":
                content = content_of(item)
                if content:
                    return content
    return ""


def extract_response_text(resp: Any) -> str:
    if isinstance(resp, str):
        return resp.strip()
    for name in ("completion_text", "text", "content", "message", "result", "response"):
        value = safe_get(resp, name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if callable(value):
            try:
                called = value()
                if isinstance(called, str) and called.strip():
                    return called.strip()
            except Exception:
                continue
    choices = safe_get(resp, "choices")
    if isinstance(choices, list) and choices:
        return content_of(choices[0])
    return ""


def role_of(message: Any) -> str:
    return str(safe_get(message, "role") or "").lower()


def content_of(message: Any) -> str:
    value = safe_get(message, "content")
    if isinstance(value, str):
        return value.strip()
    nested = safe_get(value, "text")
    if isinstance(nested, str):
        return nested.strip()
    return ""


def safe_get(obj: Any, name: str) -> Any:
    try:
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)
    except Exception:
        return None


def is_admin_event(event: Any) -> bool:
    for name in ("is_admin", "is_owner"):
        value = safe_get(event, name)
        if isinstance(value, bool):
            return value
        if callable(value):
            try:
                return bool(value())
            except Exception:
                continue
    sender = safe_get(event, "sender") or safe_get(event, "message_obj")
    for obj in (sender, event):
        role = str(safe_get(obj, "role") or safe_get(obj, "permission") or "").lower()
        if role in {"admin", "administrator", "owner", "superuser"}:
            return True
    return False


def get_provider(context: Any) -> Any:
    for name in ("get_using_provider", "get_provider", "provider"):
        value = safe_get(context, name)
        try:
            return value() if callable(value) else value
        except Exception:
            continue
    return None


def parse_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        match = re.search(r"\{.*\}", stripped, flags=re.S)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None


def merge_state_defaults(data: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(DEFAULT_STATE)
    for key, value in data.items():
        if key == "cooldown" and isinstance(value, dict):
            merged["cooldown"].update(value)
        elif key == "mood_hint" and isinstance(value, dict):
            merged["mood_hint"].update(value)
        else:
            merged[key] = value
    return merged


def cleanup_state(state: dict[str, Any], config: dict[str, Any]) -> int:
    now = now_ts()
    expired = 0
    for key, limit_key in (
        ("residue", "max_residue_items"),
        ("micro_details", "max_micro_details"),
        ("flashback_candidates", "max_flashback_candidates"),
    ):
        kept = []
        for item in state.get(key, []):
            if int(item.get("expires_at") or 0) <= now:
                expired += 1
                continue
            if int(item.get("used_count") or 0) >= int(item.get("max_use") or 2):
                expired += 1
                continue
            kept.append(item)
        kept.sort(key=lambda item: (float(item.get("strength") or 0), int(item.get("created_at") or 0)), reverse=True)
        state[key] = kept[: int(config.get(limit_key) or 5)]
    return expired


def make_item(prefix: str, raw: Any, now: int, config: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    text = clean_item_text(str(raw.get("text") or ""))
    if not text:
        return None
    strength = clamp_float(raw.get("strength"), 0.0, 1.0, 0.5)
    ttl = int(raw.get("ttl_minutes") or config.get("default_ttl_minutes") or 180)
    ttl = max(5, min(ttl, int(config.get("strong_ttl_minutes") or 720)))
    item: dict[str, Any] = {
        "id": f"{prefix}_{now}_{abs(hash(text)) % 100000}",
        "text": text,
        "source": "recent_dialogue",
        "strength": strength,
        "created_at": now,
        "expires_at": now + ttl * 60,
        "used_count": 0,
        "max_use": int(raw.get("max_use") or (1 if prefix == "f" else 2)),
    }
    if prefix == "f":
        related = raw.get("related_to")
        item["related_to"] = related if isinstance(related, list) else []
    return item


def merge_or_append_item(items: list[dict[str, Any]], new_item: dict[str, Any]) -> None:
    new_text = str(new_item.get("text") or "")
    for item in items:
        old_text = str(item.get("text") or "")
        if text_similarity(old_text, new_text) >= 0.72:
            item["strength"] = max(float(item.get("strength") or 0), float(new_item.get("strength") or 0))
            item["expires_at"] = max(int(item.get("expires_at") or 0), int(new_item.get("expires_at") or 0))
            item["created_at"] = max(int(item.get("created_at") or 0), int(new_item.get("created_at") or 0))
            return
    items.append(new_item)


def text_similarity(left: str, right: str) -> float:
    a = extract_terms(left)
    b = extract_terms(right)
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def decay_item(state: dict[str, Any], item_id: str) -> None:
    for key in ("residue", "micro_details", "flashback_candidates"):
        for item in state.get(key, []):
            if str(item.get("id")) == item_id:
                item["strength"] = max(0.0, float(item.get("strength") or 0) - 0.25)
                item["used_count"] = int(item.get("used_count") or 0) + 1


def select_items(items: list[dict[str, Any]], user_text: str, limit: int) -> list[dict[str, Any]]:
    if not items or is_trivial_user_text(user_text):
        return []
    followup = is_followup_text(user_text)
    scored = []
    for item in items:
        score = relevance_score(str(item.get("text") or ""), user_text)
        strength = float(item.get("strength") or 0)
        used = int(item.get("used_count") or 0)
        if score <= 0 and not followup and strength < 0.72:
            continue
        scored.append((score + strength * 0.4 - used * 0.2, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:limit]]


def relevance_score(item_text: str, user_text: str) -> float:
    a = extract_terms(item_text)
    b = extract_terms(user_text)
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    return overlap / max(3, min(len(a), len(b)))


def extract_terms(text: str) -> set[str]:
    terms = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]+", text.lower()))
    for word in UPDATE_KEYWORDS:
        if word.lower() in text.lower():
            terms.add(word.lower())
    chinese = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    for chunk in chinese:
        if len(chunk) <= 4:
            terms.add(chunk)
        else:
            for i in range(len(chunk) - 1):
                terms.add(chunk[i : i + 2])
    return terms


def is_trivial_user_text(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return True
    if len(stripped) <= 8 and SHORT_GREETING_RE.match(stripped):
        return True
    return False


def is_followup_text(text: str) -> bool:
    stripped = (text or "").strip()
    return len(stripped) <= 20 and any(word in stripped.lower() for word in ("这个", "这样", "它", "那", "刚才", "之前", "slc", "memory"))


def normalize_mood(mood: dict[str, Any]) -> dict[str, str]:
    labels = {"平静", "有点认真", "松弛", "有点困", "被逗乐"}
    energies = {"低", "中", "高"}
    expressions = {"少说一点", "正常", "稍微多说一点"}
    label = str(mood.get("label") or "平静")
    energy = str(mood.get("energy") or "中")
    expression = str(mood.get("expression_tendency") or mood.get("expression") or "正常")
    return {
        "label": label if label in labels else "平静",
        "energy": energy if energy in energies else "中",
        "expression_tendency": expression if expression in expressions else "正常",
    }


def append_section(lines: list[str], title: str, items: list[dict[str, Any]], quote: bool = False) -> None:
    if not items:
        return
    lines.extend(["", title])
    for item in items:
        text = str(item.get("text") or "").strip()
        if quote:
            text = f"“{text.strip('“”') }”"
        lines.append(f"- {text}")


def format_items(title: str, items: list[dict[str, Any]]) -> list[str]:
    lines = ["", f"{title}:"]
    if not items:
        lines.append("(empty)")
        return lines
    now = now_ts()
    for idx, item in enumerate(items[:8], 1):
        expires = max(0, int(item.get("expires_at") or 0) - now)
        strength = float(item.get("strength") or 0)
        lines.append(f"{idx}. {item.get('text', '')} strength={strength:.2f} expires={format_duration(expires)}")
    return lines


def pick_nested_keys(data: Any, keys: set[str]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            if key in keys and isinstance(value, (str, int, float, bool)):
                found[key] = value
            elif isinstance(value, (dict, list)) and len(found) < len(keys):
                found.update(pick_nested_keys(value, keys))
    elif isinstance(data, list):
        for item in data[:10]:
            found.update(pick_nested_keys(item, keys))
            if len(found) >= len(keys):
                break
    return found


def safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    return safe[:120] or "default"


def clean_item_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:180]


def trim_to_chars(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - 24)].rstrip() + "\n</inner_continuity>"


def limit_text(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def clamp_float(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except Exception:
        return default
    return max(low, min(high, number))


def now_ts() -> int:
    return int(time.time())


def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h"
