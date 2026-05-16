# astrbot_plugin_aling_memory

阿绫长期小记忆 / User Life Mirror / 上下文压缩插件。

这个插件给 AstrBot 上的阿绫提供少量、低频、受控的长期记忆能力：记住用户随口提过的小事、偏好、互动边界和少量共同经历，在上下文被截断后也能偶尔自然接上。

它不是上下文无限扩容，也不做 Open Loop Tracker。阿绫不应该变成助手、项目经理或催办工具。

## 功能

- 本地 JSON 持久化记忆，默认按 `unified_msg_origin` 会话隔离。
- 手动管理记忆：增删改查、标签、废弃。
- 保守自动候选提取：只在“记住”“我希望”“以后别”等强信号出现时触发。
- 短期上下文摘要：默认每 20 轮或手动 `/mem summarize` 生成。
- recent_trace：保存 24-72h 的轻量话题残影，用来接住“昨天/刚才/继续那个问题”。
- User Life Mirror：低频整理学习、项目、互动风格、关系质感、记忆偏好。
- 回复前检索相关记忆并注入短 XML 风格块。
- 场景识别返回 primary scene 和 labels，按 primary scene 控制预算。
- 闪回限频：默认 10 轮间隔、同一记忆 48 小时、每日最多 5 次。
- debug 日志和 `/mem inject_preview <text>` 预览。

## 为什么不做 Open Loop Tracker

这个插件只服务阿绫的人格聊天体验：熟人感、小事、偏好、关系边界和自然闪回。

它不会记录、提醒或推进用户未完成事项，也不会把项目进度变成长期人格记忆。项目背景只在用户主动聊 bot、插件、prompt、AstrBot、QQ 空间、token 等话题时辅助理解。

## 命令

```text
/mem add <type> <content>
/mem list
/mem search <keyword>
/mem show <id>
/mem delete <id>
/mem update <id> <content>
/mem tag <id> <tag1,tag2>
/mem deprecate <id>
/mem clear

/mem candidates
/mem approve <candidate_id>
/mem reject <candidate_id>

/mem mirror
/mem mirror_refresh

/mem summarize
/mem summaries
/mem summary_clear

/mem debug on
/mem debug off
/mem inject_preview <text>
```

示例：

```text
/mem add small_memory 用户提到过有一门课很水。
/mem search 水课
/mem inject_preview 今天课好无聊
```

## 配置

配置 schema 在 `astrbot_plugin_aling_memory/_conf_schema.json`。

核心配置：

- `enabled`
- `auto_extract_enabled`
- `auto_confirm_safe_preferences`
- `context_summary_enabled`
- `mirror_enabled`
- `debug_enabled`
- `summary_every_n_turns`
- `summary_ttl_days`
- `mirror_refresh_min_hours`
- `allow_auto_overwrite_manual_mirror`
- `recent_trace_enabled`
- `recent_trace_ttl_hours`
- `recent_trace_max_items_per_session`
- `recent_trace_inject_max_items`
- `recent_trace_inject_max_chars`
- `recent_trace_min_importance`
- `max_memory_items_total`
- `max_candidates_total`
- `flashback_min_turn_gap`
- `same_memory_min_hours`
- `max_flashback_per_day`

默认注入预算：

- `idle_chat`: 0
- `daily_chat`: 400
- `study_help`: 500
- `emotional_support`: 500
- `project_discussion`: 1200
- `command`: 0

## 数据文件

默认写入：

```text
data/plugin_data/astrbot_plugin_aling_memory/
  memory_store.json
  user_life_mirror.json
  context_summaries.json
  flashback_state.json
  recent_trace.json
  config.json
```

所有 JSON 顶层都带 `version` 字段，便于后续迁移。`memory_store.json` 顶层结构是：

```json
{
  "version": 1,
  "scopes": {}
}
```

## 注入策略

回复前会先识别场景：

- `idle_chat`
- `daily_chat`
- `study_help`
- `project_discussion`
- `emotional_support`
- `command`

