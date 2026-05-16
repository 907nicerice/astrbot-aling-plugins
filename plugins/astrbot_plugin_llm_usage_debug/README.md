# astrbot_plugin_llm_usage_debug

用于诊断 AstrBot 每次 LLM 请求的上下文规模、usage 消耗，以及后台插件触发的潜在隐性开销。

这个插件只记录诊断信息，不修改 `ProviderRequest`、不修改 `response`、不改变模型参数、不改变回复逻辑，也不依赖额外第三方库。

## 插件作用

- 在请求前输出 `[LLM_CONTEXT_STATS]`
- 在响应后输出 `[LLM_USAGE]`
- 可选输出 `[LLM_CALL_STACK]`
- 在空置期间检测后台 LLM 调用并输出 `[LLM_IDLE_WARN]`
- 维护一个内存内滑动窗口统计器
- 提供命令查看最近一段时间的 LLM 消耗统计和最近请求明细

## 当前实现方式

当前版本优先使用 AstrBot 官方 hook：

- `@filter.on_llm_request()`
- `@filter.on_llm_response()`

还提供了命令：

- `/llm_usage_stats`
- `/llm_usage_recent`
- `/llm_usage_help`

`enable_monkey_patch_fallback` 仍保留在配置里，但当前版本检测到官方 hook 可用时，不会主动 patch 核心 provider。

## 目录结构

```text
astrbot_plugin_llm_usage_debug/
  main.py
  metadata.yaml
  README.md
  _conf_schema.json
```

## 安装方式

### 方式 1：直接上传插件目录

把整个 `astrbot_plugin_llm_usage_debug` 目录上传到：

```text
/AstrBot/data/plugins/
```

然后重启容器：

```bash
docker restart astrbot
```

### 方式 2：通过 git 拉取

```bash
cd /AstrBot/data/plugins
git clone <your-repo-url> astrbot_plugin_llm_usage_debug
docker restart astrbot
```

### 方式 3：通过 AstrBot WebUI 上传

如果你的 AstrBot 版本支持 WebUI 插件上传，也可以直接上传插件目录或 zip。

## 配置说明

默认配置：

```yaml
enabled: true
llm_usage_debug: true
log_context_stats: true
log_usage: true
log_missing_usage: true
mask_session: true
max_probe_chars: 300000
enable_monkey_patch_fallback: false
log_call_stack: false
call_stack_depth: 12
enable_runtime_stats: true
runtime_stats_max_records: 2000
idle_warn_enabled: true
idle_warn_minutes: 10
idle_warn_min_calls: 1
```

字段说明：

- `enabled`：插件总开关。
- `llm_usage_debug`：诊断日志总开关。
- `log_context_stats`：是否打印请求前上下文统计。
- `log_usage`：是否打印响应 usage。
- `log_missing_usage`：provider 没返回 usage 时是否打印 `usage_missing=true`。
- `mask_session`：是否脱敏 session / user id。
- `max_probe_chars`：启发式扫描的最大字符数上限。
- `enable_monkey_patch_fallback`：兼容预留项，当前版本不会主动启用 patch。
- `log_call_stack`：是否额外打印 `[LLM_CALL_STACK]`。
- `call_stack_depth`：调用栈打印深度。
- `enable_runtime_stats`：是否启用运行时滑动窗口统计。
- `runtime_stats_max_records`：最多保留多少条最近请求记录。
- `idle_warn_enabled`：是否启用空置期间后台调用告警。
- `idle_warn_minutes`：空置告警统计窗口，单位分钟。
- `idle_warn_min_calls`：窗口内达到多少次后台调用才输出告警。

## 启用方式

默认就是开启的。只要插件启用并保持下面两项为 `true` 即可：

```yaml
enabled: true
llm_usage_debug: true
```

如果你还想靠调用栈进一步定位后台插件，建议临时开启：

```yaml
log_call_stack: true
call_stack_depth: 12
```

## 日志格式

### 请求前

```text
[LLM_CONTEXT_STATS] messages=... system=... user=... assistant=... tool=... other=... system_chars=... user_chars=... assistant_chars=... tool_chars=... other_chars=... total_chars=... history_chars=... max_message=... recent_history_messages=... slc=... retrieval=... vision=... proactive=... qzone=... self_learning=... affective=... social_context=... plugin_injection=... task=... source=... plugin=... caller=... stack_plugin=... session=... provider=... model=...
```

### 调用栈

当 `log_call_stack=true` 时，会额外输出：

```text
[LLM_CALL_STACK] stack=... stack_plugin=...
```

### 响应后

```text
[LLM_USAGE] model=... prompt_tokens=... completion_tokens=... total_tokens=... task=... source=... plugin=... caller=... stack_plugin=... session=... provider=... request_id=...
```

如果 usage 缺失：

```text
[LLM_USAGE] usage_missing=true model=... task=... source=... plugin=... caller=... stack_plugin=... session=... provider=...
```

