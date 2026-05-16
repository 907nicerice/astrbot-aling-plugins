from __future__ import annotations

import logging
from typing import Any

from .defaults import PLUGIN_NAME

logger = logging.getLogger(PLUGIN_NAME)


def inject_text(req: Any, text: str) -> bool:
    if not text:
        return True
    try:
        if hasattr(req, "extra_user_content_parts"):
            return append_text_part(req, text)
        if _append_to_known_text_field(req, text):
            return True
        logger.warning("[aling_memory] no compatible ProviderRequest injection field found")
        return False
    except Exception:
        logger.warning("[aling_memory] failed to inject memory text", exc_info=True)
        return False


def append_text_part(req: Any, text: str) -> bool:
    if not text:
        return True
    logger.info("[aling_memory] injecting memory block chars=%s", len(text))
    try:
        parts = getattr(req, "extra_user_content_parts", None)
        if not hasattr(parts, "append"):
            parts = list(parts or [])
            setattr(req, "extra_user_content_parts", parts)
        part = _make_text_part(text)
        parts.append(part)
        logger.info("[aling_memory] injected memory part type=%s", type(part).__name__)
        return True
    except Exception:
        logger.error("[aling_memory] failed to append TextPart memory injection", exc_info=True)
        return False


def extract_user_text(event: Any = None, req: Any = None) -> str:
    for obj in (event, req):
        if obj is None:
            continue
        for name in ("message_str", "message", "content", "prompt", "query", "text"):
            value = _safe_get(obj, name)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if callable(value):
                try:
                    called = value()
                    if isinstance(called, str) and called.strip():
                        return called.strip()
                except Exception:
                    continue
    messages = _safe_get(req, "messages")
    if isinstance(messages, list):
        for item in reversed(messages):
            if _role_of(item) == "user":
                content = _content_of(item)
                if content:
                    return content
    return ""


def extract_response_text(resp: Any) -> str:
    for name in ("completion_text", "text", "content", "message", "result", "response"):
        value = _safe_get(resp, name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if callable(value):
            try:
                called = value()
                if isinstance(called, str) and called.strip():
                    return called.strip()
            except Exception:
                continue
    choices = _safe_get(resp, "choices")
    if isinstance(choices, list) and choices:
        content = _content_of(choices[0])
        if content:
            return content
    return ""


def scope_from_event(event: Any) -> str:
    value = _safe_get(event, "unified_msg_origin")
    if value:
        return str(value)
    for name in ("session_id", "group_id", "user_id"):
        value = _safe_get(event, name)
        if value:
            return str(value)
    return "default"


def _make_text_part(text: str) -> Any:
    TextPart = _load_text_part()
    try:
        return TextPart(text=text)
    except TypeError:
        try:
            return TextPart(content=text)
        except TypeError:
            logger.error("[aling_memory] TextPart constructor rejected text/content arguments", exc_info=True)
            raise


def _load_text_part() -> Any:
    try:
        from astrbot.core.provider.entities import TextPart as ImportedTextPart  # type: ignore

        return ImportedTextPart
    except Exception:
        try:
            from astrbot.core.provider.schema import TextPart as ImportedTextPart  # type: ignore

            return ImportedTextPart
        except Exception:
            logger.error("[aling_memory] TextPart is unavailable; skip extra_user_content_parts injection", exc_info=True)
            raise


def _append_to_known_text_field(req: Any, text: str) -> bool:
    for name in ("prompt", "system_prompt", "user_prompt", "content"):
        value = _safe_get(req, name)
        if isinstance(value, str):
            setattr(req, name, value + "\n\n" + text)
            return True
    messages = _safe_get(req, "messages")
    if isinstance(messages, list):
        for item in reversed(messages):
            if _role_of(item) == "user":
                return _append_to_message(item, text)
        if messages:
            return _append_to_message(messages[-1], text)
    return False


def _append_to_message(message: Any, text: str) -> bool:
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = content + "\n\n" + text
            return True
    else:
        content = _safe_get(message, "content")
        if isinstance(content, str):
            setattr(message, "content", content + "\n\n" + text)
            return True
    return False


def _safe_get(obj: Any, name: str) -> Any:
    try:
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)
    except Exception:
        return None


def _role_of(message: Any) -> str:
    value = _safe_get(message, "role")
    return str(value or "").lower()


def _content_of(message: Any) -> str:
    value = _safe_get(message, "content")
    if isinstance(value, str):
        return value.strip()
    nested = _safe_get(value, "text")
    if isinstance(nested, str):
        return nested.strip()
    return ""
