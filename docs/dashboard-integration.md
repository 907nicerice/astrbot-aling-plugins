# Dashboard Integration

`aling_life_dashboard` 是只读观测层。

## 定位

- 读取 JSON 状态。
- 展示生活状态、连续性、记忆和调试统计。
- 不直接控制人格生成。
- 不改写 prompt。

## 集成要求

- Dashboard 读取字段时要兼容缺失字段。
- 展示层必须脱敏，不展示真实凭据或登录态。
- 配置示例只能使用占位符。
- 修改状态 JSON 结构时，需要同步检查 dashboard 读取逻辑。

## 与其他插件关系

- 从 `shared_life_context` 读取当前生活状态。
- 从 `inner_continuity` 读取近期连续性摘要。
- 从 `aling_memory` 读取长期记忆摘要或统计。
- 从 `llm_usage_debug` 读取调用统计。
- 不替代 `context_budget_guard` 的预算控制。
