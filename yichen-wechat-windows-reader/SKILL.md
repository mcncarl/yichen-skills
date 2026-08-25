---
name: yichen-wechat-windows-reader
description: |
  Windows 微信 4.x 用户提供明文数据库快照的本机只读查询与导出工具。用于验证明文快照、列出会话、按匿名会话 ID 查询/搜索聊天和导出 Markdown。明确不读取 Weixin.exe 进程、不提取或保存密钥、不解密数据库、不控制微信界面。触发词：Windows 微信明文快照、微信只读分析、查询微信快照、导出微信聊天、yichen-wechat-windows-reader。
---

# Windows 微信明文快照只读分析器

只分析用户明确提供的、已经是标准 SQLite 明文格式的快照目录。不要寻找微信数据目录，不要访问 `Weixin.exe`，不要读取进程内存，不要提取、接收、保存或验证数据库密钥，也不要尝试 SQLCipher/WAL 解密。

## 安全边界

- 每次命令都要求用户显式传入 `--snapshot`；不要自动发现或复制源数据。
- 先运行 `validate`。缺少任一必需数据库、没有任一消息库或 SQLite 完整性检查失败时，停止分析。
- 输入库只以 `mode=ro&immutable=1` 和 `PRAGMA query_only=ON` 打开。
- `chats` 只用于找候选。`history`、`search`、`export` 只能接受 `chats` 返回的精确 `chat_id`，不接受昵称模糊匹配。
- 输出不包含 wxid、群 username 或 sender username；匿名 `chat_id` 只用于本次快照定位。
- 默认导出到 `%LOCALAPPDATA%\YichenWeChatVault\exports`。输出到项目、Documents、桌面、网盘、网络盘或其他目录时，必须让用户针对当前命令确认，再传 `--confirm-external-output`。
- `snapshot-manifest.json` 可由用户提供 `account_username` 以判断收发方向；没有时输出 `unknown`，禁止猜测。

## 使用顺序

```powershell
python {{SKILL_DIR}}\scripts\snapshot_reader.py --snapshot C:\private\snapshot validate
python {{SKILL_DIR}}\scripts\snapshot_reader.py --snapshot C:\private\snapshot chats --query "群名"
python {{SKILL_DIR}}\scripts\snapshot_reader.py --snapshot C:\private\snapshot history CHAT_ID --start 2026-08-01 --end 2026-08-25
python {{SKILL_DIR}}\scripts\snapshot_reader.py --snapshot C:\private\snapshot search CHAT_ID "关键词"
python {{SKILL_DIR}}\scripts\snapshot_reader.py --snapshot C:\private\snapshot export CHAT_ID
```

如果名称相同，展示所有候选及各自的 `chat_id`，由用户选择。不要自行挑第一项。

## 快照契约

目录必须包含：

- `contact/contact.db`
- `session/session.db`
- `favorite/favorite.db`
- `sns/sns.db`
- `message/message_resource.db`
- 至少一个 `message/message_*.db` 或 `message/biz_message_*.db`

可选 `snapshot-manifest.json`：

```json
{"account_username":"用户明确提供的本账户内部标识"}
```

该字段只在内存中比较，绝不出现在查询或导出结果中。

## 输出

默认把查询 JSON 打到终端，把导出 Markdown 写入私有目录。回复用户时优先给统计、结论和文件路径；除非用户明确要求，不粘贴大段聊天原文。
