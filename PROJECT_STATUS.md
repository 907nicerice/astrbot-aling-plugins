# Project Status

更新时间：2026-09-01

## 当前结构

- 本仓库作为九个插件的总导航和兼容说明入口。
- 每个插件迁移到独立 GitHub 仓库，独立维护版本、Issue 和 Release。
- 插件源码不再复制到本仓库，避免多个副本产生版本漂移。

## 已纳入索引

- `astrbot_plugin_aling_memory`
- `astrbot_plugin_inner_continuity`
- `astrbot_plugin_companion_support`
- `astrbot_plugin_shared_life_context`
- `astrbot_plugin_qzone_life_bridge`
- `astrbot_plugin_aling_life_dashboard`
- `astrbot_plugin_ayling_meme`
- `astrbot_plugin_llm_usage_debug`
- `astrbot_plugin_persona_history_filter`

## 安全约定

- 不提交运行数据、日志、缓存、Cookie、QQ 登录态、真实配置或密钥。
- 插件独立仓库使用统一 `.gitignore` 排除常见运行产物。
- 发布前检查 `metadata.yaml` 中的仓库地址和版本号。
