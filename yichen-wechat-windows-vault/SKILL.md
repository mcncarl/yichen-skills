---
name: yichen-wechat-windows-vault
description: |
  微信 Windows 4.x 本地数据库全量/增量解析与数字资产库。用于本机 Windows 微信聊天记录、联系人、群聊、朋友圈、收藏夹、附件索引的只读密钥捕获、完整快照、WAL 正确解密、查询、搜索、导出、关系复盘、客户跟进和群聊素材沉淀。触发词：Windows 微信解析、微信 Windows 全量、微信 Windows 增量、导出 Windows 微信聊天、朋友圈解析、收藏夹解析、yichen-wechat-windows-vault。
---

# 微信 Windows 本地解析 Vault

这是 `yichen-wechat-local-vault` 的独立 Windows 实现。它把本机微信数据库复制到用户私有目录，验证 SQLCipher HMAC，合并最后一个有效 WAL 提交，再对明文快照做只读查询。不要把它用于不属于当前 Windows 用户的账号或设备。

## 不可突破的边界

- 默认不读取微信进程内存。只有用户在当前任务中明确同意“读取微信进程内存并把数据库密钥保存到本机私有目录”后，才能使用 `capture --consent-read-process-memory`。
- 不启动、关闭、暂停、恢复、注入、Hook、调试或操控微信进程；不调用微信 UI，不发送消息。需要数据库活动或退出微信时，只能让用户手动操作。
- 不依赖 `wx-cli`、Frida、DLL 注入、驱动或微信专用第三方二进制。
- 不在回复、日志或导出中显示原始 key、完整 salt、账号目录名、wxid 或无关聊天内容。
- 密钥只保存为当前 Windows 用户可解开的 DPAPI 密文；明文数据库只进入 `%LOCALAPPDATA%\YichenWeChatVault\vault`。
- 不自动删除旧快照。用户明确要求清理时，先列出准确 generation、大小和路径，获得确认后再删除指定 generation；不得递归删除 vault 根目录。
- 查询与导出只读已完成的明文快照。禁止写回微信数据库。
- 查询连接必须保持 SQLite `mode=ro` 与 `PRAGMA query_only`；导出文件已存在时默认拒绝替换，只有用户明确要求覆盖后才能传 `--overwrite`。

## 环境要求

- Windows 10/11 x64。
- 官方 Windows 微信 4.x，和数据库属于同一个 Windows 用户。
- Python 3.10+。
- 安装固定依赖：

```powershell
py -3 -m pip install -r "{{SKILL_DIR}}\requirements.txt"
```

已在 Windows 微信 `4.1.13.7` 验证内存结构发现和活动消息库的只读 key 捕获。微信升级后如果结构变化，捕获会失败关闭，不要猜地址或降级校验；先运行测试并重新审计公开结构。

## 首次工作流

### 1. 只读诊断

```powershell
py -3 "{{SKILL_DIR}}\scripts\windows_vault.py" diagnose
```

诊断只返回账号根目录指纹、数据库数量、WAL 数量和微信进程数量。

### 2. 明确获得内存读取与本地密钥存储授权

先向用户说明：工具将以 `PROCESS_QUERY_INFORMATION | PROCESS_VM_READ` 读取当前用户的 `Weixin.exe`，捕获的数据库 AES key 会经 DPAPI 加密后保存到 `%LOCALAPPDATA%\YichenWeChatVault\keys\account.json`，不会显示、上传或写入 Git。

只有用户明确同意后运行：

```powershell
py -3 "{{SKILL_DIR}}\scripts\windows_vault.py" capture --targets all --duration 240 --consent-read-process-memory
```

捕获期间让用户手动打开需要的数据区域，例如聊天、通讯录、朋友圈和收藏夹。工具只等待数据库正常读写时极短的解保护窗口。若仍有缺失，使用返回的相对数据库路径做定向捕获：

```powershell
py -3 "{{SKILL_DIR}}\scripts\windows_vault.py" capture --targets "message/message_0.db" --duration 120 --consent-read-process-memory
```

不要替用户点击微信。不要要求用户发送包含隐私的内容；如确需触发消息库写入，让用户自行决定是否在测试会话发送无敏感内容。

### 3. 用户手动完全退出微信

生成一致快照前，要求用户从微信菜单手动退出，并确认托盘中不再运行。Skill 不得代为结束进程。

