# Token Budget

Token 预算的目标是让阿绫保留必要连续性，同时避免把过多状态、记忆和调试信息塞进一次请求。

## 建议

- 长期记忆只注入与当前对话相关的片段。
- 短期连续性只保留未闭合话题和近期情绪线索。
- 今日生活状态应短而具体，避免变成完整日志。
- 调试统计默认不进入人格 prompt。
- Dashboard 展示数据不应反向扩大 prompt 注入。

## 检查点

- 修改 `aling_memory` 后，检查单次记忆注入上限。
- 修改 `inner_continuity` 后，检查近期状态摘要长度。
- 修改 `shared_life_context` 后，检查今日状态不会重复注入。
- 修改 `context_budget_guard` 后，检查所有注入插件仍被预算覆盖。
