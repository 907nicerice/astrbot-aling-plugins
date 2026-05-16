# Plugin Overview

本仓库管理阿绫 QQ Bot 的 AstrBot 插件源码。

## 插件列表

- `astrbot_plugin_shared_life_context`: 管理今日生活状态、当前活动、能量水平等短周期状态。
- `astrbot_plugin_inner_continuity`: 管理短中期情绪连续性、未闭合话题和互动余韵。
- `astrbot_plugin_aling_memory`: 管理长期记忆、用户偏好和小细节闪回。
- `astrbot_plugin_context_budget_guard`: 管理注入长度和 token 预算边界。
- `astrbot_plugin_llm_usage_debug`: 统计 LLM 调用和 token 使用情况。
- `astrbot_plugin_aling_life_dashboard`: 读取状态 JSON 并提供只读展示。

## 维护原则

插件之间要保持职责清晰。一个插件新增能力时，应先确认是否属于自己的边界，避免把长期记忆、当前状态、短期连续性和观测展示混在一起。
