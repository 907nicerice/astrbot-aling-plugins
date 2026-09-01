# Injection Order

推荐注入顺序从稳定背景到即时状态，再到预算保护：

1. `aling_memory`: 提供少量长期记忆和偏好线索。
2. `inner_continuity`: 提供近期互动余韵、未闭合话题和短中期情绪连续性。
3. `shared_life_context`: 提供今日生活状态、当前活动和能量水平。
4. `llm_usage_debug`: 记录调用和 token 统计。

`aling_life_dashboard` 不参与人格生成注入，只读取状态并展示。所有参与注入的插件应各自限制长度，并检查叠加后的总体预算。

实际顺序应以 AstrBot 事件钩子和插件实现为准。修改任意注入插件后，需要检查最终 prompt 是否重复表达同类内容。
