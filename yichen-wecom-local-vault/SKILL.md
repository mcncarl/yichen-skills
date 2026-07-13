---
name: yichen-wecom-local-vault
description: Read, decrypt, query, search, and export local WeCom/企业微信 5.x desktop databases on macOS into a private read-only vault. Use when the user asks to parse 企业微信本地数据、企微聊天记录、WeCom/WXWork contacts, sessions, groups, customers, message history, local database backup, structured export, or a Mac enterprise-WeChat data analysis workflow.
---

# yichen-wecom-local-vault：企业微信本地数据 Vault

只读取 Mac 企业微信5.x本地数据库，生成新的私密明文快照，再从快照查询联系人、会话和消息。把它与个人微信 `yichen-wechat-local-vault` 分开使用；两者的容器、加密算法和表结构不兼容。

## 强制边界

- 绝不点击、退出、重启、重签原始 `/Applications/企业微信.app`，也绝不发送企业微信消息。
- 允许在用户明确要求“修改边界 / 用重签副本抓企微 key / 继续完整解密”时，复制一份企业微信到私密 Vault，对副本做 ad-hoc 重签，并通过 Frida 启动这个副本捕获 key。
- 重签副本只能用于本机 owner 授权的数据解析；默认不复用旧副本、不覆盖已有副本、不写进项目或云盘。
- 默认不附加企业微信进程。只有用户明确要求“抓企微 key / 捕获密钥 / 继续解密”时，才可运行带 `--confirm-attach` 的捕获命令；系统拒绝 attach 时优先改用签名副本路线。
- 只读源数据库和 WAL；不写回企业微信容器。
- 不删除或覆盖任何文件。每次解密建立新的时间戳快照；每次导出建立新文件。
- 不在回复或日志中显示 raw key、完整账号目录、联系人内部 ID 或整段私聊原文。
- 明文快照、密钥和导出文件都属于敏感数据；不要放进项目、桌面、云盘或 Git。

## 入口

```bash
SKILL_DIR="${CODEX_HOME:-$HOME/.codex}/skills/yichen-wecom-local-vault"
python3 "$SKILL_DIR/scripts/vault_cli.py" status
```

依赖：日常发现与查询只需要 Python 3；解密需要 `pycryptodome`；Mac 被动捕获 key 另外需要 `frida`。不要自动安装依赖，先报告缺项。

## 自动选择工作流

1. 第一次使用或用户问“能不能解析”：运行 `status`，只检查数据库，不附加进程。
2. 已有私密 key 文件：运行 `decrypt` 创建新快照；默认合并已提交的 WAL 帧。
3. 缺少 key：先说明需要明确授权捕获；可选只读 attach，若 macOS 拒绝 `task_for_pid`，再使用重签副本捕获。
4. 已有快照：直接用 `sessions`、`contacts`、`history`、`search`、`export`，不要重新解密。
5. 用户指定会话或时间范围：只查询该范围；消息较多时先落 Markdown/JSON 文件。

## 数据库发现与检查

```bash
python3 "$SKILL_DIR/scripts/vault_cli.py" discover
python3 "$SKILL_DIR/scripts/vault_cli.py" status
python3 "$SKILL_DIR/scripts/vault_cli.py" status --show-paths
python3 "$SKILL_DIR/scripts/capture_key_macos.py" list
python3 "$SKILL_DIR/scripts/capture_key_macos.py" doctor
python3 "$SKILL_DIR/scripts/scan_dbkey_manager_macos.py" scan
```

只有用户明确需要看真实路径时才使用 `--show-paths`。多账号时用 `--data-dir` 指定包含 `message.db`、`session.db`、`user.db` 的数据集。

## 捕获 Mac 企业微信 key

此步骤只被动附加已经运行的进程，不启动或操作客户端。必须获得用户当轮明确授权：

```bash
python3 "$SKILL_DIR/scripts/capture_key_macos.py" capture \
  --confirm-attach \
  --duration 60
```

捕获器监听 CommonCrypto AES/MD5 调用，将候选16字节 key 与本地加密库第一页逐一验证；只有验证成功才以 `0600` 写入私密 Vault，终端不显示 key。若超时，报告“未捕获”，不要让用户在客户端里进行点击操作，也不要自行重签应用。