### 4. 首次全量刷新

```powershell
py -3 "{{SKILL_DIR}}\scripts\windows_vault.py" refresh --mode full
```

刷新会：

1. 再次确认没有 `Weixin.exe`。
2. 把每个 DB、WAL、SHM 作为稳定文件集复制到新的不可变 generation。
3. 验证每个 SQLCipher 页 HMAC。
4. 验证 WAL 头、连续帧校验和与盐，只合并最后一个有效 commit 之前的帧。
5. 运行 SQLite `quick_check` 和 `integrity_check`。
6. 只有所有数据库都成功时才原子更新 `current.json`。

缺 key、旧 key、损坏页或 WAL 错误必须作为失败返回，不得用旧明文库伪装成功。

日常使用 `refresh --mode incremental`（默认）。增量模式仍会创建新的不可变 generation，并重新稳定复制和哈希每组 DB/WAL/SHM；只有加密文件组和 DPAPI key 指纹均未变化时，才复用上一代通过完整性检查的明文库。需要强制逐库重新解密时使用 `--mode full`。

## 日常状态与查询

查看 key 和快照覆盖率：

```powershell
py -3 "{{SKILL_DIR}}\scripts\windows_vault.py" status
py -3 "{{SKILL_DIR}}\scripts\vault_cli.py" status --format text
```

查询入口和 Mac 版本保持一致：

```powershell
py -3 "{{SKILL_DIR}}\scripts\vault_cli.py" sessions --limit 20 --format text
py -3 "{{SKILL_DIR}}\scripts\vault_cli.py" unread --format text
py -3 "{{SKILL_DIR}}\scripts\vault_cli.py" new-messages --format text
py -3 "{{SKILL_DIR}}\scripts\vault_cli.py" contacts --query "关键词" --format text
py -3 "{{SKILL_DIR}}\scripts\vault_cli.py" members "群名" --format text
py -3 "{{SKILL_DIR}}\scripts\vault_cli.py" history "联系人或群名" --start-time "2026-05-01" --format text
py -3 "{{SKILL_DIR}}\scripts\vault_cli.py" search "关键词" --chat "群名" --type link --format text
py -3 "{{SKILL_DIR}}\scripts\vault_cli.py" stats "群名" --start-time "2026-05-01" --format text
py -3 "{{SKILL_DIR}}\scripts\vault_cli.py" export "群名" --format markdown --output ".\chat.md"
py -3 "{{SKILL_DIR}}\scripts\vault_cli.py" favorites --type article --query "关键词" --format text
py -3 "{{SKILL_DIR}}\scripts\vault_cli.py" moments --name "联系人" --start "2026-05-01" --format text
```

支持的消息类型过滤：`text`、`image`、`voice`、`video`、`sticker`、`location`、`link`、`file`、`call`、`system`。

## 群聊摘要素材包

用户明确要群聊精华、日报、复盘或“从上次继续”时：

```powershell
py -3 "{{SKILL_DIR}}\scripts\vault_cli.py" digest-source "群名" --start "2026-05-01" --end "2026-05-14" --format text
py -3 "{{SKILL_DIR}}\scripts\vault_cli.py" digest-source "群名" --since-last --data-root ".\wechat-digests" --format text
```

大批量消息先生成素材文件，再分析。图片只有在对应说明文件存在时才描述；否则明确写“图片内容不可见”，不得编造。

## 输出原则

- 回复优先给状态、数量、失败项和报告路径；不要粘贴整段私聊。
- 明确区分 DPAPI 密钥库、加密快照、明文快照和用户导出报告。
- 导出报告可能包含明文隐私，写入前确认用户指定路径；默认导出目录是 `%USERPROFILE%\Documents\YichenWeChatVault\exports`。
- 朋友圈和收藏夹缺 key 时只补抓相关库，不扩大到不必要范围。
- 所有异常都保持源数据库不变；任何临时或不完整 generation 都不能成为 current。

## 维护与验证

```powershell
py -3 -m unittest discover -s "{{SKILL_DIR}}\tests" -v
py -3 -m py_compile "{{SKILL_DIR}}\scripts\*.py"
```

依赖、许可证、来源和威胁边界见 `README.md`、`PROVENANCE.md`、`SECURITY.md`、`THIRD_PARTY_NOTICES.md` 和 `sbom.spdx.json`。
