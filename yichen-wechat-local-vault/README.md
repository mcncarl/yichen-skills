# wechat-local-vault

微信 Mac 4.x 本地数据库全量/增量解析与数字资产库。按指令选择全量解密、增量刷新、统一查询、指定联系人/群聊导出、朋友圈/收藏夹解析、群聊精华素材包和关系复盘。

## 隐私路径

- 密钥和配置应只保存在本机私有配置区。
- 明文库、解密清单和增量状态应放在本机私有 vault。
- 可读导出报告可以放到用户自选的导出目录。

明文库包含完整本地微信隐私，不要同步、分享或复制到项目目录。

## 常用命令

```bash
python3 scripts/extract_keys.py --list-dbs
python3 scripts/extract_keys.py --match-only --targets all --reuse-log
python3 scripts/extract_keys.py --targets all --duration 240
python3 scripts/decrypt_all_dbs.py --mode full
python3 scripts/decrypt_all_dbs.py --mode incremental
python3 scripts/vault_cli.py status --format text
python3 scripts/vault_cli.py sessions --format text
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
- `contacts` / `members`：联系人、群聊和群成员。
- `history` / `search`：按聊天对象、关键词、时间、消息类型查询。
- `stats`：消息总数、类型分布、发言排行、24 小时分布。
- `export`：Markdown 或 txt 导出。
- `favorites`：收藏夹，支持 text/image/article/card/video。
- `moments`：朋友圈，支持联系人、时间、关键词。
- `digest-source`：生成群聊摘要素材包，供后续写日报、群聊精华或画像。

## 群聊精华素材包

`digest-source` 会在 `{data_root}/{group_id}-{group_name}/` 下创建：

- `sources/*.json`：机器可读消息、统计和路径信息。
- `sources/*.md`：人工可读素材稿。
- `profiles/`：普通版群友画像。
- `profiles-roast/`：毒舌版画像。
- `imgs/`：图片说明扩展点，文件名形如 `{message_id}.txt`。

它只生成素材，不直接更新 `history.json`。最终摘要确认后再更新历史锚点，避免“从上次继续”读到半成品。

## 脚本

- `vault_cli.py`：统一查询、统计、导出、收藏夹、朋友圈和摘要素材包入口。
- `extract_keys.py`：本机 key 捕获、复用和匹配。
- `decrypt_all_dbs.py`：全量/增量解密，写入私密 vault。
- `export_chat.py`：按联系人、群聊或会话 ID 导出聊天。
- `list_contacts.py`：列出联系人和群聊。
- `wechat_digest.py`：按天摘要脚本，仅在明确需要摘要时使用。
- `search_sns.py`：朋友圈搜索辅助。