### 空置后台告警

```text
[LLM_IDLE_WARN] recent background LLM calls detected calls=3 total_tokens=xxxxx tasks=qzone:2,self_learning:1 stack_plugins=astrbot_plugin_qzone_life_bridge:2,astrbot_plugin_self_learning:1
```

## 如何查看日志

```bash
docker logs -f astrbot | grep -E "LLM_CONTEXT_STATS|LLM_USAGE|LLM_CALL_STACK|LLM_IDLE_WARN"
```

## 命令用法

### `/llm_usage_stats`

默认查看最近 30 分钟：

```text
/llm_usage_stats
```

支持时间窗口：

```text
/llm_usage_stats 10m
/llm_usage_stats 30m
/llm_usage_stats 1h
/llm_usage_stats 6h
/llm_usage_stats all
```

输出包括：

- 总请求数
- `usage_missing`
- 总 tokens / 输入 tokens / 输出 tokens
- 按 task 汇总
- 按 `stack_plugin` 汇总
- Top 5 单次请求
- 如果全部没有 usage，则补充 chars-only 参考

### `/llm_usage_recent`

默认显示最近 10 条：

```text
/llm_usage_recent
```

也可以指定条数：

```text
/llm_usage_recent 20
```

### `/llm_usage_help`

输出简短排查说明与“绕过 AstrBot provider hook”的判断提示：

```text
/llm_usage_help
```

## 如何判断高消耗来源

- `prompt_tokens` 远大于 `completion_tokens`：主要成本在输入上下文。
- `system_chars` 很大：人格 prompt、系统 prompt 或插件 system 注入偏重。
- `history_chars` 很大：历史轮数过多。
- `messages` 很多：通常说明历史上下文很长，或存在重复注入。
- `max_message=system:xxxxx`：最大开销主要来自 system prompt。
- `slc=true` 且 `system_chars` 明显上涨：`shared_life_context` 很可能是来源之一。
- `retrieval=true` 且 `total_chars` 变大：知识库检索内容偏长。
- `proactive=true`：主动消息链路偏重。
- `qzone=true`：QQ 空间链路偏重。
- `self_learning=true`：自学习链路或其 refine/reinforce/filter provider 相关链路被命中。
- `affective=true`：`affective_engine` / `inner_state` 相关链路被命中。
- `social_context=true`：自学习里的表达模式、黑话、社交上下文相关链路被命中。
- `stack_plugin=astrbot_plugin_xxx`：调用栈里已经看到了明确插件目录，优先排查它。
- `usage_missing=true`：当前 provider 没返回 usage，只能先根据 chars 规模做近似判断。

## 如何判断后台插件消耗

推荐排查流程：

1. 开启本插件。
2. 保持 `enable_runtime_stats=true`，建议同时开启 `log_call_stack=true`。
3. 空置 10 分钟不聊天。
4. 执行 `/llm_usage_stats 10m`。
5. 如果看到 `qzone / self_learning / proactive / affective / unknown`，先停对应插件继续观察。
6. 如果 `stack_plugin` 明确指向某个插件目录，优先排查那个插件。

## 如何判断插件绕过 AstrBot provider hook

这个插件只能看到经过 AstrBot 官方 LLM hook 的请求。

如果出现下面这种情况：

- DeepSeek / dsv4flash 控制台请求数继续上涨
- 但 AstrBot 日志里没有对应的 `[LLM_CONTEXT_STATS]` 或 `[LLM_USAGE]`
- `/llm_usage_stats 10m` 显示 0 次或明显偏少

那么很可能存在插件直接使用 OpenAI SDK / HTTP 客户端调用模型，绕过了 AstrBot provider hook。

此时建议 grep 插件源码中的这些关键词：

```text
openai
OpenAI
AsyncOpenAI
chat.completions
/v1/chat/completions
requests.post
httpx
aiohttp
api_key
base_url
```

## 隐私说明

这个插件不会打印：

- 完整 prompt
- 用户原文
- system prompt 原文
- 插件注入原文

日志中只输出：

- 数量
- 字符数
- role 分布
- 布尔标记
- task / source / plugin / caller / stack_plugin
- provider / model / request_id
- 脱敏后的 session

## 局限性

- 如果 provider 不返回 usage，只能记录 `usage_missing=true`。
- 字符数不等于 token 数，只能辅助判断来源。
- `task / source / plugin / caller / stack_plugin` 中的一部分是启发式推断，不是核心源码真值。
- 运行时统计是内存态的，插件重启后会清空。
- 当前版本没有默认启用 monkey patch fallback。
- 如果请求完全绕过 AstrBot 的官方 hook，这个插件无法直接拦截，只能通过“平台计费上涨但插件日志无记录”的反证法判断。

## 语法检查

建议执行：

```bash
python -m py_compile main.py
```

如果拆成多个 `.py` 文件，也请一起做编译检查。
