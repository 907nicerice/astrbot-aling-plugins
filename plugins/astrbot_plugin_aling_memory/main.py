from __future__ import annotations

import logging
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
    ProviderRequest = Any
    LLMResponse = Any

from .models.memory_item import ALLOWED_MEMORY_TYPES
from .services.defaults import DEFAULT_CONFIG, PLUGIN_NAME
from .services.extractor import Extractor
from .services.flashback import FlashbackService
from .services.injector import Injector
from .services.json_store import resolve_data_dir
from .services.memory_store import MemoryStore
from .services.mirror_service import MirrorService
from .services.provider_compat import extract_response_text, extract_user_text, inject_text, scope_from_event
from .services.recent_trace_service import RecentTraceService
from .services.retriever import Retriever
from .services.scene_router import SceneRouter
from .services.summarizer import Summarizer
from .services.text_utils import split_tags

logger = logging.getLogger(PLUGIN_NAME)


@register(
    "astrbot_plugin_aling_memory",
    "Codex",
    "阿绫长期小记忆 / User Life Mirror / 上下文压缩插件",
    "0.1.0",
)
class AlingMemoryPlugin(Star):
    def __init__(self, context: Context, config: Any = None) -> None:
        super().__init__(context)
        self.config = self._merge_config(config)
        plugin_dir = Path(__file__).resolve().parent
        self.data_dir = resolve_data_dir(context, plugin_dir)
        self.store = MemoryStore(self.data_dir, self.config)
        self.config = self.store.ensure_config_file()
        self.router = SceneRouter(self.config)
        self.flashback = FlashbackService(self.data_dir, self.config)
        self.retriever = Retriever(self.store, self.flashback, self.config)
        self.injector = Injector(self.config)
        self.mirror = MirrorService(self.data_dir, self.config)
        self.summarizer = Summarizer(self.config)
        self.extractor = Extractor(self.config)
        self.recent_trace = RecentTraceService(self.data_dir, self.config)

    @filter.command("mem")
    async def mem(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        try:
            raw = getattr(event, "message_str", "") or extract_user_text(event=event)
            scope_id = scope_from_event(event)
            reply = self._handle_command(scope_id, raw)
        except Exception:
            logger.exception("[aling_memory] command failed")
            reply = "阿绫的小记忆插件刚刚出错了，已经记到日志里。"
        yield event.plain_result(reply)

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        try:
            if not self.config.get("enabled", True):
                return
            scope_id = scope_from_event(event)
            user_text = extract_user_text(event=event, req=req)
            if not user_text:
                return
            self.store.record_message(scope_id, "user", user_text)
            turn = self.flashback.bump_turn(scope_id)
            scene = self.router.classify(user_text)
            if scene.primary_scene == "command":
                return
            self._maybe_extract_user_candidate(scope_id, user_text)
            self._maybe_periodic_summary(scope_id, turn)
            retrieval = self.retriever.retrieve(scope_id, user_text, scene)
            mirror_limit = self.injector.mirror_limit(scene.primary_scene)
            mirror_slices = self.mirror.select_slices(scope_id, scene.primary_scene, mirror_limit)
            recent_traces = self.recent_trace.retrieve(scope_id, user_text)
            plan = self.injector.build(scene, retrieval, mirror_slices, recent_traces)
            if plan.text:
                ok = inject_text(req, plan.text)
                if ok and plan.flashback and retrieval.flashback_memory_id:
                    self.flashback.mark_used(scope_id, retrieval.flashback_memory_id)
                    self.store.update_memory(scope_id, retrieval.flashback_memory_id, mark_used=True)
            if self.config.get("debug_enabled"):
                logger.info(
                    "[aling_memory] scene=%s labels=%s budget=%s selected=%s flashback=%s tokens_est=%s",
                    scene.primary_scene,
                    ",".join(scene.labels),
                    (self.config.get("injection_budgets") or {}).get(scene.primary_scene, 0),
                    len(plan.selected_ids),
                    plan.flashback,
                    plan.tokens_est,
                )
                logger.info("[aling_memory] selected memory ids: %s", ", ".join(plan.selected_ids) or "(none)")
                logger.info("[aling_memory] selected recent trace ids: %s", ", ".join(plan.recent_trace_ids) or "(none)")
                if plan.filtered:
                    logger.info("[aling_memory] filtered reason: %s", " / ".join(plan.filtered[:12]))
        except Exception:
            logger.exception("[aling_memory] on_llm_request failed")

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp: LLMResponse) -> None:
        try:
            if not self.config.get("enabled", True):
                return
            scope_id = scope_from_event(event)
            text = extract_response_text(resp)
            if text:
                self.store.record_message(scope_id, "assistant", text)
                user_text = extract_user_text(event=event)
                self.recent_trace.save_from_turn(scope_id, user_text, text)
        except Exception:
            logger.warning("[aling_memory] on_llm_response failed", exc_info=True)

    def _handle_command(self, scope_id: str, raw: str) -> str:
        text = raw.strip()
        if text.startswith("/mem"):
            text = text[4:].strip()
        elif text.startswith("／mem"):
            text = text[4:].strip()
        if not text:
            return self._help()
        cmd, _, rest = text.partition(" ")
        cmd = cmd.lower()
        if cmd == "add":
            return self._cmd_add(scope_id, rest)
        if cmd == "list":
            return self._cmd_list(scope_id)
        if cmd == "search":
            return self._cmd_search(scope_id, rest)
        if cmd == "show":
            return self._cmd_show(scope_id, rest)
        if cmd == "delete":
            return self._cmd_delete(scope_id, rest)
        if cmd == "update":
            return self._cmd_update(scope_id, rest)
        if cmd == "tag":
            return self._cmd_tag(scope_id, rest)
        if cmd == "deprecate":
            return self._cmd_deprecate(scope_id, rest)
        if cmd == "clear":
            return self._cmd_clear(scope_id)
        if cmd == "candidates":
            return self._cmd_candidates(scope_id)
        if cmd == "approve":
            return self._cmd_approve(scope_id, rest)
        if cmd == "reject":
            return self._cmd_reject(scope_id, rest)
        if cmd == "mirror":
            return self._cmd_mirror(scope_id)
        if cmd == "mirror_refresh":
            return self._cmd_mirror_refresh(scope_id)
        if cmd == "summarize":
            return self._cmd_summarize(scope_id)
        if cmd == "summaries":
            return self._cmd_summaries(scope_id)
        if cmd == "summary_clear":
            self.store.clear_summaries(scope_id)
            return "已清空当前会话的短期摘要。"
        if cmd == "debug":
            return self._cmd_debug(rest)
        if cmd == "inject_preview":
            return self._cmd_inject_preview(scope_id, rest)
        return self._help()

    def _cmd_add(self, scope_id: str, rest: str) -> str:
        memory_type, _, content = rest.strip().partition(" ")
        if memory_type not in ALLOWED_MEMORY_TYPES:
            return "类型不支持。可用类型：small_memory / preference_memory / relationship_memory / life_signal / project_context / context_summary"
        if not content.strip():
            return "用法：/mem add <type> <content>"
        item = self.store.add_memory(scope_id, memory_type, content.strip())
        return f"记住了：{item.id}\n{item.content}"

    def _cmd_list(self, scope_id: str) -> str:
        items = self.store.list_memories(scope_id, include_inactive=True)
        if not items:
            return "当前会话还没有小记忆。"
        lines = [f"{item.id} [{item.type}/{item.status}] {item.content[:60]}" for item in items[-20:]]
        return "最近记忆：\n" + "\n".join(lines)

    def _cmd_search(self, scope_id: str, keyword: str) -> str:
        if not keyword.strip():
            return "用法：/mem search <keyword>"
        items = self.store.search_memories(scope_id, keyword.strip())
        if not items:
            return "没搜到相关记忆。"
        return "\n".join(f"{item.id} [{item.type}] {item.content}" for item in items[:20])

    def _cmd_show(self, scope_id: str, memory_id: str) -> str:
        item = self.store.get_memory(scope_id, memory_id.strip())
        if not item:
            return "没找到这条记忆。"
        return (
            f"id: {item.id}\n"
            f"type: {item.type}\nstatus: {item.status}\nsource: {item.source}\nconfidence: {item.confidence}\n"
            f"tags: {', '.join(item.tags) or '-'}\ncontent: {item.content}\nuse_rule: {item.use_rule or '-'}"
        )

    def _cmd_delete(self, scope_id: str, memory_id: str) -> str:
        return "已删除。" if self.store.delete_memory(scope_id, memory_id.strip()) else "没找到这条记忆。"

    def _cmd_update(self, scope_id: str, rest: str) -> str:
        memory_id, _, content = rest.strip().partition(" ")
        if not memory_id or not content:
            return "用法：/mem update <id> <content>"
        item = self.store.update_memory(scope_id, memory_id, content=content)
        return "已更新。" if item else "没找到这条记忆。"

    def _cmd_tag(self, scope_id: str, rest: str) -> str:
        memory_id, _, tags_raw = rest.strip().partition(" ")
        if not memory_id or not tags_raw:
            return "用法：/mem tag <id> <tag1,tag2>"
        item = self.store.update_memory(scope_id, memory_id, tags=split_tags(tags_raw))
        return "标签已更新。" if item else "没找到这条记忆。"

    def _cmd_deprecate(self, scope_id: str, memory_id: str) -> str:
        item = self.store.update_memory(scope_id, memory_id.strip(), status="deprecated")
        return "已降级为 deprecated。" if item else "没找到这条记忆。"

    def _cmd_clear(self, scope_id: str) -> str:
        counts = self.store.clear_scope(scope_id)
        self.store.clear_summaries(scope_id)
        trace_count = self.recent_trace.clear(scope_id)
        mirror_count = self.mirror.clear(scope_id)
        return (
            "已清空当前会话的 aling_memory："
            f"记忆 {counts['memories']} 条，候选 {counts['candidates']} 条，"
            f"recent_trace {trace_count} 条，User Life Mirror {'已清空' if mirror_count else '原本为空'}。"
        )

    def _cmd_candidates(self, scope_id: str) -> str:
        candidates = self.store.list_candidates(scope_id)
        if not candidates:
            return "当前没有候选记忆。"
        return "\n".join(
            f"{cand.id} [{cand.suggested_type}/{cand.confidence:.2f}] {cand.content}\n原因：{cand.reason}"
            for cand in candidates[:20]
        )

    def _cmd_approve(self, scope_id: str, candidate_id: str) -> str:
        item = self.store.approve_candidate(scope_id, candidate_id.strip())
        return f"已确认：{item.id}" if item else "没找到这个候选。"

    def _cmd_reject(self, scope_id: str, candidate_id: str) -> str:
        cand = self.store.remove_candidate(scope_id, candidate_id.strip())
        return "已拒绝候选。" if cand else "没找到这个候选。"

    def _cmd_mirror(self, scope_id: str) -> str:
        mirror = self.mirror.get(scope_id)
        lines = []
        for key, item in mirror.items():
            summary = item.summary or "(empty)"
            lines.append(f"{key} [{item.source}] {summary}")
        return "User Life Mirror：\n" + "\n".join(lines)

    def _cmd_mirror_refresh(self, scope_id: str) -> str:
        mirror = self.mirror.refresh(scope_id, self.store.list_memories(scope_id))
        return "已刷新 User Life Mirror。\n" + "\n".join(f"{key}: {item.summary}" for key, item in mirror.items())

    def _cmd_summarize(self, scope_id: str) -> str:
        summary = self.summarizer.summarize(scope_id, self.store.recent_messages(scope_id))
        if not summary:
            return "最近消息还不够生成摘要。"
        self.store.add_summary(scope_id, summary)
        self._extract_from_summary(scope_id, summary.content)
        return f"已生成短期摘要：{summary.id}\n{summary.content}"

    def _cmd_summaries(self, scope_id: str) -> str:
        summaries = self.store.list_summaries(scope_id, include_expired=True)
        if not summaries:
            return "当前没有短期摘要。"
        return "\n".join(f"{item.id} ttl={item.ttl_days}d {item.content}" for item in summaries[-10:])

    def _cmd_debug(self, rest: str) -> str:
        value = rest.strip().lower()
        if value not in {"on", "off"}:
            return "用法：/mem debug on|off"
        self.config["debug_enabled"] = value == "on"
        self.store.config = self.config
        self.store.ensure_config_file()
        return "debug 已开启。" if value == "on" else "debug 已关闭。"

    def _cmd_inject_preview(self, scope_id: str, text: str) -> str:
        if not text.strip():
            return "用法：/mem inject_preview <text>"
        scene = self.router.classify(text)
        retrieval = self.retriever.retrieve(scope_id, text, scene)
        mirror_slices = self.mirror.select_slices(scope_id, scene.primary_scene, self.injector.mirror_limit(scene.primary_scene))
        recent_traces = self.recent_trace.retrieve(scope_id, text)
        plan = self.injector.build(scene, retrieval, mirror_slices, recent_traces)
        return (
            f"scene={scene.primary_scene}\n"
            f"labels={', '.join(scene.labels)}\n"
            f"reasons={'; '.join(scene.reasons)}\n"
            f"selected memories={', '.join(plan.selected_ids) or '0'}\n"
            f"recent traces={', '.join(plan.recent_trace_ids) or '0'}\n"
            f"mirror slices={', '.join(plan.mirror_keys) or '0'}\n"
            f"tokens_est={plan.tokens_est}\n"
            f"flashback={str(plan.flashback).lower()}\n"
            f"filtered={'; '.join(plan.filtered) or '-'}\n"
            f"injection:\n{plan.text or '(empty)'}"
        )

    def _maybe_extract_user_candidate(self, scope_id: str, text: str) -> None:
        if not self.config.get("auto_extract_enabled", True):
            return
        for candidate in self.extractor.extract_from_user_text(text):
            if self.extractor.auto_confirmable(candidate):
                item = self.store.add_memory(
                    scope_id,
                    candidate.suggested_type,
                    candidate.content,
                    tags=candidate.tags,
                    use_rule=candidate.use_rule,
                    confidence=candidate.confidence,
                    source="auto_confirmed",
                )
                logger.info(
                    "[aling_memory] auto_confirm memory id=%s type=%s confidence=%.2f",
                    item.id,
                    item.type,
                    item.confidence,
                )
            else:
                self.store.add_candidate(scope_id, candidate)

    def _maybe_periodic_summary(self, scope_id: str, turn: int) -> None:
        if not self.config.get("context_summary_enabled", True):
            return
        every = int(self.config.get("summary_every_n_turns") or 20)
        if every <= 0 or turn % every != 0:
            return
        summary = self.summarizer.summarize(scope_id, self.store.recent_messages(scope_id))
        if summary:
            self.store.add_summary(scope_id, summary)
            self._extract_from_summary(scope_id, summary.content)

    def _extract_from_summary(self, scope_id: str, text: str) -> None:
        if not self.config.get("auto_extract_enabled", True):
            return
        for candidate in self.extractor.extract_from_summary(text):
            self.store.add_candidate(scope_id, candidate)

    def _merge_config(self, config: Any) -> dict[str, Any]:
        merged = dict(DEFAULT_CONFIG)
        if isinstance(config, dict):
            merged.update(config)
        elif config is not None:
            for name in DEFAULT_CONFIG:
                try:
                    value = getattr(config, name)
                    if value is not None:
                        merged[name] = value
                except Exception:
                    continue
            try:
                value = config.get("debug_enabled")  # type: ignore[attr-defined]
                if value is not None:
                    merged["debug_enabled"] = value
            except Exception:
                pass
        return merged

    def _help(self) -> str:
        return (
            "用法：/mem add/list/search/show/delete/update/tag/deprecate/clear/candidates/approve/reject/"
            "mirror/mirror_refresh/summarize/summaries/summary_clear/debug/inject_preview"
        )
