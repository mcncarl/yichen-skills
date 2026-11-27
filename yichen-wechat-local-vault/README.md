# yichen-wechat-local-vault

微信本地数字资产库，支持 **macOS / Windows 本地全量解析与查询工作流对齐**。Windows 已实现所选账号全部本地数据库的采集/增量复用和认证解密，并通过统一的 `snapshot` 子命令对齐 Mac 的全套分析颗粒度（会话、未读、增量新消息、联系人/群成员、历史、全局搜索、统计、导出、收藏、朋友圈、漏看/待回复、转账汇总、群聊摘要素材包及本地图片定位/解码）。Windows 已实测环境和边界见 [本机全量解析说明](references/windows-live.md)。

这里的“全量”指已经同步到电脑、位于所选账号本地数据目录中的数据库和记录。

| 能力 | macOS | Windows |
| --- | --- | --- |
| 本地全库采集、解密 | 已支持 | 已支持（`windows capture --scope all`） |
| 增量刷新 | 已支持（`decrypt_all_dbs.py --mode incremental`） | 已支持（`windows capture --mode incremental`，核验加密/明文 SHA-256 复用未变化库） |
| 会话、未读、增量新消息、联系人、群成员 | 已支持 | 已对齐（`snapshot status/sessions/unread/new-messages/contacts(--detail)/members`） |
| 聊天记录、全局搜索、类型过滤、统计、导出 | 已支持 | 已对齐（`snapshot history/search/stats/export`，含 `--media --file-dir` 文件定位） |
| 收藏、朋友圈正文解析 | 已支持 | 已封装独立子命令（`snapshot favorites` / `snapshot moments`） |
| 漏看/待回复、转账汇总、群聊摘要素材包 | 已支持 | 已对齐（`snapshot pending` / `transfers` / `digest-source`） |
| 聊天图片定位、解码与本地 OCR | 已支持（含 `kvcomm` 密钥自动候选） | 已对齐（`windows images` 与 `snapshot images` 支持 `--message-id`、`kvcomm` 自动推导 V2 `.dat` 密钥 + Windows CNG 解码 + `Weixin.exe` 只读内存回退 + 原生 WinRT / Tesseract 中文 OCR） |

三个 `MMFtsTokenizer` 搜索索引库会对底层全部物理表与 FTS5 影子 B-tree 逐表执行 `integrity_check`，仅将私有虚拟表分词器缺口明确返回，不影响聊天主表解析；Windows 全套能力已通过 Windows 11 真机端到端验收与 GitHub Actions（`windows-latest` + `macos-latest`）持续集成回归，实测范围以 [本机全量解析说明](references/windows-live.md) 为准。

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
python3 scripts/vault_cli.py images "联系人或群名" --local-id 123 --ocr --format text
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
- `transfers`：转账记录，每笔给出方向、对方、金额、备注和截至快照的状态，按币种合计转入、转出和待收；身份不明、缺 ID 或同 ID 冲突的记录明确标注，不纳入确定收支。跨会话相同 ID 在所选聊天范围内合并为一条异常记录，避免镜像重复计数。`history`/`export` 里的转账也显示金额和状态。只含聊天里的转账消息，不是微信支付账单。
- `contacts` / `members`：联系人、群聊和群成员。
- `history` / `search`：按聊天对象、关键词、时间、消息类型查询；`search` 同样覆盖压缩存储的长文本、文件名和链接标题。
- `images`：私聊/群聊图片，按消息 `packed_info_data` 中的哈希定位本地附件；`--decode` 解码到私密缓存（含明文图片），`--ocr` 本机识字。
- `stats`：消息总数、类型分布、发言排行、24 小时分布。
- `export`：Markdown 或 txt 导出。
- `favorites`：收藏夹，支持 text/image/article/card/video。
- `moments`：朋友圈，支持联系人、时间、关键词。
- `digest-source`：生成群聊摘要素材包，供后续写日报、群聊精华或画像。

## Windows 本地全量解析与离线查询

Windows 本机采集使用 `python scripts/vault_cli.py windows discover/capture`，详见 [Windows 本机采集](references/windows-live.md)。它只读明确授权的账号和签名通过的微信进程，在私密应用数据区生成带逐页认证、WAL 提交事务处理及完整性校验的聊天快照；不会操作微信界面。当前已在 Windows 11 ARM64、AMD64 微信 4.1.15.56 环境完成真实采集、解密、新消息刷新及导出回读；版本与权限范围见该参考文档。

明确要求全量本地数据库时，使用 `windows capture --scope all --source-id SOURCE_ID`；日常刷新可加 `--mode incremental` 复用上一份已校验快照中 SHA-256 未变化的数据库，只重新解密变化库。它生成包含收藏、朋友圈和媒体数据库的完整核心快照；已知搜索索引的 SQLite 校验缺口会通过 `complete_with_index_gaps` 和 `integrity_gaps` 明确返回，逐页认证仍须全部通过。

Windows 来源使用同一个 CLI 的 `snapshot` 子命令（已对齐 Mac 全部查询与分析工作流），不读取 Mac 配置、不刷新或解密任何数据库：

```bash
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot validate
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot status --format text
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot sessions --limit 20 --format text
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot unread --format text
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot new-messages --previous-snapshot /path/to/old-snapshot --format text
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot chats --query "群名"
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot contacts --detail CHAT_ID --format text
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot members CHAT_ID --format text
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot history CHAT_ID --type file --media --file-dir /path/to/msg/file --format text
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot search CHAT_ID "关键词"
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot search --all "关键词" --format text
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot stats CHAT_ID --format text
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot export CHAT_ID --format markdown --output /path/to/chat.md --confirm-external-output
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot favorites --type article --query "关键词" --format text
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot moments --name "联系人" --format text
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot pending --since 48h --format text
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot transfers --start 2026-01-01 --format text
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot digest-source CHAT_ID --start 2026-05-01 --end 2026-05-14 --format text
python3 scripts/vault_cli.py snapshot --snapshot /path/to/authorized-snapshot images CHAT_ID --attach-dir /path/to/msg/attach --decode --ocr --format text
# Windows 本机一键自动绑定最新快照与 msg/attach、自动推导 V2 密钥并 OCR：
python scripts/vault_cli.py windows images CHAT_ID --decode --ocr --format text
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
