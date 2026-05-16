# astrbot-aling-plugins

这是阿绫 QQ Bot 的 AstrBot 插件集合仓库。

本仓库只保存插件源码、插件说明、插件兼容关系和示例配置。不保存主人格 prompt、普通 prompt、skill、聊天记录、真实配置、cookie、QQ 登录态、服务器配置或服务器凭据。

## 目录

- `plugins/`: AstrBot 插件源码。每个插件目录保持 AstrBot 插件自身的文件结构。
- `docs/`: 插件关系、注入顺序、token 预算、记忆系统和 dashboard 接入说明。
- `configs/examples/`: 示例配置和配置说明，只放占位符，不放真实部署值。
- `scripts/`: 后续维护脚本说明或辅助脚本。

## 安全约定

- 真实运行数据应留在 AstrBot 部署目录，不进入本仓库。
- 本仓库不提交 `.env`、真实 `config.json`、真实 `*_config.json`、NapCat 登录态、QQ 登录态、运行日志、缓存和压缩包。
- 插件示例配置必须使用占位符。
- 修改插件后，提交前需要执行敏感词和运行数据扫描。
