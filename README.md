# AstrBot Aling Plugins

阿绫相关 AstrBot 插件的总导航仓库。每个插件使用独立仓库、独立版本和独立发布；本仓库只维护插件索引、组合建议、兼容关系和公共文档。

## 插件列表

| 插件 | 用途 |
| --- | --- |
| [astrbot_plugin_aling_memory](https://github.com/907nicerice/astrbot_plugin_aling_memory) | 长期小记忆、User Life Mirror 与上下文摘要 |
| [astrbot_plugin_inner_continuity](https://github.com/907nicerice/astrbot_plugin_inner_continuity) | 最近几轮对话的情绪余波、小细节和闪回缓存 |
| [astrbot_plugin_companion_support](https://github.com/907nicerice/astrbot_plugin_companion_support) | 陪伴对话的倾听、共情、风险识别和回复策略 |
| [astrbot_plugin_shared_life_context](https://github.com/907nicerice/astrbot_plugin_shared_life_context) | 阿绫当前生活状态和每日生活上下文 |
| [astrbot_plugin_qzone_life_bridge](https://github.com/907nicerice/astrbot_plugin_qzone_life_bridge) | 将生活上下文连接到 QQ 空间内容生成流程 |
| [astrbot_plugin_aling_life_dashboard](https://github.com/907nicerice/astrbot_plugin_aling_life_dashboard) | 只读 WebUI 状态面板 |
| [astrbot_plugin_ayling_meme](https://github.com/907nicerice/astrbot_plugin_ayling_meme) | 根据 `<meme:...>` 标记匹配并发送表情包 |
| [astrbot_plugin_llm_usage_debug](https://github.com/907nicerice/astrbot_plugin_llm_usage_debug) | 诊断 LLM 上下文大小和 token 使用量 |
| [astrbot_plugin_persona_history_filter](https://github.com/907nicerice/astrbot_plugin_persona_history_filter) | 从人格对话历史中过滤命令和调试输出 |

## 推荐组合

### 人格连续性

`aling_memory` + `inner_continuity` + `shared_life_context`

- `aling_memory` 保存少量长期事实、偏好和共同经历。
- `inner_continuity` 保存最近几轮对话的短期心理余波。
- `shared_life_context` 提供阿绫当天正在经历的生活舞台。

### QQ 空间与观测

`shared_life_context` → `qzone_life_bridge` → `aling_life_dashboard`

- `shared_life_context` 提供状态。
- `qzone_life_bridge` 消费状态并连接 QQ 空间内容流程。
- `aling_life_dashboard` 只读展示运行状态。

### 调试与历史清洁

`llm_usage_debug` + `persona_history_filter`

- `llm_usage_debug` 查看上下文与 token 使用。
- `persona_history_filter` 避免命令和调试内容污染人格历史。

## 仓库约定

- 插件源码、版本号、Issue 和 Release 在各插件独立仓库维护。
- 本仓库不再保存插件源码副本，避免多个副本产生版本漂移。
- 真实配置、运行数据、Cookie、QQ 登录态、日志和密钥不得提交。
- 插件之间的职责和兼容说明见 [PLUGIN_COMPATIBILITY.md](PLUGIN_COMPATIBILITY.md)。
