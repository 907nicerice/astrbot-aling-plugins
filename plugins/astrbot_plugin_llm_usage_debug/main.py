from __future__ import annotations

import os
import re
import json
import time
import traceback
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register

PLUGIN_NAME = "astrbot_plugin_llm_usage_debug"
REQ_META_KEY = "_llm_usage_debug_req_meta_queue"
CURRENT_FILE = os.path.normcase(os.path.abspath(__file__))
PLUGIN_PATH_RE = re.compile(r"(?:^|[\\/])(astrbot_plugin_[^\\/]+)(?:[\\/]|$)", re.IGNORECASE)

DEFAULT_CONFIG = {
    "enabled": True,
    "llm_usage_debug": True,
    "log_context_stats": True,
    "log_usage": True,
    "log_missing_usage": True,
    "mask_session": True,
    "max_probe_chars": 300000,
    "enable_monkey_patch_fallback": False,
    "log_call_stack": False,
    "call_stack_depth": 12,
    "enable_runtime_stats": True,
    "runtime_stats_max_records": 2000,
    "idle_warn_enabled": True,
    "idle_warn_minutes": 10,
    "idle_warn_min_calls": 1,
}

EVENT_META_KEYS = (
    "action_type",
    "task",
    "task_type",
    "source",
    "plugin_name",
    "plugin",
    "caller",
    "caller_plugin",
    "origin_plugin",
)
TASK_KEYS = ("task", "task_type", "action_type")
SOURCE_KEYS = ("source", "action_type", "task", "task_type")
PLUGIN_KEYS = ("plugin_name", "plugin", "origin_plugin")
CALLER_KEYS = ("caller", "caller_plugin", "origin_plugin", "plugin_name", "plugin")

SLC_KEYWORDS = (
    "shared_life_context",
    "daily_plan",
    "current_activity",
    "energy_level",
    "micro_experience",
    "ambient_mood",
    "daily_life",
)
RETRIEVAL_KEYWORDS = (
    "retrieval",
    "knowledge",
    "知识库",
    "检索结果",
    "rag",
    "related knowledge base results",
)
PROACTIVE_KEYWORDS = (
    "主动对话",
    "主动消息",
    "proactive_chat",
    "unanswered_count",
    "autonomous proactive agent",
    "proactive",
)
QZONE_KEYWORDS = (
    "QQ空间",
    "qq空间",
    "空间动态",
    "qzone",
    "动态",
    "动态生成",
    "说说",
    "should_post",
    "qzone_should_post",
    "qzone_generate",
    "qzone_rewrite",
    "qzone_tool",
    "生活碎片",
    "情绪吐槽",
    "隐性提及你",
    "public post",
    "post_qzone",
    "qzone_life_bridge",
    "qzone_auto_like",
    "dynamic_generate",
)
VISION_KEYWORDS = (
    "image",
    "vision",
    "图片",
    "图像",
    "图像描述",
    "image_url",
)
TOOL_KEYWORDS = (
    "tool_calls",
    "function_call",
    "工具调用",
    "using_llm_tool",
)
SELF_LEARNING_KEYWORDS = (
    "self_learning",
    "自学习",
    "filter_provider",
    "refine_provider",
    "reinforce_provider",
    "progressive_learning",
    "advanced_learning",
    "jargon",
    "黑话",
    "expression_pattern",
    "response_diversity",
    "social_context",
)
AFFECTIVE_KEYWORDS = (
    "affection",
    "affective",
    "affective_engine",
    "inner_state",
)
SOCIAL_CONTEXT_KEYWORDS = (
    "social_context",
    "jargon",
    "黑话",
    "expression_pattern",
    "response_diversity",
)
PLUGIN_KEYWORDS = (
    "plugin",
    "插件",
    "shared_life_context",
    "proactive_chat",
    "qzone",
    "knowledge",
    "retrieval",
    "self_learning",
    "affective_engine",
)

TASK_ALIASES = {
    "chat": {"chat", "normal_chat", "ordinary_chat", "user_chat", "message"},
    "proactive": {"proactive", "proactive_chat", "active_reply", "\u4e3b\u52a8\u6d88\u606f", "\u4e3b\u52a8\u5bf9\u8bdd"},
    "qzone_should_post": {
        "qzone_should_post",
        "should_post",
        "should_post_qzone",
        "qzone_decision",
        "\u662f\u5426\u53d1\u5e03",
    },
    "qzone_generate": {
        "qzone_generate",
        "generate_qzone",
        "dynamic_generate",
        "post_qzone",
        "\u52a8\u6001\u751f\u6210",
        "\u8bf4\u8bf4\u751f\u6210",
    },
    "qzone_rewrite": {
        "qzone_rewrite",
        "rewrite_qzone",
        "polish_qzone",
        "qzone_refine",
        "\u6539\u5199\u8bf4\u8bf4",
        "\u6da6\u8272\u8bf4\u8bf4",
    },
    "qzone_tool": {
        "qzone_tool",
        "qzone",
        "qq\u7a7a\u95f4",
        "qzone_life_bridge",
        "qzone_auto_like",
        "qzone_tool_call",
    },
    "shared_life_refresh": {"shared_life_refresh", "shared_life_context", "life_context_refresh"},
    "vision": {"vision", "image", "multimodal"},
    "retrieval": {"retrieval", "rag", "knowledge"},
    "affective": {"affective", "affective_engine", "inner_state", "affection"},
}
QZONE_TASKS = {"qzone_should_post", "qzone_generate", "qzone_rewrite", "qzone_tool"}
BACKGROUND_TASKS = {*QZONE_TASKS, "proactive", "shared_life_refresh", "affective", "unknown"}
FIXED_TASK_ORDER = [
    "chat",
    "proactive",
    "qzone_should_post",
    "qzone_generate",
    "qzone_rewrite",
    "qzone_tool",
    "shared_life_refresh",
    "affective",
    "retrieval",
    "vision",
    "unknown",
]

PROMPT_PROBE_KEYWORDS = {
    "qzone": QZONE_KEYWORDS,
    "shared_life_context": ("shared_life_context",),
    "proactive": ("\u4e3b\u52a8\u5bf9\u8bdd", "proactive"),
    "affective": ("affection",),
}

HELP_TEXT = """LLM usage debug help

What this plugin can tell you:
1. Whether AstrBot-observed LLM requests still happen while the bot is idle.
2. Which task/source/plugin/caller/stack_plugin most likely triggered them.
3. Whether provider usage exists or is missing.

Useful commands:
/llm_usage_stats
/llm_usage_stats 10m
/llm_usage_stats 30m
/llm_usage_stats 1h
/llm_usage_stats 6h
/llm_usage_stats all
/llm_usage_recent
/llm_usage_recent 20

Recommended workflow:
1. Enable this plugin and keep llm_usage_debug=true.
2. Let the bot stay idle for 10 minutes with no normal chat.
3. Run /llm_usage_stats 10m.
4. If you see qzone / proactive / self_learning / affective, stop the related plugin first.
5. If DeepSeek console request count grows but this plugin shows 0 calls, a plugin may be bypassing AstrBot provider hooks.

If you suspect direct API calls outside AstrBot provider hooks, grep plugin source for:
openai
OpenAI
AsyncOpenAI
chat.completions
/v1/chat/completions
requests.post
httpx
aiohttp
api_key
base_url
"""


@dataclass(slots=True)
class RuntimeRecord:
    timestamp: float
    task: str
    source: str
    plugin: str
    caller: str
    event_type: str
    caller_module: str
    caller_function: str
    stack_plugin: str
    provider: str
    model: str
    session: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    usage_missing: bool
    system_chars: int
    history_chars: int
    user_message_chars: int
    total_chars: int
    full_prompt_chars: int
    messages: int
    contains_qzone_prompt: bool
    contains_proactive_prompt: bool
    contains_shared_life_context: bool


def safe_get(obj: Any, key: Any, default: Any = None) -> Any:
    try:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        if isinstance(key, int) and isinstance(obj, (list, tuple)):
            return obj[key] if -len(obj) <= key < len(obj) else default
        if hasattr(obj, key):
            return getattr(obj, key)
    except Exception:
        return default
    return default


def safe_get_nested(obj: Any, path: list[Any] | tuple[Any, ...], default: Any = None) -> Any:
    current = obj
    try:
        for key in path:
            current = safe_get(current, key, default)
            if current is default:
                return default
        return current
    except Exception:
        return default


def normalize_field(value: Any, default: str = "unknown") -> str:
    try:
        if value is None:
            return default
        text = str(value).strip()
        if not text:
            return default
        return re.sub(r"\s+", "_", text)
    except Exception:
        return default


def match_text(value: Any) -> str:
    try:
        if value is None:
            return ""
        return str(value).strip().lower()
    except Exception:
        return ""


def canonicalize_task(value: Any) -> str:
    normalized = match_text(value)
    if not normalized:
        return "unknown"
    for canonical, aliases in TASK_ALIASES.items():
        if normalized in aliases:
            return canonical
        if any(alias in normalized for alias in aliases):
            return canonical
    return "unknown"


def bool_str(value: Any) -> str:
    return "true" if bool(value) else "false"


def parse_plugin_name_from_path(path: str | None) -> str:
    try:
        if not path:
            return "unknown"
        match = PLUGIN_PATH_RE.search(path)
        if match:
            return normalize_field(match.group(1))
    except Exception:
        return "unknown"
    return "unknown"


def format_stack_frame(filename: str, func_name: str, lineno: int) -> str:
    plugin_name = parse_plugin_name_from_path(filename)
    basename = os.path.basename(filename)
    if plugin_name != "unknown":
        return f"{plugin_name}/{basename}:{func_name}:{lineno}"
    return f"{basename}:{func_name}:{lineno}"


def stack_frame_module(filename: str) -> str:
    plugin_name = parse_plugin_name_from_path(filename)
    basename = os.path.basename(filename)
    if plugin_name != "unknown":
        return f"{plugin_name}/{basename}"
    return basename or "unknown"


