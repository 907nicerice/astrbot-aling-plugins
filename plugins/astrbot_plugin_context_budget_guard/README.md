# Context Budget Guard / 上下文预算守卫

`astrbot_plugin_context_budget_guard` 是一个 AstrBot LLM 请求 token 预算诊断插件。它基于 `@filter.on_llm_request()`，在模型调用前检查 `ProviderRequest`，把每轮请求大致拆成 `system_prompt`、`prompt`、`contexts`、`extra_user_content_parts`、`tools/functions`、`messages`、`image_urls` 等来源，输出字符数、粗略 token 数、风险标签和短预览。

第一版默认 `dry_run=true`，只统计、只报警、只记录日志，不修改请求体，不影响 bot 正常回复。

## 它解决什么问题

当 `/reset` 后第一轮简单聊天仍接近上万 input tokens 时，问题往往不只是历史太长，也可能来自人格 prompt、插件注入、工具描述、知识库、长期记忆、图片 base64 或大段 JSON。

Context Budget Guard 会在调用 LLM 前输出类似：

```text
[ContextBudgetGuard] session=ab12cd34 total_est_tokens=9730 total_chars=28500
  system_prompt: 4100 tok / 12000 chars
  prompt: 12 tok / 30 chars
  contexts: 1800 tok / 5400 chars / items=8
  extra_user_content_parts: 2600 tok / 7800 chars / items=3
  tools: 900 tok / 2700 chars
  risk_flags=[total_too_large, extra_too_large]
```

日志不会输出完整 prompt，只输出统计数字、字段名、风险标签和截断后的短片段预览。

## 它不是 AstrBot 上下文压缩的替代品

AstrBot 上下文压缩主要处理历史上下文过长的问题。这个插件做的是调用前诊断：告诉你每轮请求里各部分分别占多少，以及是否出现 base64、超长 JSON、疑似插件状态栏等内容。

简单说：

- 上下文压缩：帮你处理历史。
- Context Budget Guard：帮你定位本轮请求体的 token 来源。

## 与 LLM Usage Debug 的区别

LLM Usage Debug 是调用后看实际账单或 provider 返回的 usage。

Context Budget Guard 是调用前拆请求体来源，告诉你是 `system_prompt`、`contexts`、`extra_user_content_parts`、`tools` 还是其他字段在变大。

推荐两个一起用：先用 Context Budget Guard 看来源，再用 `/llm_usage_stats 1m` 对照实际 usage。

## 命令

```text
/cbg status
/cbg report
/cbg dryrun on
/cbg dryrun off
```

`/cbg status` 显示插件是否启用、dry_run 状态、阈值、最近一次请求 token 和风险标签。

`/cbg report` 显示最近 10 次请求摘要，并统计平均最大的来源：

```text
#1 total=9730 system=4100 contexts=1800 extra=2600 tools=900 flags=extra_too_large
#2 total=4200 system=3900 contexts=200 extra=50 tools=0 flags=system_prompt_too_large

Top sources:
1. system_prompt avg 4100 tokens
2. extra_user_content_parts avg 2200 tokens
3. contexts avg 1600 tokens
```

`/cbg dryrun on` 会设置 `dry_run=true`。

`/cbg dryrun off` 会设置 `dry_run=false`，但第一版的截断能力仍需额外打开 `enable_extra_trim`、`enable_context_trim` 或 `enable_base64_omit` 才会尝试修改请求。

## 风险标签

- `total_too_large`：总估算 token 超过阈值。
- `system_prompt_too_large`：人格或系统提示过大。
- `contexts_too_large`：历史上下文过大。
- `extra_too_large`：额外用户内容过大，常见于动态插件注入。
- `tools_too_large`：工具或函数描述过大。
- `single_message_too_large`：单条 message 过大。
- `base64_like_content`：检测到图片 base64 或类似长串。
- `long_json_like_content`：检测到超长 JSON-like 内容。
- `plugin_state_like_content`：检测到 affection、shared_life_context、proactive、qzone、self_learning、memory、knowledge 等疑似插件状态栏关键词。

## 推荐排查流程

1. 在聊天里执行 `/reset`。
2. 发一句简单消息，例如“阿绫”。
3. 查看 AstrBot 日志中的 `[ContextBudgetGuard]` 输出。
4. 再用 `/llm_usage_stats 1m` 对照实际 usage。
5. 如果 `system_prompt` 最大，压缩人格 prompt。
6. 如果 `contexts` 最大，调整 AstrBot 上下文轮数。
7. 如果 `extra_user_content_parts` 最大，检查 affection、SLC、proactive、qzone、self_learning 等插件注入。
8. 如果 `tools/functions` 最大，检查工具描述和函数 schema。
9. 如果出现 `base64_like_content`，检查图片、多模态历史或插件是否把图片 base64 塞进文本。

## 推荐 AstrBot 上下文配置

- 模型上下文窗口：手动设置为 8192 或 16384。
- 最多携带对话轮数：6 到 10。
- 丢弃对话轮数：2 到 4。
- 超出模型上下文窗口时：按对话轮数截断。

## 配置说明

主要配置项：

- `enabled`：是否启用插件。
- `dry_run`：只诊断不修改请求，默认 `true`。
- `log_each_request`：是否每次请求都输出统计日志。
- `debug_dump_request_fields`：是否输出 `ProviderRequest` 的字段名，不输出字段内容。
- `warn_total_tokens`：总估算 token 报警阈值。
- `system_prompt_warn_tokens`：系统提示报警阈值。
- `contexts_warn_tokens`：上下文报警阈值。
- `extra_warn_tokens`：额外内容报警阈值。
- `tools_warn_tokens`：工具描述报警阈值。
- `single_message_warn_tokens`：单条消息报警阈值。
- `long_json_warn_chars`：JSON-like 内容字符数报警阈值。
- `preview_chars`：日志短预览长度。
- `history_size`：保留最近多少次请求统计。

预留截断配置默认关闭：

- `enable_extra_trim`
- `max_extra_chars`
- `enable_context_trim`
- `keep_recent_messages`
- `enable_base64_omit`

注意：不截断 `system_prompt`，只报警。`contexts` 截断会尽量避开 tool/function 调用配对；如果检测到可能破坏配对，会跳过截断并只报警。

## 安装

将目录放到 AstrBot 的插件目录，例如：

```text
AstrBot/data/plugins/astrbot_plugin_context_budget_guard/
```

然后在 AstrBot WebUI 里重载插件，或重启 AstrBot。

## 兼容性

- Python 3.10+
- 无额外依赖
- 目标 AstrBot v4.23.x，尽量兼容 v4.16 到 v4.x
- 不使用同步网络请求
- 插件异常会被捕获并写日志，不应导致 bot 无响应
