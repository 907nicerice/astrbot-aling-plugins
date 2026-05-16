from __future__ import annotations

import re


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]|[^\s]")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    pieces = TOKEN_RE.findall(text)
    return max(1, int(len(pieces) * 0.75))


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def unique_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = item.strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    lower = text.lower()
    return [word for word in keywords if word and word.lower() in lower]


def split_tags(value: str) -> list[str]:
    parts = re.split(r"[,，\s]+", value or "")
    return unique_keep_order([part for part in parts if part])