def capture_call_stack(depth: int = 12) -> dict[str, str]:
    stack_plugin = "unknown"
    stack_text = "unknown"
    caller_module = "unknown"
    caller_function = "unknown"
    try:
        limit = max(int(depth or 0) * 6, 24)
        raw_frames = traceback.extract_stack(limit=limit)
        frames: list[dict[str, str]] = []
        for frame in raw_frames[:-1]:
            filename = os.path.normcase(os.path.abspath(frame.filename))
            if filename == CURRENT_FILE:
                continue
            plugin_name = parse_plugin_name_from_path(filename)
            frames.append(
                {
                    "formatted": format_stack_frame(filename, frame.name, frame.lineno),
                    "plugin": plugin_name,
                    "module": stack_frame_module(filename),
                    "function": frame.name,
                }
            )

        for frame in reversed(frames):
            if frame["plugin"] != "unknown":
                stack_plugin = frame["plugin"]
                break

        caller_frame = next((frame for frame in reversed(frames) if frame["plugin"] != "unknown"), None)
        if caller_frame is None and frames:
            caller_frame = frames[-1]
        if caller_frame is not None:
            caller_module = caller_frame.get("module", "unknown") or "unknown"
            caller_function = caller_frame.get("function", "unknown") or "unknown"

        plugin_frames = [frame for frame in frames if frame["plugin"] != "unknown"]
        if plugin_frames:
            selected = plugin_frames[-max(int(depth or 0), 1) :]
        else:
            selected = frames[-max(int(depth or 0), 1) :]

        if selected:
            stack_text = " > ".join(frame["formatted"] for frame in selected)
    except Exception:
        return {
            "stack": "unknown",
            "stack_plugin": "unknown",
            "caller_module": "unknown",
            "caller_function": "unknown",
        }
    return {
        "stack": stack_text,
        "stack_plugin": stack_plugin,
        "caller_module": caller_module,
        "caller_function": caller_function,
    }


def content_to_text_len(content: Any) -> int:
    try:
        if content is None:
            return 0
        if isinstance(content, str):
            return len(content)
        if isinstance(content, bytes):
            return len(content)
        if isinstance(content, (int, float, bool)):
            return len(str(content))
        if hasattr(content, "model_dump"):
            return content_to_text_len(content.model_dump())
        if hasattr(content, "dict"):
            return content_to_text_len(content.dict())
        if isinstance(content, dict):
            return sum(content_to_text_len(value) for value in content.values())
        if isinstance(content, (list, tuple, set)):
            return sum(content_to_text_len(item) for item in content)
        return len(str(content))
    except Exception:
        try:
            return len(str(content))
        except Exception:
            return 0


def append_probe_text(parts: list[str], text: str, remaining: list[int]) -> None:
    if not text or remaining[0] <= 0:
        return
    chunk = text[: remaining[0]]
    if chunk:
        parts.append(chunk)
        remaining[0] -= len(chunk)


def collect_probe_text(value: Any, parts: list[str], remaining: list[int]) -> None:
    try:
        if value is None or remaining[0] <= 0:
            return
        if isinstance(value, str):
            append_probe_text(parts, value, remaining)
            return
        if isinstance(value, bytes):
            append_probe_text(parts, value.decode("utf-8", errors="ignore"), remaining)
            return
        if isinstance(value, (int, float, bool)):
            append_probe_text(parts, str(value), remaining)
            return
        if hasattr(value, "model_dump"):
            collect_probe_text(value.model_dump(), parts, remaining)
            return
        if hasattr(value, "dict"):
            collect_probe_text(value.dict(), parts, remaining)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                append_probe_text(parts, str(key), remaining)
                collect_probe_text(item, parts, remaining)
                if remaining[0] <= 0:
                    break
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                collect_probe_text(item, parts, remaining)
                if remaining[0] <= 0:
                    break
            return
        append_probe_text(parts, str(value), remaining)
    except Exception:
        return


def collect_structure_flags(value: Any, state: dict[str, bool]) -> None:
    try:
        if value is None:
            return
        if hasattr(value, "model_dump"):
            collect_structure_flags(value.model_dump(), state)
            return
        if hasattr(value, "dict"):
            collect_structure_flags(value.dict(), state)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = match_text(key)
                if key_text == "image_url":
                    state["vision"] = True
                if key_text in ("tool_calls", "function_call", "function_response"):
                    state["tool"] = True
                collect_structure_flags(item, state)
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                collect_structure_flags(item, state)
    except Exception:
        return


def normalize_role(role: Any) -> str:
    role_text = match_text(role)
    if role_text in ("system", "user", "assistant", "tool"):
        return role_text
    return "other"


def content_part_to_context(part: Any) -> Any:
    try:
        if part is None:
            return None
        if hasattr(part, "model_dump_for_context"):
            return part.model_dump_for_context()
        if hasattr(part, "model_dump"):
            return part.model_dump()
        if hasattr(part, "dict"):
            return part.dict()
        return part
    except Exception:
        return str(part)


