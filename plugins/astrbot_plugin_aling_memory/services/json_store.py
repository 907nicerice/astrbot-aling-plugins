from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from .defaults import PLUGIN_NAME

logger = logging.getLogger(PLUGIN_NAME)


class JsonFile:
    def __init__(self, path: Path, default_data: dict[str, Any]) -> None:
        self.path = path
        self.default_data = default_data
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            data = deepcopy(self.default_data)
            self.save(data)
            return data
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, dict):
                raise ValueError("top-level JSON is not an object")
            return self._merge_versioned_defaults(data)
        except Exception as exc:
            backup = self.path.with_suffix(self.path.suffix + ".broken")
            try:
                os.replace(self.path, backup)
            except OSError:
                logger.warning("[aling_memory] failed to backup broken JSON %s", self.path, exc_info=True)
            logger.warning("[aling_memory] rebuilt broken JSON %s: %s", self.path, exc)
            data = deepcopy(self.default_data)
            self.save(data)
            return data

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(tmp, self.path)

    def _merge_versioned_defaults(self, data: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(self.default_data)
        merged.update(data)
        if "version" not in merged:
            merged["version"] = self.default_data.get("version", 1)
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
    cwd = Path.cwd()
    candidates.append(cwd / "data" / "plugin_data" / PLUGIN_NAME)
    if plugin_dir:
        candidates.append(plugin_dir / "data")
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except OSError:
            continue
    fallback = Path(__file__).resolve().parents[1] / "data"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback
