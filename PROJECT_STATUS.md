# Project Status

更新时间：2026-05-16

## 已复制插件

- `astrbot_plugin_aling_memory`
  - 来源：`C:\Users\82357\Documents\New project\astrbot_plugin_aling_memory`
  - 状态：已复制
- `astrbot_plugin_inner_continuity`
  - 来源：`C:\Users\82357\Documents\New project\astrbot_plugin_inner_continuity`
  - 状态：已复制
- `astrbot_plugin_shared_life_context`
  - 来源：`C:\Users\82357\Documents\Codex\2026-04-26\astrbot-astrbot-text-astrbot-plugin-shared\astrbot_plugin_shared_life_context`
  - 状态：已复制
- `astrbot_plugin_aling_life_dashboard`
  - 来源：`C:\Users\82357\Documents\Codex\2026-04-29\astrbot-astrbot-plugin-aling-life-dashboard\astrbot_plugin_aling_life_dashboard`
  - 状态：已复制
- `astrbot_plugin_context_budget_guard`
  - 来源：`C:\Users\82357\Documents\Codex\2026-05-07\astrbot-llm-token-astrbot-qq-bot\astrbot_plugin_context_budget_guard`
  - 状态：已复制
- `astrbot_plugin_llm_usage_debug`
  - 来源：`C:\Users\82357\Documents\Codex\2026-05-07\astrbot-llm-usage-debug-task-qzone\astrbot_plugin_llm_usage_debug`
  - 状态：已复制，选用较新的候选版本

## 未找到插件

无。

## 已排除内容

- 跳过插件内 `data/` 运行数据目录。
- 跳过插件内 `__pycache__/` 和 `.pyc` 编译缓存。
- 跳过插件内真实配置文件名 `config.json`。
- 跳过日志、压缩包、备份、运行缓存、会话目录和 `.env` 类文件。

## 当前重点问题

- `astrbot_plugin_aling_life_dashboard` 源码包含 dashboard 登录、cookie 状态探测和脱敏逻辑，因此严格关键词扫描会命中 `cookie`、`p_skey`、`password` 等字段名。当前未发现真实值，但提交前需要人工确认这些命中是否作为源码语义允许。
- 本机未发现 GitHub CLI `gh`，自动创建 GitHub 私有仓库和推送可能需要手动执行。

## 后续待办

- 为每个插件补充最小化示例配置。
- 补充跨插件注入顺序测试。
- 为 token 预算和 dashboard 观测输出建立回归样例。
- 在 GitHub 仓库启用私有可见性和默认分支 `main`。
