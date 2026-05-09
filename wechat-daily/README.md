# wechat-local-vault

微信 Mac 4.x 本地数据库全量/增量解析与数字资产库。这个 skill 原来叫 `wechat-daily`，现在定位已调整为本地微信 vault：按指令选择全量解密、增量刷新、指定联系人/群聊导出、朋友圈/收藏夹解析和关系复盘。

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
python3 scripts/export_chat.py --contact "联系人备注" --mode full
python3 scripts/export_chat.py --contact "联系人备注" --mode incremental
python3 scripts/export_chat.py --chat-id "contact_username" --since "2025-01-01"
```

## 脚本

- `extract_keys.py`：本机 key 捕获、复用和匹配。
- `decrypt_all_dbs.py`：全量/增量解密，写入私密 vault。
- `export_chat.py`：按联系人、群聊或会话 ID 导出聊天。
- `list_contacts.py`：列出联系人和群聊。
- `wechat_daily.py`：旧日报脚本，仅在明确需要日报时使用。
- `search_sns.py`：朋友圈搜索辅助。