`doctor` 只读检查 Python、Frida、Developer Tools、SIP 和数据库格式。若 macOS 拒绝 `task_for_pid`，停止捕获并报告权限边界；不要自动关闭 SIP、放宽系统 `taskport` 或重签企业微信。参考 [Frida macOS 官方说明](https://frida.re/docs/examples/macos/)和[官方故障排查](https://frida.re/docs/troubleshooting/)。

### 重签副本捕获路线

当原始企业微信 attach 被 macOS 拒绝，且用户明确允许修改边界时，可以复制并 ad-hoc 重签企业微信副本。脚本会通过 Frida 启动副本并等待 key；如果副本要求登录，只提示用户手动登录，不点击 UI、不发送消息、不关闭原始企业微信。若原始企业微信仍在运行导致副本被单实例机制拉起后退出，必须让用户自己退出原始客户端后再重试。

```bash
python3 "$SKILL_DIR/scripts/capture_key_macos.py" capture \
  --mode spawn-signed-copy \
  --confirm-signed-copy \
  --duration 240
```

副本默认写入：

```text
~/Library/Application Support/wecom-local-vault/apps/WeComSigned-<timestamp>.app
```

该路线会额外 hook `DbKeyManager::UpdateKey`、`GetAllLocalEncryptKey` 回调和内部 wxSQLite3 页加解密函数。当前 5.0.x macOS 客户端里，内部页加解密函数会复制 `args[3][0..15]`，再拼接页码和 `sAlT` 派生每页 AES key；捕获器将这个 16 字节 raw key 候选与当前本地数据库第一页逐一验证，只有验证成功才会保存。

Frida 被系统拒绝时，可改用只读 Mach VM 扫描 DbKeyManager；它不注入代码、不重启或重签客户端、不操作 UI，但需要用户在本机终端输入管理员密码：

```bash
python3 "$SKILL_DIR/scripts/scan_dbkey_manager_macos.py" scan --confirm-sudo
```

该扫描器根据当前进程 load address 定位 `DbKeyManager` vtable，并只读取 `this+0x68` 的 Apple libc++ `std::string` 候选 key；候选通过数据库第一页验证后才写入私密 Vault，终端不显示 raw key。

## 创建明文快照

```bash
python3 "$SKILL_DIR/scripts/vault_cli.py" decrypt
python3 "$SKILL_DIR/scripts/vault_cli.py" decrypt --key-file "/private/path/keys-时间戳.json"
```

快照默认写入：

```text
~/Library/Application Support/wecom-local-vault/snapshots/<timestamp>-<dataset_id>/
```

每个快照包含 `manifest.json`，并标记 `contains_plaintext_wecom_data: true`。脚本把 WAL 中 header salt 匹配、且在最后一次已提交事务以前的页面解密并合并到新快照，不改源 WAL。

## 查询和导出

```bash
python3 "$SKILL_DIR/scripts/vault_cli.py" sessions --limit 50
python3 "$SKILL_DIR/scripts/vault_cli.py" contacts --query "关键词"
python3 "$SKILL_DIR/scripts/vault_cli.py" history "群名或conversation_id" \
  --start "2026-07-01" --end "2026-07-13" --limit 500
python3 "$SKILL_DIR/scripts/vault_cli.py" search "关键词" \
  --chat "群名" --start "2026-07-01" --limit 200
python3 "$SKILL_DIR/scripts/vault_cli.py" export "群名" \
  --start "2026-07-01" --format markdown
```

默认读取最新快照；需要固定证据版本时传 `--snapshot`。导出默认写入私密 Vault 的 `exports/`，文件权限为 `0600`，已有目标文件一律拒绝覆盖。

## 已知限制

- Mac key 捕获依赖企业微信实际打开/读写加密数据库；如果捕获期间没有触发 wxSQLite3 页加解密调用，可能抓不到 key。
- 消息二进制内容采用通用 UTF-8/Protobuf 文本提取；图片、语音、文件正文目前只输出类型占位，不解密媒体。
- 会话方向需要可靠的本人内部 ID；未确认时不要把发送者武断标记为“我”。
- 企业微信版本升级可能改变密钥调用或表结构；先运行离线测试和 `status` 再处理真实数据。

数据库格式、表结构和 WAL 说明见 [references/database-notes.md](references/database-notes.md)。

## 验证

```bash
cd "$SKILL_DIR/scripts"
python3 test_wecom_local_vault.py
python3 -m py_compile *.py
python3 "$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py" "$SKILL_DIR"
```
