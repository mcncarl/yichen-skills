# Codex Grok Consult

[English](./README.md) | 简体中文

`yichen-grok-consult` 让 GPT 始终作为 Codex 当前对话的主模型，同时把 Grok 当作只读第二意见或原生 X 搜索后端。

这是非官方社区插件，与 xAI、X、OpenAI 均无隶属、背书或合作关系。

## 提供的工具

- `search_x_with_grok`：启动官方 Grok Build CLI 的原生 `x_search`。只有明确的账号额度耗尽才能进入匿名 FxTwitter；该匿名路线失败后，调用方还必须在取得当前任务明确授权后传入 `allow_authenticated_fallback=true`，服务器才会放行可能读取本机 X 登录态的 OpenCLI 和 xreach。工具会提取公开 X status URL，还原 Snowflake 编号中的时间，转换时区并按滚动窗口或固定日期过滤。
- `ask_grok`：让 Grok 独立回答问题。
- `review_with_grok`：让 Grok 审阅草稿或分析。
- `challenge_with_grok`：让 Grok 反驳和压力测试某个判断。

四个工具全部通过官方 Grok Build CLI 和账号 OAuth 调用 Grok。OpenCLI 与 xreach 只作为 X 搜索的只读末级回退，不能代替普通 Grok 咨询。

## 环境要求

- 支持插件 marketplace 的 Codex。
- Node.js 18 或更高版本。
- 官方 [Grok Build CLI](https://docs.x.ai/build/overview)，默认位于 `~/.grok/bin/grok`，也可通过 `GROK_CONSULT_CLI` 指定。
- 已执行 `grok login` 并保持有效登录。
- X 回退可选依赖：同级 `yichen-unified-search` Skill 中的 `fxtwitter_search.py`，以及 OpenCLI、xreach。OpenCLI/xreach 可能使用本机 X 登录态，只有当前任务明确授权且 `allow_authenticated_fallback=true` 时才会使用。

本文发布时，xAI 官方安装方式为：

```bash
curl -fsSL https://x.ai/cli/install.sh | bash
grok login
```

运行远程安装脚本前，请先回到 xAI 官方文档确认当前命令。

## 从本仓库安装

```bash
codex plugin marketplace add mcncarl/yichen-skills --ref main
codex plugin add yichen-grok-consult@yichen-skills
```

安装完成后新建 Codex 任务，使插件和 MCP 工具进入当前工具列表。

## 可选配置

公开版不包含固定代理、凭证、API Key、用户名或个人绝对路径。

| 环境变量 | 用途 |
|---|---|
| `GROK_CONSULT_CLI` | 官方 Grok CLI 不在默认位置时，指定其绝对路径 |
| `GROK_CONSULT_SEARCH_TIMEOUT_MS` | 原生搜索超时，限制在 10–630 秒 |
| `GROK_CONSULT_SEARCH_MAX_TURNS` | 原生搜索最大轮数，限制在 1–60 |
| `GROK_CONSULT_PYTHON` | FxTwitter 适配器使用的 Python 绝对路径 |
| `GROK_CONSULT_FXTWITTER_ADAPTER` | 同级 Skill 不在默认位置时，指定 `fxtwitter_search.py` 的绝对路径 |
| `GROK_CONSULT_OPENCLI` | OpenCLI 绝对路径 |
| `GROK_CONSULT_XREACH` | xreach 绝对路径 |
| `GROK_CONSULT_LOCAL_READER_TIMEOUT_MS` | 本地读取器超时，限制在 10–180 秒 |

如果网络需要代理，只在自己的本机 MCP 环境中配置 `HTTP_PROXY`、`HTTPS_PROXY` 等变量，不要提交代理凭证。

## 安全与隐私边界

- Grok 在 `~/.grok/grok-consult/` 下的隔离非 Git 目录运行，不会进入当前项目。
- 子进程只接收白名单环境变量，`XAI_API_KEY` 不会被转发。
- 搜索时只开放 `x_search`、`web_search` 和 `web_fetch`；关闭 MCP、本地文件、Shell、记忆、子代理和计划模式。
- 真实 Grok 登录文件只通过 `GROK_AUTH_PATH` 引用，不复制进仓库，也不在工具输出中返回。
- MCP 会读取隔离会话记录，确认至少一次 `XSearch` 已完成，不相信 Grok 文字里的“我已经搜索”。
- 未登录、401/403、权限、输入、超时、网络、服务、零结果或搜索证据不可核验都不属于额度耗尽；只有明确的 Grok 账号额度或使用上限耗尽才能触发 FxTwitter。
- FxTwitter 只接收公开关键词，不接收 X Cookie。OpenCLI 与 xreach 可能使用本机 X 会话，因此服务器默认禁止两者，只有调用方在当前任务明确授权后传入 `allow_authenticated_fallback=true` 才放行。
- 查询、结果和会话记录会留在隔离 Grok 目录，也可能由 xAI 处理；插件不会自动清理。
- 对外返回结果不包含用户的绝对 transcript 路径。

## 校验限制

- 会话记录只能证明这次 Grok 会话至少完成过一次原生 `XSearch`，不能逐条证明最终答案中的每个 URL 都来自原始搜索结果。
- Snowflake 解码只能确定性还原数字 status ID 中编码的时间，不能单独证明 X 确实签发该 ID、帖子仍在线，或正文、作者、互动量都正确。
- 互动量只是搜索时快照，之后可能变化或根本不可见。
- 当任务要求完整结构化数据或稳定 SLA 时，原生 X 搜索不能替代官方 X API。

## 实现链路

```text
GPT 主导的 Codex 任务
  -> 本地 MCP 服务
  -> 隔离的官方 Grok Build CLI 会话（始终第一层）
  -> 原生 XSearch / 辅助网页搜索
  -> 仅明确账号额度耗尽时：
       匿名 FxTwitter
       -> 仅在当前任务明确授权后：
            OpenCLI -> xreach
  -> 核验 XSearch 完成记录或本地只读路线
  -> 提取 URL + 还原 Snowflake 时间
  -> 把结构化结果交回 GPT
```

## 致谢

隔离调用 Grok Build 的设计参考了公开项目 [`sudoHG/codex-grok-search`](https://github.com/sudoHG/codex-grok-search)。本插件未复制其源码，详情见仓库根目录的 `THIRD_PARTY_NOTICES.md`。

## 许可

本插件遵循仓库根目录的[个人学习与非商业使用许可](../../LICENSE)。
