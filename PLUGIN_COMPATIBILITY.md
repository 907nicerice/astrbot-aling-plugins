# Plugin Compatibility

## 职责边界

| 插件 | 职责 | 不负责 |
| --- | --- | --- |
| `aling_memory` | 长期事实、偏好、共同经历和上下文摘要 | 当天生活状态、每轮强制闪回 |
| `inner_continuity` | 最近几轮对话的残留感、小细节和短期闪回 | 长期记忆、好感度系统 |
| `shared_life_context` | 当前活动、能量和当天生活状态 | 长期用户记忆、QQ 空间发布 |
| `companion_support` | 陪伴对话策略、风险识别和安全引导 | 保存长期人格记忆、替代专业医疗支持 |
| `qzone_life_bridge` | 将生活上下文桥接到 QQ 空间内容流程 | 生成或维护长期记忆 |
| `aling_life_dashboard` | 只读展示插件状态 | 修改人格状态或 prompt |
| `ayling_meme` | 解析表情意图并发送匹配图片 | 记忆、情绪推理和文本生成 |
| `llm_usage_debug` | 诊断上下文大小和 token 使用 | 改写请求行为和人格内容 |
| `persona_history_filter` | 过滤命令、统计和调试输出 | 生成摘要或保存记忆 |

## 依赖关系

```text
shared_life_context
        ├──> qzone_life_bridge
        └──> aling_life_dashboard

aling_memory ───────┐
inner_continuity ───┼──> 人格连续性
companion_support ──┘

llm_usage_debug + persona_history_filter ──> 调试与历史清洁
```

## 兼容原则

- 不同插件不要重复注入同一类内容。
- 长期记忆、短期连续性和当天生活状态必须保持边界。
- Dashboard 只读，不反向修改其他插件的数据。
- 修改共享字段前，要同时检查 bridge 和 dashboard。
- 所有注入插件都应限制长度，避免叠加后上下文失控。
