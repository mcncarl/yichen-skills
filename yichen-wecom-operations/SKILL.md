---
name: yichen-wecom-operations
description: 企业微信官方 wecom-cli 操作入口。用于把本地 Markdown 创建为普通或智能文档、在用户另行配置图片上传 helper 后生成含本地图片的智能文档、读取或覆写企微文档、创建与管理待办，并在企业权限开放时预约、查询、更新或取消会议和日程。用户提到“企微文档”“智能文档”“上传 Markdown”“预定会议”“企微会议”“企微日程”“企微待办”时使用；不用于消息发送或企业微信客户端操作。
---

# 企业微信操作

通过本机官方 `wecom-cli` 操作企微云端能力。把它与只读本地数据库 Skill `$wecom-local-vault` 分开使用。

## 强制边界

1. 绝不点击、启动、退出或控制企业微信客户端，绝不调用 `wecom-cli msg` 或发送消息。
2. 读取、帮助和 schema 查询可直接执行；创建、覆写、更新、邀请、取消和删除必须来自用户当轮明确指令。
3. 取消会议／日程、删除待办、覆写已有文档前，先只读确认精确目标和当前状态，再取得用户对该目标的明确确认。
4. 不读取或输出 `~/.config/wecom/` 中的加密凭证，不在回复、日志、报告或记忆中保存 Bot ID、Secret、内部 userid、docid、meetingid、todo_id 或带授权参数的 URL。
5. 若 `~/.config/wecom/{.encryption_key,bot.enc,mcp_config.enc}` 已存在，不得重新运行 `wecom-cli init` 覆盖配置。
6. 每次先运行目标 category 的 `--help`。若返回“当前企业暂不支持授权”，立即停止该 category，不得改用客户端自动化或非官方协议绕过。
7. 远程业务结果以 `errcode == 0` 为成功；失败最多低频重试一次。返回 `help_instruction` 时，按要求逐字展示 `help_message`。
8. 不自动删除本地上传副本、回执或失败后已创建的企微资源；需要清理时先征得用户明确同意。

## 开始前检查

```bash
SKILL_ROOT="${WECOM_OPERATIONS_SKILL_ROOT:-$HOME/.agents/skills/yichen-wecom-operations}"
python3 "$SKILL_ROOT/scripts/doctor.py"
python3 "$SKILL_ROOT/scripts/doctor.py" --category doc
```

`doctor.py` 只检查版本、加密配置文件权限和 category 可用性，不读取凭证内容。

## 路由

- 本地 Markdown、普通文档、智能文档、图片证据：读取 [references/documents.md](references/documents.md)。
- 预约／查询／取消会议，或企微日程：读取 [references/meetings.md](references/meetings.md)。
- 创建、查询、更新或删除待办：读取 [references/todos.md](references/todos.md)。

不要为无关任务读取所有参考文件。

## 文档快速入口

默认只预检，不产生企微写操作：

```bash
SKILL_ROOT="${WECOM_OPERATIONS_SKILL_ROOT:-$HOME/.agents/skills/yichen-wecom-operations}"
python3 "$SKILL_ROOT/scripts/create_smartpage.py" \
  --source "/absolute/path/report.md" \
  --title "报告标题"
```

用户当轮明确要求创建后再传 `--execute`：

```bash
SKILL_ROOT="${WECOM_OPERATIONS_SKILL_ROOT:-$HOME/.agents/skills/yichen-wecom-operations}"
python3 "$SKILL_ROOT/scripts/create_smartpage.py" \
  --source "/absolute/path/report.md" \
  --title "报告标题" \
  --execute
```

无本地图片时只创建最终智能文档；存在本地图片时额外创建一个明确命名的“图片资源”普通文档，上传图片并生成企微 CDN 链接，再创建最终智能文档。两者都必须在结果中向用户披露。

## 运行时能力检查

- 依赖企业微信官方 [`@wecom/cli`](https://github.com/WecomTeam/wecom-cli)，安装后运行 `wecom-cli init` 完成用户自己的机器人配置。
- 文档、待办、会议、日程和通讯录的授权范围取决于企业与机器人配置，必须用 `doctor.py` 和目标 category 的 `--help` 动态检查。
- 官方 CLI 可以处理文本和远程图片；本地图片上传依赖另行提供、带 `doc +doc_upload_image` 能力的 helper，并通过 `WECOM_UPLOAD_HELPER` 指向其可执行文件。本仓库不分发该本地扩展。
- 智能文档回读权限可能返回 `851008`；创建成功不能冒充回读验证成功。

## 交付

只向用户展示可读名称、时间、状态和最终访问链接。内部 ID 仅保存在权限为 `0600` 的本机回执中，不在对话里展开。
