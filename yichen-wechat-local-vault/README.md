# yichen-wechat-local-vault

微信本地数字资产库，支持 **macOS / Windows 本地全量解析**。Windows 已实现所选账号全部本地数据库的采集和认证解密、聊天主表逐行解析，以及收藏、朋友圈正文解析；Mac 另支持增量刷新、漏看/待回复等工作流。Windows 已实测环境和边界见 [本机全量解析说明](references/windows-live.md)。

这里的“全量”指已经同步到电脑、位于所选账号本地数据目录中的数据库和记录。

| 能力 | macOS | Windows |
| --- | --- | --- |
| 本地全库采集、解密 | 已支持 | 已支持，使用 `windows capture --scope all` |
| 聊天记录解析、查询、搜索、导出 | 已支持 | 已实测逐行解析和回读 |
| 收藏、朋友圈正文解析 | 已支持 | 已实测，复用包内纯函数工作流 |
| 漏看、待回复等高级工作流 | 已支持 | 尚未完整对齐 |

Windows 媒体数据库可以采集解密；图片、语音、视频文件本体还原仍需另行适配。三个搜索索引库的 SQLite 校验缺口会明确返回，不影响本次已完成的聊天主表解析。

## 隐私路径

- 密钥和配置应只保存在本机私有配置区。
- 明文库、解密清单和增量状态应放在本机私有 vault。
- 可读导出报告可以放到用户自选的导出目录。
- 查询输出（JSON 和 `--format text`）默认隐藏 username 和微信号；需要精确匹配时，在子命令前加 `--include-identifiers`。

明文库包含完整本地微信隐私，不要同步、分享或复制到项目目录。

## Mac 常用命令

```bash
python3 scripts/extract_keys.py --list-dbs
python3 scripts/extract_keys.py --match-only --targets all --reuse-log
python3 scripts/extract_keys.py --targets all --duration 240
python3 scripts/decrypt_all_dbs.py --mode full
python3 scripts/decrypt_all_dbs.py --mode incremental
python3 scripts/vault_cli.py status --format text
python3 scripts/vault_cli.py sessions --format text
python3 scripts/vault_cli.py pending --since 48h --format text
python3 scripts/vault_cli.py history "联系人或群名" --format text
python3 scripts/vault_cli.py search "关键词" --format text
python3 scripts/vault_cli.py stats "群名" --format text
python3 scripts/vault_cli.py favorites --format text
python3 scripts/vault_cli.py moments --name "联系人" --format text
python3 scripts/vault_cli.py digest-source "群名" --start "2026-05-01" --end "2026-05-14" --format text
python3 scripts/export_chat.py --contact "联系人备注" --mode full
python3 scripts/export_chat.py --contact "联系人备注" --mode incremental
python3 scripts/export_chat.py --chat-id "contact_username" --since "2025-01-01"
```

`vault_cli.py` 默认 JSON 输出，适合被 Agent 调用；需要人工查看时加 `--format text`。

## 统一查询入口

`scripts/vault_cli.py` 吸收了 WeChat CLI 的常用产品化能力，但仍然只读本 skill 的已解密 vault：

- `status`：检查明文库是否齐全。
- `sessions` / `unread` / `new-messages`：最近会话、未读和增量新消息。
- `pending`：漏看/待回复候选，含已读未回的私聊、群里 @我/引用我/提到我/@所有人、待收或超时退回的转账、私聊红包和未接来电；`--previous` + `--since last` 接续上次检查，`--output` 写入权限 600 的私密文件。
- `transfers`：转账记录，每笔给出转入/转出、对方、金额、备注和状态，并合计转入、转出和待收；`history`/`export` 里的转账也显示金额和状态。只含聊天里的转账消息，不是微信支付账单。
- `contacts` / `members`：联系人、群聊和群成员。
- `history` / `search`：按聊天对象、关键词、时间、消息类型查询；`search` 同样覆盖压缩存储的长文本、文件名和链接标题。
- `stats`：消息总数、类型分布、发言排行、24 小时分布。
- `export`：Markdown 或 txt 导出。
- `favorites`：收藏夹，支持 text/image/article/card/video。
- `moments`：朋友圈，支持联系人、时间、关键词。
- `digest-source`：生成群聊摘要素材包，供后续写日报、群聊精华或画像。

## Windows 本地全量解析与离线查询

Windows 本机采集使用 `python scripts/vault_cli.py windows discover/capture`，详见 [Windows 本机采集](references/windows-live.md)。它只读明确授权的账号和签名通过的微信进程，在私密应用数据区生成带逐页认证、WAL 提交事务处理及完整性校验的聊天快照；不会操作微信界面。当前已在 Windows 11 ARM64、AMD64 微信 4.1.15.56 环境完成真实采集、解密、新消息刷新及导出回读；版本与权限范围见该参考文档。

明确要求全量本地数据库时，使用 `windows capture --scope all --source-id SOURCE_ID`。它生成包含收藏、朋友圈和媒体数据库的完整核心快照；已知搜索索引的 SQLite 校验缺口会通过 `complete_with_index_gaps` 和 `integrity_gaps` 明确返回，逐页认证仍须全部通过。收藏、朋友圈正文按 [共用纯函数工作流](references/windows-live.md#朋友圈和收藏正文解析)读取，暂未单独封装查询子命令。

Windows 来源使用同一个 CLI 的 `snapshot` 子命令，不读取 Mac 配置、不刷新或解密任何数据库：

```bash
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot validate
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot chats --query "群名"
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot history CHAT_ID
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot search CHAT_ID "关键词"
```

输入必须是静止且已 checkpoint 的明文快照，附有效 manifest。支持的 Schema、导出规则、依赖和原始贡献来源见 [Windows 快照模式](references/windows-snapshot.md)。合成测试不等于真实 Windows 微信版本验收。

## 群聊精华素材包

`digest-source` 会在 `{data_root}/{group_id}-{group_name}/` 下创建：

- `sources/*.json`：机器可读消息、统计和路径信息。
- `sources/*.md`：人工可读素材稿。
- `profiles/`：普通版群友画像。
- `profiles-roast/`：毒舌版画像。
- `imgs/`：图片说明扩展点，文件名形如 `{message_id}.txt`。

它只生成素材，不直接更新 `history.json`。最终摘要确认后再更新历史锚点，避免“从上次继续”读到半成品。

## 脚本

- `vault_cli.py`：统一查询、统计、导出、漏看/待回复检查、收藏夹、朋友圈和摘要素材包入口。
- `extract_keys.py`：本机 key 捕获、复用和匹配。
- `decrypt_all_dbs.py`：全量/增量解密，写入私密 vault；日志里的账号目录显示为 `<账号目录>`。
- `export_chat.py`：按联系人、群聊或会话 ID 导出聊天。
- `list_contacts.py`：列出联系人和群聊。
- `wechat_digest.py`：按天摘要脚本，仅在明确需要摘要时使用。
- `search_sns.py`：朋友圈搜索辅助。
