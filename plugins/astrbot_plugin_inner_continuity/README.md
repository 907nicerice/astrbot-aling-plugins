# astrbot_plugin_inner_continuity

Inner Continuity Engine 是给阿绫使用的短期内在连续性 / 闪回缓存插件。

它负责保存“刚刚几轮对话之后，阿绫心里还挂着什么”，例如短期残留感、小细节、可以自然带出的短句闪回。它不是长期记忆库，也不是好感度系统。

核心原则：

```text
闪回可以强；检索必须干净。
```

## 功能

- 每个私聊用户维护独立状态，默认 key 为 `private:{user_id}`。
- 回复前通过 `extra_user_content_parts` 注入临时 `<inner_continuity>` 块。
- 优先使用 AstrBot `TextPart`，并在支持时调用 `mark_as_temp()`。
- 回复后异步更新短期状态，LLM 更新失败时自动降级到规则 fallback。
- 自动清理过期、过度使用和超过上限的项目。
- 可选只读 `shared_life_context` 摘要字段，用来帮助语气贴合当天状态。
- 调试命令可查看、清空、开关 debug、管理员 dump 原始 JSON。

## 和 aling_memory 的边界

`aling_memory` 负责长期事实、偏好、过去发生过的事情。Inner Continuity 只负责刚刚几轮对话的心理余波和短期小细节。

本插件不会：

- 调用 `aling_memory` 的写入接口。
- 主动写入长期记忆。
- 修改用户原始消息。
- 修改事件历史内容。
- 把 `<inner_continuity>` 渲染内容放进 memory 检索 query。

注入只发生在最终 LLM 请求前。优先通过临时 `TextPart` 进入 `extra_user_content_parts`，避免污染普通历史和长期记忆检索。

## 和 shared_life_context 的边界

`shared_life_context` 描述“阿绫今天在过什么日子”。Inner Continuity 描述“刚刚你们聊完之后她还挂着什么”。

本插件可以在 `read_shared_life_context=true` 时只读这些摘要字段：

- `current_activity`
- `energy_level`
- `ambient_mood`
- `current_period`

本插件不会写入 shared_life_context，也不会把用户刚刚聊的 bug、token、prompt、插件方案塞进 SLC。

## 状态结构

状态文件默认写入：

```text
data/plugin_data/astrbot_plugin_inner_continuity/data/inner_continuity/{safe_user_key}.json
```

核心字段：

- `mood_hint`：轻量情绪和表达倾向，只允许“平静 / 有点认真 / 松弛 / 有点困 / 被逗乐”等弱标签。
- `residue`：这几轮对话留下的短期残留感。
- `micro_details`：不值得进入长期记忆、但接下来几轮可能自然回勾的小细节。
- `flashback_candidates`：聊天中可以顺口带出的一小句闪回素材。
- `cooldown`：注入和闪回冷却时间。

不会保存 `love`、`affection`、`romance_score`、`dependence`、`possessiveness` 之类字段。

## 配置项

配置 schema 位于 `_conf_schema.json`。

```json
{
  "enabled": true,
  "inject_enabled": true,
  "update_enabled": true,
  "use_llm_update": true,
  "read_shared_life_context": true,
  "max_residue_items": 5,
  "max_micro_details": 6,
  "max_flashback_candidates": 4,
  "default_ttl_minutes": 180,
  "strong_ttl_minutes": 720,
  "max_injected_chars": 900,
  "min_update_interval_seconds": 60,
  "flashback_cooldown_seconds": 300,
  "debug": false
}
```

说明：

- `inject_enabled=false`：不注入短期连续性，但仍可按 `update_enabled` 更新状态。
- `use_llm_update=false`：不额外调用 LLM，只启用低强度规则 fallback。
- `read_shared_life_context=false`：完全不读取 SLC。
- `max_injected_chars`：控制单轮注入字符数，默认不超过 900。
- `min_update_interval_seconds`：控制回复后更新频率，避免连续短消息刷 LLM。
- `flashback_cooldown_seconds`：控制闪回短句出现频率。

## 命令

```text
/inner
/inner_clear
/inner_debug on
/inner_debug off
/inner_dump
```

`/inner` 查看当前用户状态摘要。

`/inner_clear` 清空当前用户状态。

`/inner_debug on|off` 开关调试日志。

`/inner_dump` 输出原始 JSON，仅管理员可用。

## Token 控制策略

- 默认注入不超过 900 字符。
- `residue` 最多注入 3 条。
- `micro_details` 最多注入 3 条。
- `flashback_candidates` 最多注入 3 条。
- 选择时优先 strength 高、used_count 少、和用户最新消息相关的项目。
- 闪回短句有独立冷却，避免每轮都“我还记得”。
- 普通短寒暄不会生成大量 residue，也不会触发大段注入。
- 更新 prompt 只包含用户最新原始消息、阿绫最新回复、旧短期状态摘要和可选 SLC 摘要，不携带完整 system/persona prompt。

## 常见问题

### 它会让 aling_memory 检索变脏吗？

设计目标是不让它参与 memory 检索。插件不修改原始用户消息，不调用长期记忆写入接口，也不会把短期状态文本交给 `aling_memory`。

### LLM 更新失败会影响聊天吗？

不会。回复后更新是异步任务，provider 调用失败只写 warning，然后使用规则 fallback 或跳过更新。

### 为什么不是好感度系统？

Inner Continuity 只保存短期心理余波和可自然回勾的小细节。亲近感最多作为轻微语气背景，不会有恋爱值、依赖度或持续推动暧昧的状态字段。

### 和 shared_life_context 重叠怎么办？

SLC 是今天的生活舞台，Inner Continuity 是刚刚你们的心理余波。插件只读 SLC 摘要，不写 SLC。
