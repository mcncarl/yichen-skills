# Codex × ChatGPT Review Loop

[English](#english) | [中文](#中文)

## English

`codex-chatgpt` is a safety-first orchestration Skill for a two-agent collaboration loop:

```text
ChatGPT Pro: research, architecture, PLAN, REVIEW
Codex: local edits, commands, tests, repairs
Read-only MCP + Secure Tunnel: bounded project evidence for ChatGPT
```

### Modes

- `research`: ChatGPT Pro performs public-web research; no code Tunnel is used.
- `code`: ChatGPT inspects one project and returns PLAN; Codex implements and tests; ChatGPT reviews the real resulting state.
- `hybrid`: current web research plus local implementation and review.
- `review`: ChatGPT reviews one project through seven read-only MCP tools; Codex does not edit.
- `local-only`: optional and disabled unless the user separately configures a compatible local MCP.

### Important Scope

This public package contains the Skill protocol only. It does **not** publish the author's MCP runtime, Tunnel client, Runtime Key, private ChatGPT App, browser session, screenshots, or local workspace configuration. To use the code, hybrid, or review modes, supply a compatible runtime that satisfies [the documented contract](references/setup.md).

The Skill requires the official signed-in ChatGPT website, a visible Chat/Chat mode, and a model route visibly labeled `Pro`. It never treats Work mode, an API, another account, manual code transfer, or Codex-only reasoning as an equivalent fallback.

### Install

List the available Skills:

```bash
npx skills add mcncarl/yichen-skills --list
```

Install this Skill:

```bash
npx skills add mcncarl/yichen-skills --skill codex-chatgpt
```

Then copy [config.example.md](config.example.md) to a private local configuration source and follow [references/setup.md](references/setup.md). Never commit the populated configuration.

### Security Highlights

- The ChatGPT-facing MCP exposes exactly seven read-only tools.
- One explicit validated project is exposed at a time.
- ChatGPT never writes files or runs tests; Codex never claims otherwise.
- Browser messages contain identifiers and short instructions, not code, diffs, logs, secrets, or absolute paths.
- Evidence is stored outside source repositories and must be sanitized.
- One task permits one initial implementation and one bounded remediation before a new user checkpoint.

This project is not affiliated with or endorsed by OpenAI. ChatGPT, Codex, and OpenAI are trademarks of their respective owner.

### Related Work

[XiaoDuoYa/codex-with-chatgpt](https://github.com/XiaoDuoYa/codex-with-chatgpt) explores a different Cloudflare/OAuth remote-MCP architecture. This Skill uses a separate Secure-Tunnel, read-only review protocol and vendors no source code from that repository.

## 中文

`codex-chatgpt` 是一个将 ChatGPT Pro 和 Codex 分工组合起来的安全优先 Skill：

```text
ChatGPT Pro：联网调研、架构、PLAN、REVIEW
Codex：本地修改、命令、测试、修复
只读 MCP + Secure Tunnel：让 ChatGPT 在边界内读取真实项目证据
```

它支持纯调研、写代码、调研+代码、只读审查以及可选的 `local-only` 模式。ChatGPT 负责方案和审查，Codex 是唯一的本地代码写入者和命令/测试执行者。

### 公开边界

这个目录只公开 Skill 编排协议，不包含作者的 MCP Runtime、Tunnel 客户端、Runtime Key、ChatGPT 私有 App、浏览器会话、截图或本地项目配置。想使用代码、混合或审查模式，需要自行提供满足 [Runtime 契约](references/setup.md) 的只读 MCP。

这个 Skill 只接受 ChatGPT 官网中可见的 Chat/聊天 + `Pro` 模式，不会把 Work/工作、API、其他账号、手动粘贴代码或 Codex 自己的推理冒充为 ChatGPT Pro 完成的结果。

### 安装

```bash
npx skills add mcncarl/yichen-skills --skill codex-chatgpt
```

安装后，把 [config.example.md](config.example.md) 复制到私有本地配置位置，并按 [references/setup.md](references/setup.md) 配置。不要提交已填写的配置。

### 安全边界

- ChatGPT 一侧只有 7 个只读工具。
- 一次只暴露一个经过验证的项目。
- ChatGPT 不写代码、不跑测试；Codex 负责真实修改和验证。
- 网页控制消息不包含代码、diff、日志、密钥或本机绝对路径。
- 截图与 manifest 必须存在代码仓库外并完成脱敏。

本项目与 OpenAI 无官方隶属或背书关系。

### 相关项目

[XiaoDuoYa/codex-with-chatgpt](https://github.com/XiaoDuoYa/codex-with-chatgpt) 探索的是不同的 Cloudflare/OAuth 远程 MCP 架构。本 Skill 使用独立的 Secure Tunnel + 只读审查协议，没有复制或打包该仓库源码。