def normalize_tool_call_results(tool_calls_result: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    try:
        if tool_calls_result is None:
            return normalized
        items = tool_calls_result if isinstance(tool_calls_result, list) else [tool_calls_result]
        for item in items:
            if hasattr(item, "to_openai_messages"):
                messages = item.to_openai_messages()
                if isinstance(messages, list):
                    normalized.extend(message for message in messages if isinstance(message, dict))
            elif isinstance(item, dict):
                normalized.append(item)
    except Exception:
        return normalized
    return normalized


def build_probe_messages(request: ProviderRequest) -> tuple[list[Any], dict[str, Any]]:
    messages: list[Any] = []
    meta = {"current_message_chars": 0, "has_current_message": False}
    try:
        system_prompt = safe_get(request, "system_prompt", "") or ""
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        contexts = safe_get(request, "contexts", []) or []
        if isinstance(contexts, list):
            messages.extend(contexts)

        prompt = safe_get(request, "prompt", None)
        image_urls = list(safe_get(request, "image_urls", []) or [])
        audio_urls = list(safe_get(request, "audio_urls", []) or [])
        extra_parts = list(safe_get(request, "extra_user_content_parts", []) or [])

        has_current_message = bool(prompt) or bool(image_urls) or bool(audio_urls) or bool(extra_parts)
        if has_current_message:
            content_blocks: list[Any] = []
            if isinstance(prompt, str) and prompt.strip():
                content_blocks.append({"type": "text", "text": prompt})
            elif image_urls:
                content_blocks.append({"type": "text", "text": "[image]"})
            elif audio_urls:
                content_blocks.append({"type": "text", "text": "[audio]"})

            for part in extra_parts:
                normalized_part = content_part_to_context(part)
                if normalized_part is not None:
                    content_blocks.append(normalized_part)

            for _ in image_urls:
                content_blocks.append({"type": "image_url", "image_url": {"url": "[redacted]"}})
            for _ in audio_urls:
                content_blocks.append({"type": "audio_url", "audio_url": {"url": "[redacted]"}})

            if (
                len(content_blocks) == 1
                and isinstance(content_blocks[0], dict)
                and content_blocks[0].get("type") == "text"
                and not extra_parts
                and not image_urls
                and not audio_urls
            ):
                current_message: dict[str, Any] = {
                    "role": "user",
                    "content": content_blocks[0].get("text", ""),
                }
            else:
                current_message = {"role": "user", "content": content_blocks}

            meta["has_current_message"] = True
            meta["current_message_chars"] = content_to_text_len(current_message.get("content"))
            messages.append(current_message)

        messages.extend(normalize_tool_call_results(safe_get(request, "tool_calls_result", None)))
    except Exception:
        return messages, meta
    return messages, meta


def summarize_messages(
    messages: list[Any],
    current_message_chars: int = 0,
    has_current_message: bool = False,
) -> dict[str, Any]:
    summary = {
        "messages": 0,
        "system": 0,
        "user": 0,
        "assistant": 0,
        "tool": 0,
        "other": 0,
        "system_chars": 0,
        "user_chars": 0,
        "assistant_chars": 0,
        "tool_chars": 0,
        "other_chars": 0,
        "total_chars": 0,
        "history_chars": 0,
        "max_message_role": "other",
        "max_message_chars": 0,
        "recent_history_messages": 0,
    }
    try:
        non_system_messages = 0
        for message in messages or []:
            role = normalize_role(safe_get(message, "role", "other"))
            content = safe_get(message, "content", None)
            message_chars = content_to_text_len(content)

            summary["messages"] += 1
            summary[role] += 1
            summary[f"{role}_chars"] += message_chars
            summary["total_chars"] += message_chars

            if role != "system":
                non_system_messages += 1

            if message_chars > summary["max_message_chars"]:
                summary["max_message_chars"] = message_chars
                summary["max_message_role"] = role

        summary["history_chars"] = max(
            summary["total_chars"] - summary["system_chars"] - int(current_message_chars or 0),
            0,
        )
        summary["recent_history_messages"] = max(non_system_messages - (1 if has_current_message else 0), 0)
    except Exception:
        return summary
    return summary


def get_event_extra_text(event: AstrMessageEvent | None) -> str:
    parts: list[str] = []
    try:
        if event is None:
            return ""
        for key in EVENT_META_KEYS:
            value = event.get_extra(key, None)
            if value not in (None, ""):
                parts.append(str(value))
    except Exception:
        return ""
    return " ".join(parts)


def get_system_prompt_text(messages: list[Any]) -> str:
    parts: list[str] = []
    try:
        for message in messages or []:
            if normalize_role(safe_get(message, "role", "other")) != "system":
                continue
            content = safe_get(message, "content", "")
            if isinstance(content, str):
                parts.append(content)
            else:
                text_parts: list[str] = []
                remaining = [20000]
                collect_probe_text(content, text_parts, remaining)
                parts.append("\n".join(text_parts))
    except Exception:
        return ""
    return "\n".join(part for part in parts if part)


def json_preview(text: str, limit: int = 300) -> str:
    try:
        value = (text or "")[: max(int(limit or 0), 0)]
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return '""'


def build_prompt_probe(system_prompt: str) -> dict[str, Any]:
    try:
        lower_prompt = (system_prompt or "").lower()
        contains_qzone = any(keyword.lower() in lower_prompt for keyword in PROMPT_PROBE_KEYWORDS["qzone"])
        contains_proactive = any(keyword.lower() in lower_prompt for keyword in PROMPT_PROBE_KEYWORDS["proactive"])
        contains_slc = any(
            keyword.lower() in lower_prompt for keyword in PROMPT_PROBE_KEYWORDS["shared_life_context"]
        )
        contains_affective = any(keyword.lower() in lower_prompt for keyword in PROMPT_PROBE_KEYWORDS["affective"])
        return {
            "contains_qzone": contains_qzone,
            "contains_proactive": contains_proactive,
            "contains_shared_life_context": contains_slc,
            "contains_affective": contains_affective,
            "system_head": (system_prompt or "")[:300],
            "system_tail": (system_prompt or "")[-300:] if system_prompt else "",
        }
    except Exception:
        return {
            "contains_qzone": False,
            "contains_proactive": False,
            "contains_shared_life_context": False,
            "contains_affective": False,
            "system_head": "",
            "system_tail": "",
        }


def safe_call(obj: Any, method_name: str, default: Any = None) -> Any:
    try:
        method = getattr(obj, method_name, None)
        if callable(method):
            return method()
    except Exception:
        return default
    return default


def get_event_type(event: AstrMessageEvent | None) -> str:
    try:
        if event is None:
            return "unknown"
        if safe_call(event, "is_private_chat", False):
            return "private_chat"
        if safe_call(event, "get_group_id", None):
            return "group_chat"
        message_obj_type = normalize_field(safe_get_nested(event, ("message_obj", "type"), None), default="")
        if message_obj_type:
            return message_obj_type
        return normalize_field(type(event).__name__, default="unknown")
    except Exception:
        return "unknown"


def get_user_label(event: AstrMessageEvent | None, mask_session_value: bool = True) -> str:
    try:
        if event is None:
            return "***"
        user_id = (
            safe_call(event, "get_sender_id", None)
            or safe_get(event, "sender_id", None)
            or safe_get_nested(event, ("message_obj", "sender", "user_id"), None)
            or safe_get_nested(event, ("message_obj", "user_id"), None)
        )
        if not mask_session_value:
            return normalize_field(user_id, default="unknown")
        return "user:***" if user_id not in (None, "") else "***"
    except Exception:
        return "***"


def get_conversation_label(event: AstrMessageEvent | None, mask_session_value: bool = True) -> str:
    try:
        if event is None:
            return "***"
        for key in ("conversation_id", "conversation", "conv_id"):
            value = event.get_extra(key, None)
            if value not in (None, ""):
                return mask_id(str(value)) if mask_session_value else str(value)
        value = safe_get(event, "conversation_id", None)
        if value:
            return mask_id(str(value)) if mask_session_value else str(value)
        return get_session_label(event, mask_session_value=mask_session_value)
    except Exception:
        return "***"


def get_message_origin(event: AstrMessageEvent | None, has_current_message: bool = False) -> str:
    try:
        if event is not None:
            for key in ("message_origin", "origin", "sender_type", "message_source"):
                value = event.get_extra(key, None)
                normalized = match_text(value)
                if normalized in ("user", "bot", "system", "timer"):
                    return normalized

        if has_current_message:
            event_type = get_event_type(event)
            if event_type in ("private_chat", "group_chat"):
                return "user"
        return "unknown"
    except Exception:
        return "unknown"


def get_current_context_task(event: AstrMessageEvent | None) -> str:
    try:
        if event is None:
            return "unknown"
        for key in ("current_task", "task", "task_type", "action_type", "source"):
            value = event.get_extra(key, None)
            normalized = normalize_field(value, default="")
            if normalized:
                return normalized
    except Exception:
        return "unknown"
    return "unknown"


def message_content_to_text(content: Any) -> str:
    try:
        if isinstance(content, str):
            return content
        parts: list[str] = []
        collect_probe_text(content, parts, [300000])
        return "\n".join(parts)
    except Exception:
        return ""


def build_prompt_parts(
    messages: list[Any],
    has_current_message: bool = False,
) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    try:
        current_user_index = -1
        if has_current_message:
            for idx in range(len(messages or []) - 1, -1, -1):
                if normalize_role(safe_get(messages[idx], "role", "other")) == "user":
                    current_user_index = idx
                    break

        system_seen = 0
        for idx, message in enumerate(messages or []):
            role = normalize_role(safe_get(message, "role", "other"))
            content = safe_get(message, "content", None)
            text = message_content_to_text(content)
            if role == "system":
                part = "system" if system_seen == 0 else "plugin_injection"
                system_seen += 1
            elif idx == current_user_index:
                part = "user"
            else:
                part = "history"
            parts.append({"part": part, "role": role, "message_index": idx, "text": text})
    except Exception:
        return parts
    return parts


def find_keyword_hits_in_text(
    text: str,
    keywords: tuple[str, ...] | list[str],
    *,
    part: str,
    message_index: int | None = None,
    max_hits: int = 10,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    try:
        source_text = text or ""
        lower_text = source_text.lower()
        for keyword in keywords:
            needle = str(keyword or "")
            if not needle:
                continue
            lower_needle = needle.lower()
            positions: list[int] = []
            start = 0
            while True:
                index = lower_text.find(lower_needle, start)
                if index < 0:
                    break
                positions.append(index)
                start = index + max(len(lower_needle), 1)
            if not positions:
                continue
            first_index = positions[0]
            context_start = max(first_index - 150, 0)
            context_end = min(first_index + len(needle) + 150, len(source_text))
            hits.append(
                {
                    "part": part,
                    "message_index": message_index,
                    "keyword": needle,
                    "count": len(positions),
                    "first_index": first_index,
                    "context": source_text[context_start:context_end],
                }
            )
            if len(hits) >= max_hits:
                break
    except Exception:
        return hits
    return hits


def find_prompt_hits(parts: list[dict[str, Any]], max_hits: int = 10) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    try:
        for part in parts or []:
            hits.extend(
                find_keyword_hits_in_text(
                    str(part.get("text", "")),
                    QZONE_KEYWORDS,
                    part=str(part.get("part", "unknown")),
                    message_index=int(part.get("message_index", -1)),
                    max_hits=max_hits - len(hits),
                )
            )
            if len(hits) >= max_hits:
                break
    except Exception:
        return hits
    return hits[:max_hits]


def split_system_segments(system_prompt: str) -> list[dict[str, Any]]:
    try:
        text = system_prompt or ""
        if not text:
            return []
        starts = {0}
        heading_re = re.compile(r"(?m)^(?:#{1,6}\s+.+|【[^】]{1,80}】.*|\[[^\]]{1,80}\].*|\s*\[系统任务.*)$")
        for match in heading_re.finditer(text):
            starts.add(match.start())
        sorted_starts = sorted(starts)
        segments: list[dict[str, Any]] = []
        for idx, start in enumerate(sorted_starts):
            end = sorted_starts[idx + 1] if idx + 1 < len(sorted_starts) else len(text)
            segment_text = text[start:end].strip()
            if segment_text:
                segments.append({"index": len(segments), "text": segment_text})
        if not segments:
            segments.append({"index": 0, "text": text})
        return segments
    except Exception:
        return [{"index": 0, "text": system_prompt or ""}]


def classify_system_segment(segment_text: str, segment_index: int) -> str:
    try:
        lower_text = (segment_text or "").lower()
        if any(keyword.lower() in lower_text for keyword in QZONE_KEYWORDS):
            return "plugin_qzone"
        if any(keyword.lower() in lower_text for keyword in PROMPT_PROBE_KEYWORDS["proactive"]):
            return "proactive_prompt"
        if any(keyword.lower() in lower_text for keyword in PROMPT_PROBE_KEYWORDS["shared_life_context"]):
            return "plugin_shared_life_context"
        if any(keyword.lower() in lower_text for keyword in PROMPT_PROBE_KEYWORDS["affective"]):
            return "plugin_affection"
        if segment_index == 0:
            return "base_persona"
        return "unknown"
    except Exception:
        return "unknown"


def build_system_segments(system_prompt: str) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    try:
        for raw_segment in split_system_segments(system_prompt):
            text = str(raw_segment.get("text", ""))
            lower_text = text.lower()
            segments.append(
                {
                    "segment": int(raw_segment.get("index", len(segments))),
                    "source": classify_system_segment(text, int(raw_segment.get("index", len(segments)))),
                    "chars": len(text),
                    "contains_qzone": any(keyword.lower() in lower_text for keyword in QZONE_KEYWORDS),
                    "contains_proactive": any(
                        keyword.lower() in lower_text for keyword in PROMPT_PROBE_KEYWORDS["proactive"]
                    ),
                    "contains_shared_life_context": any(
                        keyword.lower() in lower_text
                        for keyword in PROMPT_PROBE_KEYWORDS["shared_life_context"]
                    ),
                    "head": text[:80],
                }
            )
    except Exception:
        return segments
    return segments


def scan_messages(messages: list[Any], max_probe_chars: int = 300000, extra_text: str = "") -> dict[str, Any]:
    flags = {
        "slc": False,
        "retrieval": False,
        "vision": False,
        "proactive": False,
        "qzone": False,
        "self_learning": False,
        "affective": False,
        "social_context": False,
        "plugin_injection": False,
        "tool": False,
    }
    probe_text = ""
    try:
        remaining = [max(int(max_probe_chars or 0), 0)]
        parts: list[str] = []
        for message in messages or []:
            role = normalize_role(safe_get(message, "role", "other"))
            if role == "tool":
                flags["tool"] = True
            if safe_get(message, "tool_calls", None) is not None or safe_get(message, "function_call", None) is not None:
                flags["tool"] = True
            collect_structure_flags(message, flags)
            collect_probe_text(message, parts, remaining)
            if remaining[0] <= 0:
                break

        if extra_text and remaining[0] > 0:
            append_probe_text(parts, extra_text, remaining)

        probe_text = "\n".join(parts).lower()

        flags["slc"] = any(keyword.lower() in probe_text for keyword in SLC_KEYWORDS)
        flags["retrieval"] = any(keyword.lower() in probe_text for keyword in RETRIEVAL_KEYWORDS)
        flags["proactive"] = any(keyword.lower() in probe_text for keyword in PROACTIVE_KEYWORDS)
        flags["qzone"] = any(keyword.lower() in probe_text for keyword in QZONE_KEYWORDS)
        flags["vision"] = flags["vision"] or any(keyword.lower() in probe_text for keyword in VISION_KEYWORDS)
        flags["tool"] = flags["tool"] or any(keyword.lower() in probe_text for keyword in TOOL_KEYWORDS)
        flags["self_learning"] = any(keyword.lower() in probe_text for keyword in SELF_LEARNING_KEYWORDS)
        flags["affective"] = any(keyword.lower() in probe_text for keyword in AFFECTIVE_KEYWORDS)
        flags["social_context"] = any(keyword.lower() in probe_text for keyword in SOCIAL_CONTEXT_KEYWORDS)

        plugin_keyword_hit = any(keyword.lower() in probe_text for keyword in PLUGIN_KEYWORDS)
        system_count = sum(
            1 for message in messages or [] if normalize_role(safe_get(message, "role", "other")) == "system"
        )
        flags["plugin_injection"] = (
            plugin_keyword_hit
            or flags["slc"]
            or flags["retrieval"]
            or flags["proactive"]
            or flags["qzone"]
            or flags["self_learning"]
            or flags["affective"]
            or flags["social_context"]
            or system_count > 1
        )
    except Exception:
        return {"probe_text": probe_text, "flags": flags}
    return {"probe_text": probe_text, "flags": flags}


def detect_flags(messages: list[Any], max_probe_chars: int = 300000, extra_text: str = "") -> dict[str, bool]:
    result = scan_messages(messages, max_probe_chars=max_probe_chars, extra_text=extra_text)
    return result["flags"]


def get_extra_value(event: AstrMessageEvent | None, keys: tuple[str, ...]) -> str:
    try:
        if event is None:
            return "unknown"
        for key in keys:
            value = event.get_extra(key, None)
            normalized = normalize_field(value, default="")
            if normalized:
                return normalized
    except Exception:
        return "unknown"
    return "unknown"


def infer_plugin_name(flags: dict[str, bool], probe_text: str, stack_plugin: str) -> str:
    if stack_plugin != "unknown":
        return stack_plugin
    if "qzone_life_bridge" in probe_text or "qzone_auto_like" in probe_text:
        return "astrbot_plugin_qzone_life_bridge"
    if flags.get("affective"):
        return "astrbot_plugin_affective_engine"
    if flags.get("self_learning") or flags.get("social_context"):
        return "astrbot_plugin_self_learning"
    if flags.get("slc"):
        return "astrbot_plugin_shared_life_context"
    if flags.get("proactive"):
        return "astrbot_plugin_proactive_chat"
    return "unknown"


def detect_qzone_task(probe_text: str, flags: dict[str, bool], hint_text: str = "") -> str:
    text = f"{probe_text or ''}\n{hint_text or ''}".lower()
    if any(marker in text for marker in ("should_post", "qzone_should_post", "should_post_qzone", "qzone_decision")):
        return "qzone_should_post"
    if any(marker in text for marker in ("rewrite_qzone", "qzone_rewrite", "polish_qzone", "qzone_refine")):
        return "qzone_rewrite"
    if flags.get("tool") or any(marker in text for marker in ("qzone_tool", "qzone_auto_like", "tool_call")):
        return "qzone_tool"
    if any(marker in text for marker in ("dynamic_generate", "post_qzone", "qzone_generate", "generate_qzone")):
        return "qzone_generate"
    if any(marker in text for marker in ("qzone_life_bridge", "qzone")):
        return "qzone_tool"
    return "unknown"


def get_task_source(
    task: str,
    *,
    explicit_values: list[str],
    stack_plugin: str,
    plugin: str,
    flags: dict[str, bool],
    has_current_message: bool,
) -> str:
    try:
        explicit_hit = [value for value in explicit_values if canonicalize_task(value) == task]
        if explicit_hit:
            return f"event_extra:{explicit_hit[0]}"
        if stack_plugin != "unknown" and task != "chat":
            return f"stack_plugin:{stack_plugin}"
        if plugin != "unknown" and task != "chat":
            return f"plugin:{plugin}"
        if task == "chat" and has_current_message:
            return "current_user_message"
        active_flags = ",".join(name for name, enabled in flags.items() if enabled)
        return f"prompt_flags:{active_flags or 'none'}"
    except Exception:
        return "unknown"


def detect_task(
    messages: list[Any],
    event: AstrMessageEvent | None = None,
    request: ProviderRequest | None = None,
    response: LLMResponse | None = None,
    flags: dict[str, bool] | None = None,
    extra_text: str = "",
    stack_plugin: str = "unknown",
    plugin: str = "unknown",
    has_current_message: bool = False,
    event_type: str = "unknown",
    message_origin: str = "unknown",
) -> tuple[str, str, list[str]]:
    try:
        flags = flags or detect_flags(messages, max_probe_chars=20000, extra_text=extra_text)
        explicit_values: list[str] = []
        if event is not None:
            explicit_values.extend(
                [
                    get_extra_value(event, ("task",)),
                    get_extra_value(event, ("task_type",)),
                    get_extra_value(event, ("action_type",)),
                    get_extra_value(event, ("source",)),
                ]
            )

        if event_type in ("private_chat", "group_chat") and message_origin == "user" and has_current_message:
            return "chat", "user_message_event_priority", explicit_values

        for value in explicit_values:
            canonical = canonicalize_task(value)
            if canonical != "unknown":
                return canonical, f"event_extra:{value}", explicit_values

        stack_or_plugin_text = f"{stack_plugin or ''}\n{plugin or ''}\n{extra_text or ''}".lower()
        qzone_owner = "qzone" in stack_or_plugin_text or "qq空间" in stack_or_plugin_text
        if flags.get("qzone") and (qzone_owner or not has_current_message):
            qzone_task = detect_qzone_task(extra_text, flags, hint_text=stack_or_plugin_text)
            if qzone_task == "unknown":
                scan_result = scan_messages(messages, max_probe_chars=20000, extra_text=extra_text)
                qzone_task = detect_qzone_task(scan_result.get("probe_text", ""), flags, hint_text=stack_or_plugin_text)
            if qzone_task != "unknown":
                return qzone_task, get_task_source(
                    qzone_task,
                    explicit_values=explicit_values,
                    stack_plugin=stack_plugin,
                    plugin=plugin,
                    flags=flags,
                    has_current_message=has_current_message,
                ), explicit_values

        if flags.get("proactive") and ("proactive" in stack_or_plugin_text or not has_current_message):
            return "proactive", get_task_source(
                "proactive",
                explicit_values=explicit_values,
                stack_plugin=stack_plugin,
                plugin=plugin,
                flags=flags,
                has_current_message=has_current_message,
            ), explicit_values
        if flags.get("slc") and not has_current_message:
            return "shared_life_refresh", get_task_source(
                "shared_life_refresh",
                explicit_values=explicit_values,
                stack_plugin=stack_plugin,
                plugin=plugin,
                flags=flags,
                has_current_message=has_current_message,
            ), explicit_values
        if flags.get("affective") and ("affective" in stack_or_plugin_text or not has_current_message):
            return "affective", get_task_source(
                "affective",
                explicit_values=explicit_values,
                stack_plugin=stack_plugin,
                plugin=plugin,
                flags=flags,
                has_current_message=has_current_message,
            ), explicit_values
        if has_current_message:
            return "chat", get_task_source(
                "chat",
                explicit_values=explicit_values,
                stack_plugin=stack_plugin,
                plugin=plugin,
                flags=flags,
                has_current_message=has_current_message,
            ), explicit_values
        if response is not None:
            if safe_get(response, "role", "") == "tool":
                return "unknown", "response_role:tool", explicit_values
            if safe_get(response, "tools_call_name", None):
                return "unknown", "response_tools_call", explicit_values
        if request is not None and safe_get(request, "image_urls", None):
            return "vision", "request:image_urls", explicit_values
        if flags.get("vision"):
            return "vision", get_task_source(
                "vision",
                explicit_values=explicit_values,
                stack_plugin=stack_plugin,
                plugin=plugin,
                flags=flags,
                has_current_message=has_current_message,
            ), explicit_values
        if flags.get("retrieval"):
            return "retrieval", get_task_source(
                "retrieval",
                explicit_values=explicit_values,
                stack_plugin=stack_plugin,
                plugin=plugin,
                flags=flags,
                has_current_message=has_current_message,
            ), explicit_values
        return "unknown", "no_signal", explicit_values
    except Exception:
        return "unknown", "exception", []


def safe_get_usage(response: Any) -> dict[str, int]:
    try:
        candidates = [
            safe_get(response, "usage", None),
            safe_get_nested(response, ("raw_completion", "usage"), None),
            safe_get_nested(response, ("raw_response", "usage"), None),
            safe_get_nested(response, ("response", "usage"), None),
        ]
        if isinstance(response, dict):
            candidates.append(response.get("usage"))

        for usage in candidates:
            if usage is None:
                continue

            prompt_tokens = safe_get(usage, "prompt_tokens", None)
            if prompt_tokens is None:
                prompt_tokens = safe_get(usage, "input", None)
            if prompt_tokens is None:
                input_other = safe_get(usage, "input_other", 0) or 0
                input_cached = safe_get(usage, "input_cached", 0) or 0
                prompt_tokens = input_other + input_cached

            completion_tokens = safe_get(usage, "completion_tokens", None)
            if completion_tokens is None:
                completion_tokens = safe_get(usage, "output", None)

            total_tokens = safe_get(usage, "total_tokens", None)
            if total_tokens is None:
                total_tokens = safe_get(usage, "total", None)
            if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
                total_tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)

            if prompt_tokens is not None or completion_tokens is not None or total_tokens is not None:
                return {
                    "prompt_tokens": int(prompt_tokens or 0),
                    "completion_tokens": int(completion_tokens or 0),
                    "total_tokens": int(total_tokens or 0),
                }
    except Exception:
        return {}
    return {}


def safe_get_request_id(response: Any) -> str | None:
    try:
        candidates = (
            safe_get(response, "id", None),
            safe_get(response, "request_id", None),
            safe_get_nested(response, ("raw_completion", "id"), None),
            safe_get_nested(response, ("raw_completion", "request_id"), None),
            safe_get_nested(response, ("headers", "x-request-id"), None),
            safe_get_nested(response, ("raw_completion", "headers", "x-request-id"), None),
        )
        for candidate in candidates:
            if candidate:
                return str(candidate)

        headers = safe_get(response, "headers", None)
        if headers and hasattr(headers, "get"):
            request_id = headers.get("x-request-id")
            if request_id:
                return str(request_id)

        raw_completion = safe_get(response, "raw_completion", None)
        headers = safe_get(raw_completion, "headers", None)
        if headers and hasattr(headers, "get"):
            request_id = headers.get("x-request-id")
            if request_id:
                return str(request_id)
    except Exception:
        return None
    return None


def mask_id(value: str | None) -> str:
    try:
        if not value:
            return "***"
        if ":" in value:
            prefix = value.split(":", 1)[0]
            return f"{prefix}:***"
        return "***"
    except Exception:
        return "***"


def get_provider_name(provider_or_event: Any = None, context: Context | None = None) -> str:
    try:
        provider = provider_or_event
        if provider is not None and hasattr(provider, "provider_config"):
            provider_id = safe_get_nested(provider, ("provider_config", "id"), None)
            provider_type = safe_get_nested(provider, ("provider_config", "type"), None)
            provider_vendor = safe_get_nested(provider, ("provider_config", "provider"), None)
            return normalize_field(provider_id or provider_vendor or provider_type, default="unknown")

        event = provider_or_event if isinstance(provider_or_event, AstrMessageEvent) else None
        if event is not None and context is not None:
            provider = context.get_using_provider(event.unified_msg_origin)
            if provider is not None:
                return get_provider_name(provider)
    except Exception:
        return "unknown"
    return "unknown"


def get_model_name(
    request_or_event: Any = None,
    response: Any = None,
    provider: Any = None,
    context: Context | None = None,
) -> str:
    try:
        response_model = safe_get(response, "model", None)
        if response_model:
            return normalize_field(response_model)

        raw_response_model = safe_get_nested(response, ("raw_completion", "model"), None)
        if raw_response_model:
            return normalize_field(raw_response_model)

        request_model = safe_get(request_or_event, "model", None)
        if request_model:
            return normalize_field(request_model)

        if provider is None and isinstance(request_or_event, AstrMessageEvent) and context is not None:
            provider = context.get_using_provider(request_or_event.unified_msg_origin)

        if provider is not None:
            model_name = safe_get(provider, "model_name", None)
            if model_name:
                return normalize_field(model_name)
            get_model = safe_get(provider, "get_model", None)
            if callable(get_model):
                model_name = get_model()
                if model_name:
                    return normalize_field(model_name)
            provider_config_model = safe_get_nested(provider, ("provider_config", "model"), None)
            if provider_config_model:
                return normalize_field(provider_config_model)
    except Exception:
        return "unknown"
    return "unknown"


def get_session_label(event: AstrMessageEvent | None, mask_session_value: bool = True) -> str:
    try:
        if event is None:
            return "***" if mask_session_value else "unknown"
        if not mask_session_value:
            return str(event.unified_msg_origin)
        if event.is_private_chat():
            return "private:***"
        if event.get_group_id():
            return "group:***"
        return mask_id(str(event.unified_msg_origin))
    except Exception:
        return "***" if mask_session_value else "unknown"


def format_key_values(payload: dict[str, Any]) -> str:
    return " ".join(f"{key}={value}" for key, value in payload.items())


def log_request_debug(meta: dict[str, Any]) -> None:
    try:
        summary = meta.get("summary", {})
        payload = {
            "request_time": meta.get("request_time", format_time(float(meta.get("timestamp", time.time())))),
            "model": meta.get("model", "unknown"),
            "provider": meta.get("provider", "unknown"),
            "task": meta.get("task", "unknown"),
            "task_source": meta.get("task_source", "unknown"),
            "stack_plugin": meta.get("stack_plugin", "unknown"),
            "event_type": meta.get("event_type", "unknown"),
            "message_origin": meta.get("message_origin", "unknown"),
            "session": meta.get("session", "***"),
            "user": meta.get("user", "***"),
            "conversation": meta.get("conversation", "***"),
            "caller": meta.get("caller", "unknown"),
            "caller_module": meta.get("caller_module", "unknown"),
            "caller_function": meta.get("caller_function", "unknown"),
            "system_chars": int(summary.get("system_chars", 0) or 0),
            "history_chars": int(summary.get("history_chars", 0) or 0),
            "user_message_chars": int(meta.get("user_message_chars", 0) or 0),
            "full_prompt_chars": int(meta.get("full_prompt_chars", summary.get("total_chars", 0)) or 0),
        }
        logger.info("[LLM_USAGE_DEBUG] request_before: %s", format_key_values(payload))
        logger.info(
            '[LLM_USAGE_DEBUG][TASK_DECISION] event_type=%s message_origin=%s caller=%s.%s '
            'current_context_task=%s detected_plugin=%s final_task=%s reason="%s"',
            meta.get("event_type", "unknown"),
            meta.get("message_origin", "unknown"),
            meta.get("caller_module", "unknown"),
            meta.get("caller_function", "unknown"),
            meta.get("current_context_task", "unknown"),
            meta.get("plugin", "unknown"),
            meta.get("task", "unknown"),
            meta.get("task_source", "unknown"),
        )
        logger.info(
            "[LLM_USAGE_DEBUG] call_stack_summary: caller=%s.%s stack_plugin=%s stack=%s",
            meta.get("caller_module", "unknown"),
            meta.get("caller_function", "unknown"),
            meta.get("stack_plugin", "unknown"),
            meta.get("stack", "unknown"),
        )
        logger.info(
            "[LLM_USAGE_DEBUG] task_context: contextvars_used=false storage=event_extra_queue "
            "task_source=%s task_candidates=%s task=%s",
            meta.get("task_source", "unknown"),
            ",".join(str(item) for item in meta.get("task_candidates", []) if item not in (None, "")) or "none",
            meta.get("task", "unknown"),
        )
    except Exception as exc:
        logger.warning("llm_usage_debug: request debug logging failed: %s", exc)


def log_prompt_hits(meta: dict[str, Any]) -> None:
    try:
        hits = meta.get("prompt_hits", []) or []
        if not hits:
            logger.info("[LLM_USAGE_DEBUG][PROMPT_HIT] none")
            return
        for hit in hits[:10]:
            logger.info(
                '[LLM_USAGE_DEBUG][PROMPT_HIT] part=%s message_index=%s keyword=%s count=%s '
                'first_index=%s context=%s',
                hit.get("part", "unknown"),
                hit.get("message_index", "unknown"),
                json_preview(str(hit.get("keyword", "")), limit=120),
                int(hit.get("count", 0) or 0),
                int(hit.get("first_index", -1) or -1),
                json_preview(str(hit.get("context", "")), limit=400),
            )
    except Exception as exc:
        logger.warning("llm_usage_debug: prompt hit logging failed: %s", exc)


def log_system_segments(meta: dict[str, Any]) -> None:
    try:
        segments = meta.get("system_segments", []) or []
        if not segments:
            logger.info("[LLM_USAGE_DEBUG][SYSTEM_SEGMENTS] none")
            return
        for segment in segments[:20]:
            logger.info(
                "[LLM_USAGE_DEBUG][SYSTEM_SEGMENTS] segment=%s source=%s chars=%s "
                "contains_qzone=%s contains_proactive=%s contains_shared_life_context=%s head=%s",
                int(segment.get("segment", 0) or 0),
                segment.get("source", "unknown"),
                int(segment.get("chars", 0) or 0),
                bool_str(segment.get("contains_qzone", False)),
                bool_str(segment.get("contains_proactive", False)),
                bool_str(segment.get("contains_shared_life_context", False)),
                json_preview(str(segment.get("head", "")), limit=120),
            )
    except Exception as exc:
        logger.warning("llm_usage_debug: system segment logging failed: %s", exc)


def log_prompt_probe(meta: dict[str, Any]) -> None:
    try:
        probe = meta.get("prompt_probe", {}) or {}
        logger.info(
            "[LLM_USAGE_DEBUG] prompt_probe:\n"
            "contains_qzone=%s\n"
            "contains_proactive=%s\n"
            "contains_shared_life_context=%s\n"
            "contains_affective=%s\n"
            "system_head=%s\n"
            "system_tail=%s",
            bool_str(probe.get("contains_qzone", False)),
            bool_str(probe.get("contains_proactive", False)),
            bool_str(probe.get("contains_shared_life_context", False)),
            bool_str(probe.get("contains_affective", False)),
            json_preview(str(probe.get("system_head", ""))),
            json_preview(str(probe.get("system_tail", ""))),
        )
    except Exception as exc:
        logger.warning("llm_usage_debug: prompt probe logging failed: %s", exc)


def get_response_text(response: Any) -> str:
    try:
        candidates = (
            safe_get(response, "completion_text", None),
            safe_get(response, "result_chain", None),
            safe_get(response, "content", None),
            safe_get(response, "message", None),
            safe_get_nested(response, ("raw_completion", "choices", 0, "message", "content"), None),
            safe_get_nested(response, ("raw_response", "choices", 0, "message", "content"), None),
        )
        for candidate in candidates:
            if candidate in (None, ""):
                continue
            if isinstance(candidate, str):
                return candidate
            text_parts: list[str] = []
            collect_probe_text(candidate, text_parts, [2000])
            if text_parts:
                return "\n".join(text_parts)
    except Exception:
        return ""
    return ""


def looks_chat_like_reply(text: str) -> bool:
    try:
        stripped = (text or "").strip()
        if not stripped or len(stripped) > 500:
            return False
        lower = stripped.lower()
        if any(marker in lower for marker in ("should_post", "qzone", "qq空间", "post_qzone", "dynamic_generate")):
            return False
        if stripped.startswith(("{", "[", "```")):
            return False
        return any(ch.isalpha() or "\u4e00" <= ch <= "\u9fff" for ch in stripped)
    except Exception:
        return False


def log_response_debug(meta: dict[str, Any], usage: dict[str, int], request_id: str | None, response: Any) -> None:
    try:
        summary = meta.get("summary", {})
        payload = {
            "request_time": meta.get("request_time", format_time(float(meta.get("timestamp", time.time())))),
            "model": meta.get("model", "unknown"),
            "provider": meta.get("provider", "unknown"),
            "task": meta.get("task", "unknown"),
            "stack_plugin": meta.get("stack_plugin", "unknown"),
            "event_type": meta.get("event_type", "unknown"),
            "message_origin": meta.get("message_origin", "unknown"),
            "session": meta.get("session", "***"),
            "user": meta.get("user", "***"),
            "conversation": meta.get("conversation", "***"),
            "caller": meta.get("caller", "unknown"),
            "caller_module": meta.get("caller_module", "unknown"),
            "caller_function": meta.get("caller_function", "unknown"),
            "system_chars": int(summary.get("system_chars", 0) or 0),
            "history_chars": int(summary.get("history_chars", 0) or 0),
            "user_message_chars": int(meta.get("user_message_chars", 0) or 0),
            "full_prompt_chars": int(meta.get("full_prompt_chars", summary.get("total_chars", 0)) or 0),
            "prompt_tokens": int(usage.get("prompt_tokens", 0) if usage else 0),
            "completion_tokens": int(usage.get("completion_tokens", 0) if usage else 0),
            "total_tokens": int(usage.get("total_tokens", 0) if usage else 0),
            "request_id": request_id or "unknown",
        }
        logger.info("[LLM_USAGE_DEBUG] response_after: %s", format_key_values(payload))
        logger.info(
            "[LLM_USAGE_DEBUG] context_cleanup: contextvars_used=false storage=event_extra_queue "
            "reset_required=false task_after_request=%s",
            meta.get("task", "unknown"),
        )
        if meta.get("task") in QZONE_TASKS and looks_chat_like_reply(get_response_text(response)):
            logger.warning("[LLM_USAGE_DEBUG][WARN] qzone task produced chat-like reply. check routing.")
    except Exception as exc:
        logger.warning("llm_usage_debug: response debug logging failed: %s", exc)


def log_anomaly_warnings(meta: dict[str, Any]) -> None:
    try:
        event_type = str(meta.get("event_type", "unknown"))
        task = str(meta.get("task", "unknown"))
        message_origin = str(meta.get("message_origin", "unknown"))
        probe = meta.get("prompt_probe", {}) or {}
        is_chat_event = (
            event_type in ("group_chat", "private_chat")
            and message_origin == "user"
            and int(meta.get("user_message_chars", 0) or 0) > 0
        )
        if is_chat_event and task in QZONE_TASKS:
            logger.warning(
                "[LLM_USAGE_DEBUG][WARN] normal chat event was tagged as qzone. "
                "possible task context leak or qzone prompt pollution."
            )
        if is_chat_event and bool(probe.get("contains_qzone", False)):
            logger.warning("[LLM_USAGE_DEBUG][WARN] chat prompt contains qzone keywords. possible prompt pollution.")
        if event_type == "private_chat" and message_origin == "user" and bool(probe.get("contains_qzone", False)):
            logger.warning("[LLM_USAGE_DEBUG][WARN] user private chat prompt contains qzone content")
        if event_type == "private_chat" and message_origin == "user" and task != "chat":
            logger.warning("[LLM_USAGE_DEBUG][WARN] user private chat was tagged as non-chat task")
    except Exception as exc:
        logger.warning("llm_usage_debug: anomaly warning failed: %s", exc)


def build_context_meta(
    *,
    event: AstrMessageEvent,
    request: ProviderRequest,
    provider_name: str,
    model_name: str,
    session_label: str,
    max_probe_chars: int,
    stack_info: dict[str, str],
) -> dict[str, Any]:
    try:
        messages, probe_meta = build_probe_messages(request)
        summary = summarize_messages(
            messages,
            current_message_chars=int(probe_meta.get("current_message_chars", 0) or 0),
            has_current_message=bool(probe_meta.get("has_current_message", False)),
        )
        extra_text = get_event_extra_text(event)
        scan_result = scan_messages(messages, max_probe_chars=max_probe_chars, extra_text=extra_text)
        flags = scan_result["flags"]
        probe_text = scan_result["probe_text"]
        has_current_message = bool(probe_meta.get("has_current_message", False))
        event_type = get_event_type(event)
        message_origin = get_message_origin(event, has_current_message=has_current_message)

        explicit_plugin = get_extra_value(event, PLUGIN_KEYS)
        explicit_caller = get_extra_value(event, CALLER_KEYS)
        explicit_source = get_extra_value(event, SOURCE_KEYS)
        stack_plugin = stack_info.get("stack_plugin", "unknown") or "unknown"
        inferred_plugin = infer_plugin_name(flags, probe_text, stack_plugin)

        plugin = explicit_plugin if explicit_plugin != "unknown" else inferred_plugin
        caller = explicit_caller if explicit_caller != "unknown" else (stack_plugin if stack_plugin != "unknown" else plugin)
        if not caller:
            caller = "unknown"
        task, task_source, task_candidates = detect_task(
            messages,
            event=event,
            request=request,
            flags=flags,
            extra_text=extra_text,
            stack_plugin=stack_plugin,
            plugin=plugin,
            has_current_message=has_current_message,
            event_type=event_type,
            message_origin=message_origin,
        )
        source = explicit_source if explicit_source != "unknown" else (plugin if plugin != "unknown" else task)

        system_prompt = get_system_prompt_text(messages)
        prompt_probe = build_prompt_probe(system_prompt)
        prompt_parts = build_prompt_parts(messages, has_current_message=has_current_message)
        prompt_hits = find_prompt_hits(prompt_parts, max_hits=10)
        system_segments = build_system_segments(system_prompt)

        return {
            "timestamp": time.time(),
            "request_time": format_time(time.time()),
            "messages_raw": messages,
            "flags": flags,
            "prompt_probe": prompt_probe,
            "prompt_hits": prompt_hits,
            "system_segments": system_segments,
            "task": task,
            "task_source": task_source,
            "task_candidates": task_candidates,
            "current_context_task": get_current_context_task(event),
            "source": normalize_field(source),
            "plugin": normalize_field(plugin),
            "caller": normalize_field(caller),
            "event_type": event_type,
            "message_origin": message_origin,
            "user": get_user_label(event, mask_session_value=True),
            "conversation": get_conversation_label(event, mask_session_value=True),
            "caller_module": normalize_field(stack_info.get("caller_module", "unknown")),
            "caller_function": normalize_field(stack_info.get("caller_function", "unknown")),
            "stack_plugin": normalize_field(stack_plugin),
            "provider": normalize_field(provider_name),
            "model": normalize_field(model_name),
            "session": session_label,
            "summary": summary,
            "user_message_chars": int(probe_meta.get("current_message_chars", 0) or 0),
            "full_prompt_chars": int(summary.get("total_chars", 0) or 0),
            "stack": stack_info.get("stack", "unknown"),
        }
    except Exception as exc:
        logger.warning("llm_usage_debug: build_context_meta failed: %s", exc)
        return {
            "timestamp": time.time(),
            "request_time": format_time(time.time()),
            "messages_raw": [],
            "flags": {
                "slc": False,
                "retrieval": False,
                "vision": False,
                "proactive": False,
                "qzone": False,
                "self_learning": False,
                "affective": False,
                "social_context": False,
                "plugin_injection": False,
                "tool": False,
            },
            "prompt_probe": build_prompt_probe(""),
            "prompt_hits": [],
            "system_segments": [],
            "task": "unknown",
            "task_source": "exception",
            "task_candidates": [],
            "current_context_task": get_current_context_task(event),
            "source": "unknown",
            "plugin": "unknown",
            "caller": "unknown",
            "event_type": get_event_type(event),
            "message_origin": get_message_origin(event, has_current_message=False),
            "user": get_user_label(event, mask_session_value=True),
            "conversation": get_conversation_label(event, mask_session_value=True),
            "caller_module": normalize_field(stack_info.get("caller_module", "unknown")),
            "caller_function": normalize_field(stack_info.get("caller_function", "unknown")),
            "stack_plugin": normalize_field(stack_info.get("stack_plugin", "unknown")),
            "provider": normalize_field(provider_name),
            "model": normalize_field(model_name),
            "session": session_label,
            "summary": {
                "messages": 0,
                "system": 0,
                "user": 0,
                "assistant": 0,
                "tool": 0,
                "other": 0,
                "system_chars": 0,
                "user_chars": 0,
                "assistant_chars": 0,
                "tool_chars": 0,
                "other_chars": 0,
                "total_chars": 0,
                "history_chars": 0,
                "max_message_role": "other",
                "max_message_chars": 0,
                "recent_history_messages": 0,
            },
            "user_message_chars": 0,
            "full_prompt_chars": 0,
            "stack": stack_info.get("stack", "unknown"),
        }


def log_context_stats(meta: dict[str, Any]) -> None:
    try:
        summary = meta["summary"]
        flags = meta["flags"]
        payload = {
            "messages": summary["messages"],
            "system": summary["system"],
            "user": summary["user"],
            "assistant": summary["assistant"],
            "tool": summary["tool"],
            "other": summary["other"],
            "system_chars": summary["system_chars"],
            "user_chars": summary["user_chars"],
            "assistant_chars": summary["assistant_chars"],
            "tool_chars": summary["tool_chars"],
            "other_chars": summary["other_chars"],
            "total_chars": summary["total_chars"],
            "history_chars": summary["history_chars"],
            "max_message": f"{summary['max_message_role']}:{summary['max_message_chars']}",
            "recent_history_messages": summary["recent_history_messages"],
            "slc": bool_str(flags["slc"]),
            "retrieval": bool_str(flags["retrieval"]),
            "vision": bool_str(flags["vision"]),
            "proactive": bool_str(flags["proactive"]),
            "qzone": bool_str(flags["qzone"]),
            "self_learning": bool_str(flags["self_learning"]),
            "affective": bool_str(flags["affective"]),
            "social_context": bool_str(flags["social_context"]),
            "plugin_injection": bool_str(flags["plugin_injection"]),
            "task": meta["task"],
            "task_source": meta.get("task_source", "unknown"),
            "message_origin": meta.get("message_origin", "unknown"),
            "current_context_task": meta.get("current_context_task", "unknown"),
            "source": meta["source"],
            "plugin": meta["plugin"],
            "caller": meta["caller"],
            "event_type": meta.get("event_type", "unknown"),
            "caller_module": meta.get("caller_module", "unknown"),
            "caller_function": meta.get("caller_function", "unknown"),
            "stack_plugin": meta["stack_plugin"],
            "session": meta["session"],
            "user": meta.get("user", "***"),
            "conversation": meta.get("conversation", "***"),
            "provider": meta["provider"],
            "model": meta["model"],
            "user_message_chars": int(meta.get("user_message_chars", 0) or 0),
            "full_prompt_chars": int(meta.get("full_prompt_chars", summary["total_chars"]) or 0),
            "contains_qzone_prompt": bool_str(meta.get("prompt_probe", {}).get("contains_qzone", False)),
            "contains_proactive_prompt": bool_str(meta.get("prompt_probe", {}).get("contains_proactive", False)),
            "contains_shared_life_context": bool_str(
                meta.get("prompt_probe", {}).get("contains_shared_life_context", False)
            ),
        }
        logger.info("[LLM_CONTEXT_STATS] %s", format_key_values(payload))
    except Exception as exc:
        logger.warning("llm_usage_debug: context stats logging failed: %s", exc)


def log_usage(meta: dict[str, Any], usage: dict[str, int], request_id: str | None = None) -> None:
    try:
        payload: dict[str, Any] = {
            "model": meta["model"],
            "task": meta["task"],
            "source": meta["source"],
            "plugin": meta["plugin"],
            "caller": meta["caller"],
            "event_type": meta.get("event_type", "unknown"),
            "caller_module": meta.get("caller_module", "unknown"),
            "caller_function": meta.get("caller_function", "unknown"),
            "stack_plugin": meta["stack_plugin"],
            "session": meta["session"],
            "user": meta.get("user", "***"),
            "conversation": meta.get("conversation", "***"),
            "provider": meta["provider"],
            "system_chars": meta.get("summary", {}).get("system_chars", 0),
            "history_chars": meta.get("summary", {}).get("history_chars", 0),
            "user_message_chars": meta.get("user_message_chars", 0),
            "full_prompt_chars": meta.get("full_prompt_chars", meta.get("summary", {}).get("total_chars", 0)),
        }
        if usage:
            payload.update(
                {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                }
            )
        else:
            payload["usage_missing"] = "true"
        if request_id:
            payload["request_id"] = request_id
        logger.info("[LLM_USAGE] %s", format_key_values(payload))
    except Exception as exc:
        logger.warning("llm_usage_debug: usage logging failed: %s", exc)


def parse_window_spec(spec: str | None) -> tuple[float | None, str]:
    if spec is None:
        return 30 * 60, "30m"
    spec_text = match_text(spec)
    if not spec_text:
        return 30 * 60, "30m"
    if spec_text == "all":
        return None, "all"
    match = re.fullmatch(r"(\d+)(m|h)", spec_text)
    if not match:
        raise ValueError("Window must be one of: 10m, 30m, 1h, 6h, all")
    value = int(match.group(1))
    unit = match.group(2)
    seconds = value * 60 if unit == "m" else value * 3600
    return float(seconds), spec_text


def format_time(ts: float) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except Exception:
        return "unknown"


def format_compact_time(ts: float) -> str:
    try:
        return time.strftime("%H:%M:%S", time.localtime(ts))
    except Exception:
        return "unknown"


@register(
    PLUGIN_NAME,
    "OpenAI",
    "Diagnose AstrBot LLM context size and token usage without changing request behavior.",
    "0.3.1",
)
class LLMUsageDebugPlugin(Star):
    def __init__(self, context: Context, config: Any = None) -> None:
        super().__init__(context, config)
        self.config = config
        self.runtime_records: deque[RuntimeRecord] = deque(maxlen=int(DEFAULT_CONFIG["runtime_stats_max_records"]))
        self.last_idle_warn_at = 0.0

    def cfg(self, key: str) -> Any:
        value = safe_get(self.config, key, None)
        if value is None:
            return DEFAULT_CONFIG.get(key)
        return value

    def enabled(self) -> bool:
        return bool(self.cfg("enabled")) and bool(self.cfg("llm_usage_debug"))

    def runtime_stats_enabled(self) -> bool:
        return self.enabled() and bool(self.cfg("enable_runtime_stats"))

    def ensure_runtime_capacity(self) -> None:
        target = max(int(self.cfg("runtime_stats_max_records") or 1), 1)
        if self.runtime_records.maxlen == target:
            return
        self.runtime_records = deque(list(self.runtime_records)[-target:], maxlen=target)

    def append_request_meta(self, event: AstrMessageEvent, meta: dict[str, Any]) -> tuple[int, int]:
        queue = event.get_extra(REQ_META_KEY, []) or []
        if not isinstance(queue, list):
            queue = []
        before_len = len(queue)
        queue.append(meta)
        event.set_extra(REQ_META_KEY, queue)
        return before_len, len(queue)

    def pop_request_meta(self, event: AstrMessageEvent) -> tuple[dict[str, Any], int, int]:
        queue = event.get_extra(REQ_META_KEY, []) or []
        if isinstance(queue, list) and queue:
            before_len = len(queue)
            meta = queue.pop(0)
            event.set_extra(REQ_META_KEY, queue)
            return meta, before_len, len(queue)
        return {}, 0, 0

    def build_runtime_record(
        self,
        meta: dict[str, Any],
        usage: dict[str, int],
    ) -> RuntimeRecord:
        summary = meta.get("summary", {})
        return RuntimeRecord(
            timestamp=float(meta.get("timestamp", time.time()) or time.time()),
            task=normalize_field(meta.get("task"), default="unknown"),
            source=normalize_field(meta.get("source"), default="unknown"),
            plugin=normalize_field(meta.get("plugin"), default="unknown"),
            caller=normalize_field(meta.get("caller"), default="unknown"),
            event_type=normalize_field(meta.get("event_type"), default="unknown"),
            caller_module=normalize_field(meta.get("caller_module"), default="unknown"),
            caller_function=normalize_field(meta.get("caller_function"), default="unknown"),
            stack_plugin=normalize_field(meta.get("stack_plugin"), default="unknown"),
            provider=normalize_field(meta.get("provider"), default="unknown"),
            model=normalize_field(meta.get("model"), default="unknown"),
            session=str(meta.get("session", "***")),
            prompt_tokens=int(usage.get("prompt_tokens", 0) if usage else 0),
            completion_tokens=int(usage.get("completion_tokens", 0) if usage else 0),
            total_tokens=int(usage.get("total_tokens", 0) if usage else 0),
            usage_missing=not bool(usage),
            system_chars=int(summary.get("system_chars", 0) or 0),
            history_chars=int(summary.get("history_chars", 0) or 0),
            user_message_chars=int(meta.get("user_message_chars", 0) or 0),
            total_chars=int(summary.get("total_chars", 0) or 0),
            full_prompt_chars=int(meta.get("full_prompt_chars", summary.get("total_chars", 0)) or 0),
            messages=int(summary.get("messages", 0) or 0),
            contains_qzone_prompt=bool(meta.get("prompt_probe", {}).get("contains_qzone", False)),
            contains_proactive_prompt=bool(meta.get("prompt_probe", {}).get("contains_proactive", False)),
            contains_shared_life_context=bool(
                meta.get("prompt_probe", {}).get("contains_shared_life_context", False)
            ),
        )

    def maybe_record_runtime_stat(self, meta: dict[str, Any], usage: dict[str, int]) -> None:
        if not self.runtime_stats_enabled():
            return
        try:
            self.ensure_runtime_capacity()
            self.runtime_records.append(self.build_runtime_record(meta, usage))
        except Exception as exc:
            logger.warning("llm_usage_debug: runtime stats record failed: %s", exc)

    def recent_records(self, window_seconds: float | None) -> list[RuntimeRecord]:
        now = time.time()
        if window_seconds is None:
            return list(self.runtime_records)
        cutoff = now - window_seconds
        return [record for record in self.runtime_records if record.timestamp >= cutoff]

    def maybe_log_idle_warn(self) -> None:
        if not self.runtime_stats_enabled() or not bool(self.cfg("idle_warn_enabled")):
            return
        try:
            window_seconds = max(int(self.cfg("idle_warn_minutes") or 0), 1) * 60
            min_calls = max(int(self.cfg("idle_warn_min_calls") or 0), 1)
            records = self.recent_records(float(window_seconds))
            if not records:
                return

            background_records = [record for record in records if record.task in BACKGROUND_TASKS]
            normal_chat_records = [record for record in records if record.task == "chat"]
            if len(background_records) < min_calls or normal_chat_records:
                return

            now = time.time()
            if now - self.last_idle_warn_at < 60:
                return

            tasks_counter = Counter(record.task for record in background_records)
            plugin_counter = Counter(record.stack_plugin for record in background_records)
            total_tokens = sum(record.total_tokens for record in background_records)
            tasks_text = ",".join(f"{name}:{count}" for name, count in tasks_counter.most_common())
            plugins_text = ",".join(f"{name}:{count}" for name, count in plugin_counter.most_common())
            logger.warning(
                "[LLM_IDLE_WARN] recent background LLM calls detected calls=%s total_tokens=%s tasks=%s stack_plugins=%s",
                len(background_records),
                total_tokens,
                tasks_text or "unknown:0",
                plugins_text or "unknown:0",
            )
            self.last_idle_warn_at = now
        except Exception as exc:
            logger.warning("llm_usage_debug: idle warn failed: %s", exc)

    def build_stats_report(self, window_arg: str | None) -> str:
        if not self.runtime_stats_enabled():
            return "LLM runtime stats are disabled. Set enable_runtime_stats=true to use /llm_usage_stats."

        try:
            window_seconds, label = parse_window_spec(window_arg)
        except ValueError as exc:
            return str(exc)

        records = self.recent_records(window_seconds)
        total_calls = len(records)
        usage_missing_count = sum(1 for record in records if record.usage_missing)
        prompt_sum = sum(record.prompt_tokens for record in records)
        completion_sum = sum(record.completion_tokens for record in records)
        total_tokens_sum = sum(record.total_tokens for record in records)

        lines = [
            f"LLM usage stats (last {label})",
            f"Total calls: {total_calls}",
            f"usage_missing: {usage_missing_count}",
            f"Total tokens: {total_tokens_sum}",
            f"Input tokens: {prompt_sum}",
            f"Output tokens: {completion_sum}",
            "",
            "By task:",
        ]

        task_groups: dict[str, list[RuntimeRecord]] = {}
        for record in records:
            task_groups.setdefault(record.task, []).append(record)

        emitted_tasks: set[str] = set()
        for task_name in FIXED_TASK_ORDER + sorted(task_groups.keys()):
            if task_name in emitted_tasks:
                continue
            emitted_tasks.add(task_name)
            group = task_groups.get(task_name, [])
            lines.append(
                f"{task_name}: calls={len(group)} total_tokens={sum(item.total_tokens for item in group)}"
            )

        lines.extend(["", "By stack_plugin:"])
        stack_counter: dict[str, list[RuntimeRecord]] = {}
        for record in records:
            stack_counter.setdefault(record.stack_plugin, []).append(record)

        if stack_counter:
            sorted_plugins = sorted(
                stack_counter.items(),
                key=lambda item: (sum(record.total_tokens for record in item[1]), len(item[1])),
                reverse=True,
            )
            for stack_plugin, group in sorted_plugins:
                lines.append(
                    f"{stack_plugin}: calls={len(group)} total_tokens={sum(item.total_tokens for item in group)}"
                )
        else:
            lines.append("unknown: calls=0 total_tokens=0")

        lines.extend(["", "Top 5 single requests:"])
        top_records = sorted(
            records,
            key=lambda record: (record.total_tokens, record.total_chars, record.history_chars, record.system_chars),
            reverse=True,
        )[:5]
        if top_records:
            for record in top_records:
                lines.append(
                    "time={time} task={task} stack_plugin={stack_plugin} event_type={event_type} caller={caller} "
                    "model={model} total_tokens={total_tokens} input_tokens={input_tokens} "
                    "output_tokens={output_tokens} system_chars={system_chars} history_chars={history_chars} "
                    "contains_qzone_prompt={contains_qzone_prompt} "
                    "contains_proactive_prompt={contains_proactive_prompt} "
                    "contains_shared_life_context={contains_shared_life_context}".format(
                        time=format_time(record.timestamp),
                        task=record.task,
                        stack_plugin=record.stack_plugin,
                        event_type=record.event_type,
                        caller=f"{record.caller_module}.{record.caller_function}",
                        model=record.model,
                        total_tokens=record.total_tokens,
                        input_tokens=record.prompt_tokens,
                        output_tokens=record.completion_tokens,
                        system_chars=record.system_chars,
                        history_chars=record.history_chars,
                        contains_qzone_prompt=bool_str(record.contains_qzone_prompt),
                        contains_proactive_prompt=bool_str(record.contains_proactive_prompt),
                        contains_shared_life_context=bool_str(record.contains_shared_life_context),
                    )
                )
        else:
            lines.append("No records.")

        if records and usage_missing_count == total_calls:
            lines.extend(
                [
                    "",
                    "usage is missing for all records, chars-only reference:",
                    f"total_chars_sum={sum(record.total_chars for record in records)}",
                    f"max_total_chars={max(record.total_chars for record in records)}",
                    f"max_history_chars={max(record.history_chars for record in records)}",
                ]
            )

        return "\n".join(lines)

    def build_recent_report(self, count_arg: str | int | None) -> str:
        if not self.runtime_stats_enabled():
            return "LLM runtime stats are disabled. Set enable_runtime_stats=true to use /llm_usage_recent."

        count = 10
        try:
            if count_arg not in (None, ""):
                count = int(count_arg)
        except (TypeError, ValueError):
            return "Count must be an integer, for example: /llm_usage_recent 20"

        count = max(min(count, 100), 1)
        records = list(self.runtime_records)[-count:]
        records.reverse()

        lines = [f"Recent LLM requests (latest {count})"]
        if not records:
            lines.append("No records.")
            return "\n".join(lines)

        for record in records:
            lines.append(
                "time={time} task={task} stack_plugin={stack_plugin} model={model} total_tokens={total_tokens} "
                "prompt={prompt} completion={completion} usage_missing={usage_missing} messages={messages} "
                "system_chars={system_chars} history_chars={history_chars}".format(
                    time=format_compact_time(record.timestamp),
                    task=record.task,
                    stack_plugin=record.stack_plugin,
                    model=record.model,
                    total_tokens=record.total_tokens,
                    prompt=record.prompt_tokens,
                    completion=record.completion_tokens,
                    usage_missing=bool_str(record.usage_missing),
                    messages=record.messages,
                    system_chars=record.system_chars,
                    history_chars=record.history_chars,
                )
            )
        return "\n".join(lines)

    def reply_text(self, text: str) -> MessageEventResult:
        return MessageEventResult().message(text).use_t2i(False)

    async def initialize(self) -> None:
        if bool(self.cfg("enable_monkey_patch_fallback")):
            logger.info(
                "llm_usage_debug: official LLM hooks are available; monkey patch fallback remains inactive.",
            )

    @filter.command("llm_usage_stats")
    async def llm_usage_stats(self, event: AstrMessageEvent, window: str | None = None) -> None:
        event.set_result(self.reply_text(self.build_stats_report(window)))

    @filter.command("llm_usage_recent")
    async def llm_usage_recent(self, event: AstrMessageEvent, count: str | int | None = None) -> None:
        event.set_result(self.reply_text(self.build_recent_report(count)))

    @filter.command("llm_usage_help")
    async def llm_usage_help(self, event: AstrMessageEvent) -> None:
        event.set_result(self.reply_text(HELP_TEXT))

    @filter.on_llm_request(priority=-10000)
    async def on_llm_request(self, event: AstrMessageEvent, request: ProviderRequest) -> None:
        if not self.enabled():
            return

        try:
            provider = self.context.get_using_provider(event.unified_msg_origin)
            provider_name = get_provider_name(provider, self.context)
            model_name = get_model_name(request, provider=provider, context=self.context)
            session_label = get_session_label(event, mask_session_value=bool(self.cfg("mask_session")))
            stack_info = capture_call_stack(depth=max(int(self.cfg("call_stack_depth") or 1), 1))
            meta = build_context_meta(
                event=event,
                request=request,
                provider_name=provider_name,
                model_name=model_name,
                session_label=session_label,
                max_probe_chars=max(int(self.cfg("max_probe_chars") or 0), 0),
                stack_info=stack_info,
            )
            queue_before, queue_after = self.append_request_meta(event, meta)
            logger.info(
                "[LLM_USAGE_DEBUG] task_context_set: contextvars_used=false storage=event_extra_queue "
                "previous_queue_len=%s new_queue_len=%s previous_task=unknown new_task=%s task_source=%s",
                queue_before,
                queue_after,
                meta.get("task", "unknown"),
                meta.get("task_source", "unknown"),
            )
            logger.info(
                "[LLM_USAGE_DEBUG][CTX_SET] old_task=%s new_task=%s source=%s",
                meta.get("current_context_task", "unknown"),
                meta.get("task", "unknown"),
                meta.get("task_source", "event_extra_queue"),
            )
            log_request_debug(meta)
            log_prompt_probe(meta)
            log_prompt_hits(meta)
            log_system_segments(meta)
            log_anomaly_warnings(meta)

            if bool(self.cfg("log_call_stack")):
                logger.info(
                    "[LLM_CALL_STACK] stack=%s stack_plugin=%s",
                    meta.get("stack", "unknown"),
                    meta.get("stack_plugin", "unknown"),
                )

            if bool(self.cfg("log_context_stats")):
                log_context_stats(meta)
        except Exception as exc:
            logger.warning("llm_usage_debug: on_llm_request failed: %s", exc)

    @filter.on_llm_response(priority=-10000)
    async def on_llm_response(self, event: AstrMessageEvent, response: LLMResponse) -> None:
        if not self.enabled():
            return

        try:
            meta, queue_before, queue_after = self.pop_request_meta(event)
            if not meta:
                provider_name = get_provider_name(event, self.context)
                model_name = get_model_name(event, response=response, context=self.context)
                stack_info = capture_call_stack(depth=max(int(self.cfg("call_stack_depth") or 1), 1))
                meta = {
                    "timestamp": time.time(),
                    "request_time": format_time(time.time()),
                    "task": "unknown",
                    "task_source": "missing_request_meta",
                    "task_candidates": [],
                    "current_context_task": get_current_context_task(event),
                    "source": "unknown",
                    "plugin": "unknown",
                    "caller": "unknown",
                    "event_type": get_event_type(event),
                    "message_origin": get_message_origin(event, has_current_message=False),
                    "user": get_user_label(event, mask_session_value=bool(self.cfg("mask_session"))),
                    "conversation": get_conversation_label(event, mask_session_value=bool(self.cfg("mask_session"))),
                    "caller_module": normalize_field(stack_info.get("caller_module", "unknown")),
                    "caller_function": normalize_field(stack_info.get("caller_function", "unknown")),
                    "stack_plugin": normalize_field(stack_info.get("stack_plugin", "unknown")),
                    "provider": provider_name,
                    "model": model_name,
                    "session": get_session_label(event, mask_session_value=bool(self.cfg("mask_session"))),
                    "prompt_probe": build_prompt_probe(""),
                    "prompt_hits": [],
                    "system_segments": [],
                    "user_message_chars": 0,
                    "full_prompt_chars": 0,
                    "stack": stack_info.get("stack", "unknown"),
                    "summary": {
                        "messages": 0,
                        "system": 0,
                        "user": 0,
                        "assistant": 0,
                        "tool": 0,
                        "other": 0,
                        "system_chars": 0,
                        "user_chars": 0,
                        "assistant_chars": 0,
                        "tool_chars": 0,
                        "other_chars": 0,
                        "history_chars": 0,
                        "total_chars": 0,
                        "max_message_role": "other",
                        "max_message_chars": 0,
                        "recent_history_messages": 0,
                    },
                }
            logger.info(
                "[LLM_USAGE_DEBUG] task_context_reset: contextvars_used=false storage=event_extra_queue "
                "queue_before=%s queue_after=%s reset_ok=%s reset_after_task=unknown",
                queue_before,
                queue_after,
                bool_str(queue_after <= queue_before),
            )
            logger.info(
                "[LLM_USAGE_DEBUG][CTX_RESET] before=%s after=%s source=%s",
                meta.get("task", "unknown"),
                "unknown",
                meta.get("task_source", "event_extra_queue"),
            )
            try:
                leftover_queue = event.get_extra(REQ_META_KEY, []) or []
                if isinstance(leftover_queue, list):
                    leftover_tasks = [str(item.get("task", "unknown")) for item in leftover_queue if isinstance(item, dict)]
                    if any(task in BACKGROUND_TASKS for task in leftover_tasks):
                        logger.warning("[LLM_USAGE_DEBUG][WARN] task context leaked after request")
            except Exception:
                pass

            usage = safe_get_usage(response)
            request_id = safe_get_request_id(response)
            response_model = get_model_name(response=response, provider=None, context=None)
            if response_model != "unknown":
                meta["model"] = response_model
            log_response_debug(meta, usage, request_id, response)

            if bool(self.cfg("log_usage")):
                if usage or bool(self.cfg("log_missing_usage")):
                    log_usage(meta, usage, request_id=request_id)

            self.maybe_record_runtime_stat(meta, usage)
            self.maybe_log_idle_warn()
        except Exception as exc:
            logger.warning("llm_usage_debug: on_llm_response failed: %s", exc)