`scene_router` 同时返回 primary scene 和 labels。预算按 primary scene 计算，debug 会输出 labels。

注入块只使用：

```xml
<aling_relevant_memory>
...
</aling_relevant_memory>

<aling_project_context>
...
</aling_project_context>

<user_life_mirror_slice>
...
</user_life_mirror_slice>

<recent_continuity>
...
</recent_continuity>
```

`idle_chat` 默认零注入。普通闲聊不会注入项目背景。User Life Mirror 只注入相关切片，不全量塞进 prompt。

## recent_trace

`recent_trace` 是 24-72 小时短期连续性缓存，不是长期记忆。它只保存短摘要，不保存完整聊天原文，也不会自动升级为长期 memory。

写入时机：

- 普通对话完成后，读取本轮用户消息和 assistant 回复。
- 只有出现“昨天、刚才、继续、插件、方案、故障、prompt、memory、截断”等延续性或技术排查信号，或者用户消息较长时才写入。
- 纯寒暄、表情、单字和无上下文价值的闲聊不会写入。

检索与注入：

- 只检索当前 `unified_msg_origin` 会话，避免串群/串私聊。
- 每次读写都会清理过期 trace。
- 只有用户消息命中“昨天、昨晚、刚才、前面、上次、继续、你忘了、还记得、说到哪、那个插件”等触发词或 recall hints 时才注入。
- 每次最多注入 `recent_trace_inject_max_items` 条，并受 `recent_trace_inject_max_chars` 限制。
- 注入内容放在 `<recent_continuity>`，明确要求阿绫不要说“根据记录显示”，只在用户延续相关话题时自然参考。

ProviderRequest 注入会做多版本兼容：

1. 优先使用 `extra_user_content_parts`。
2. 使用 AstrBot `TextPart` 注入，优先 `TextPart(text=...)`，再尝试 `TextPart(content=...)`。
3. 如果 `TextPart` 创建失败，跳过本轮记忆注入并记录 error，避免把普通字符串塞进 `extra_user_content_parts`。
4. 没有 `extra_user_content_parts` 时，才尝试追加到当前版本可用文本字段。
5. 注入失败只写 warning/error，不阻断正常聊天。

## 与其他模块关系

- `shared_life_context` 是阿绫自己的当前生活状态，本插件不写入也不覆盖。
- `affective_state` 是阿绫当前情绪余温，本插件不把一次性情绪永久化。
- Persona prompt 仍是人格核心，本插件只提供短、少、相关的辅助记忆。
- AstrBot 原始上下文仍负责最近对话，本插件只在截断后保留少量短期摘要和小记忆。

## 调试

开启：

```text
/mem debug on
```

预览某句话会注入什么：

```text
/mem inject_preview 今天课好无聊
```

返回内容包括：

- primary scene
- labels
- selected memories
- mirror slices
- recent traces
- token 估算
- 是否允许闪回
- 过滤原因
- 实际注入文本

## P0 已实现

- 本地持久化存储。
- 手动命令。
- 保守规则式候选提取。
- 手动和定期上下文摘要。
- User Life Mirror 读取和刷新。
- recent_trace 24-72h 短期连续性缓存。
- 回复前检索与注入。
- token 预算裁剪。
- 闪回频率控制。
- debug 日志和注入预览。
- ProviderRequest 和 LLMResponse 多版本兼容保护。

## TODO

- 接入更精细的 AstrBot 上下文生命周期，在真正截断前生成摘要。
- 可选接入当前 provider 做更稳的摘要和候选提取，但必须保持保守。
- 增加 Mirror 手动编辑命令。
- 根据真实 AstrBot 版本补更多 ProviderRequest 字段兼容。

## 风险

- P0 的自动提取是规则式，宁愿漏记也不多记。
- 关键词检索不能理解所有语义，需要通过 `/mem inject_preview` 调试。
- 多人共享同一个会话 scope 时仍可能共享该会话记忆；默认按会话隔离，不按个人全局隔离。
