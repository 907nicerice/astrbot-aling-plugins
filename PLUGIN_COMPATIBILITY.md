# Plugin Compatibility

## 职责边界

| 插件 | 职责 | 不负责 |
| --- | --- | --- |
| `shared_life_context` | 今日生活状态、当前活动、能量水平 | 长期记忆、情绪连续性、token 总控 |
| `inner_continuity` | 短中期情绪连续性、未闭合话题、互动余韵 | 长期用户偏好、dashboard 展示 |
| `aling_memory` | 长期记忆、用户偏好、小细节闪回 | 代替上下文压缩、注入所有历史 |
| `context_budget_guard` | token 预算、注入长度限制 | 生成记忆内容、展示 dashboard |
| `llm_usage_debug` | LLM 调用统计和 token 统计 | 修改人格、注入生活状态 |
| `aling_life_dashboard` | 读取 JSON 状态并展示 | 直接控制人格生成、改写 prompt |

## 兼容原则

- 不同插件不要重复注入同类内容。
- 记忆类插件不能替代上下文压缩，只能提供经过筛选的相关片段。
- Dashboard 只负责观测，不负责人格生成。
- 修改一个插件时，要检查是否影响其他插件的注入顺序、字段命名、token 预算和展示读取。
- `shared_life_context` 更偏当前生活状态，`inner_continuity` 更偏近期关系连续性，`aling_memory` 更偏长期记忆。
- `context_budget_guard` 应作为预算边界，避免多个插件叠加注入导致 prompt 过长。

## 推荐检查清单

- 新增注入内容前，确认没有和已有插件表达同一类信息。
- 调整 JSON 字段前，确认 dashboard 读取逻辑仍兼容。
- 修改记忆检索前，确认 context budget 仍能限制最大注入长度。
- 修改 LLM 调用路径前，确认 usage debug 仍能统计调用和 token。
