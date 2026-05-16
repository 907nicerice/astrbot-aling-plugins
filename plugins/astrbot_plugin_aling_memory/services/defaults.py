from __future__ import annotations


PLUGIN_NAME = "astrbot_plugin_aling_memory"

DEFAULT_CONFIG = {
    "enabled": True,
    "auto_extract_enabled": True,
    "auto_confirm_safe_preferences": False,
    "context_summary_enabled": True,
    "mirror_enabled": True,
    "debug_enabled": False,
    "summary_every_n_turns": 20,
    "summary_ttl_days": 3,
    "mirror_refresh_min_hours": 12,
    "allow_auto_overwrite_manual_mirror": False,
    "recent_trace_enabled": True,
    "recent_trace_ttl_hours": 72,
    "recent_trace_max_items_per_session": 50,
    "recent_trace_inject_max_items": 3,
    "recent_trace_inject_max_chars": 800,
    "recent_trace_min_importance": 0.35,
    "max_memory_items_total": 500,
    "max_candidates_total": 100,
    "injection_budgets": {
        "idle_chat": 0,
        "daily_chat": 400,
        "study_help": 500,
        "emotional_support": 500,
        "project_discussion": 1200,
        "command": 0,
    },
    "flashback_min_turn_gap": 10,
    "same_memory_min_hours": 48,
    "max_flashback_per_day": 5,
    "project_keywords": [
        "bot",
        "插件",
        "prompt",
        "AstrBot",
        "Napcat",
        "QQ空间",
        "上下文",
        "token",
        "Codex",
        "人格",
        "主动对话",
        "记忆插件",
    ],
    "study_keywords": ["课", "上课", "水课", "考试", "题", "物理", "高数", "积分", "矩阵"],
    "emotion_keywords": ["难受", "烦", "累", "崩", "焦虑", "好难受", "不想", "撑不住"],
}

SCENE_LIMITS = {
    "idle_chat": {"small_memory": 0, "mirror_slices": 0, "project_context": 0},
    "daily_chat": {"small_memory": 2, "mirror_slices": 1, "project_context": 0},
    "study_help": {"small_memory": 2, "mirror_slices": 1, "project_context": 0},
    "emotional_support": {"small_memory": 2, "mirror_slices": 1, "project_context": 0},
    "project_discussion": {"small_memory": 1, "mirror_slices": 2, "project_context": 5},
    "command": {"small_memory": 0, "mirror_slices": 0, "project_context": 0},
}

MIRROR_KEYS = [
    "study_life",
    "project_life",
    "interaction_style",
    "relationship_texture",
    "memory_preference",
]
