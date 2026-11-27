# Windows 本机全量解析

**Windows 本地全量解析已实现，并已在指定客户端环境完成真实验收。** 支持所选账号全部本地数据库的采集、逐页认证解密、聊天主表逐行解析，以及收藏和朋友圈正文解析。完整流程使用 `windows capture --scope all`；Windows 客户端版本和权限适配仍按下方实测范围管理。

“全量”覆盖电脑已经同步的本地数据库和记录。媒体文件本体还原、尚未同步到电脑的手机历史、漏看/待回复等高级工作流分别按其实际完成状态说明。

适用于用户明确授权的本机 Windows 微信账号。必须在该 Windows 环境执行；Mac 上只能使用已有的离线明文快照，不能因此转去抓取 Mac 账号。用户自行完成安装协议、扫码登录及测试消息操作；采集脚本不操作微信界面。

## 执行

使用独立 CPython 3.12 AMD64 环境和 [固定 zstandard 依赖](windows-snapshot/requirements.lock)。AES 使用 Windows 自带 CNG，无额外加密包、Frida、调试器或注入。Windows ARM64 上使用 AMD64 Python 的兼容运行环境；这不等于已验证原生 ARM64 微信的内存布局。

```powershell
python scripts/vault_cli.py windows discover
python scripts/vault_cli.py windows capture --source-id SOURCE_ID
# 全量采集所选账号的本地数据库，仍不跨账号
python scripts/vault_cli.py windows capture --scope all --source-id SOURCE_ID
python scripts/vault_cli.py snapshot --snapshot PRIVATE_SNAPSHOT_PATH validate
python scripts/vault_cli.py snapshot --snapshot PRIVATE_SNAPSHOT_PATH chats --query "测试会话"
python scripts/vault_cli.py snapshot --snapshot PRIVATE_SNAPSHOT_PATH history CHAT_ID --limit 20
python scripts/vault_cli.py snapshot --snapshot PRIVATE_SNAPSHOT_PATH search CHAT_ID "测试标记"
```

`discover` 只检查当前 Windows 用户 Documents 下的标准 `xwechat_files` 目录并列出账号的匿名 `source_id`、聊天数据库数量及进程 PID，不读进程内存。数据目录已迁移时，显式使用 `--db-root 'D:\微信数据\账号目录\db_storage'`；不扫描其他磁盘、其他用户或自动选最近账号。多账号必须明确选择，不能按更新时间取第一项。

`capture` 可用 `--pid` 指定已发现的微信进程。默认每个数据库及 WAL 各限 512 MiB、内存扫描限 90 秒；确有需要时显式提高 `--max-db-mib`（最多 8192）或 `--seconds`（最多 300），注意机器内存。默认 `--scope chat` 只选 `contact/contact.db`、`session/session.db` 和 `message/message_N.db` / `biz_message_N.db`。明确要求全量本地库时选 `--scope all`，在所选账号的 `db_storage` 内安全遍历 `.db`，拒绝链接或重解析点；限制 258 个库、256 个目录和 8 层深度，不跨其他账号或磁盘。它包含收藏、朋友圈、媒体和搜索索引，但不补造尚未同步或缺失的数据库。

## 数据边界

- 进程必须名为 `Weixin.exe`、通过 Windows 信任签名校验且属于所选 Windows 用户。只请求查询和读取内存权限；不提权、不注入、不暂停或重启进程、不修改客户端或源数据库。
- 主路径读取运行时 `Config.Cipher` 对象并对候选密钥做首个数据库页 HMAC 校验；兼容回退扫描旧格式的密钥字面量。内存布局和 XOR 掩码有版本及架构差异；未命中必须报告，不把抓到任意 32 字节当作成功，不改用调试断点或关闭保护。
- 每页均验证 HMAC-SHA512，再用 AES-256-CBC 解密。保留 SQLite 的 80 字节保留区，写出后执行完整 `integrity_check`。按 SQLite/SQLCipher 文件格式规范，超过 1 GiB 的数据库在 `0x40000000` 处的保留锁字节页（4 KiB 页大小下为第 262145 页）仅在整页严格全零时原样透传，该页若非全零或任意其他页（含全零页）仍须通过完整 HMAC 校验。全库模式下，仅当三个已知搜索索引 `contact/contact_fts.db`、`favorite/favorite_fts.db`、`message/message_fts.db` 返回实测的 `SQL logic error` 时，将其校验明确记为 `unverified`；所有页面仍须认证，主数据失败或其他错误仍使采集失败。带此缺口的回执为 `complete_with_index_gaps`，不是所有库完整性通过；原因尚未确定，不猜测为缺少分词器或损坏。
- 读取主库与 WAL 前后检查文件元数据，变化时最多重试三次。校验 WAL 格式、代际 salt、滚动校验和，仅重放最后提交的事务；损坏日志、持续变化或 rollback journal 导致失败。不会忽略 WAL 后发布旧的主库副本，也不 checkpoint 源库。
- 一致性单位是单个数据库；多个库按顺序读取，不能声称整个账号在同一事务时刻取得。manifest 明确记录此限制。
- 密钥仅驻内存，不保存或打印。Python 运行时不保证所有对象副本立即物理清零；不要输出内存转储。

## 私密输出与查询

快照位于 `%LOCALAPPDATA%\YichenWeChatVault\windows-live\snapshots\<新UUID>`，目录 ACL 仅允许对应 Windows 用户和 SYSTEM。每次尝试创建独立目录；完整解密、完整性检查及 Schema 验证通过后才更新私密 `latest.json`。失败产物保留为不完整状态，不能当作上次结果已刷新。

默认聊天采集的 manifest `profile` 为 `windows-chat-capture-v1`：要求 contact、session 和至少一个兼容消息分片。`--scope all` 使用 `full-snapshot-v1`，必须实际存在并通过核心验证的 contact、session、favorite、sns、message_resource 和消息分片；缺任一核心库便失败，不更新成功指针。旧的无 profile / `full-snapshot-v1` 原契约不变；`snapshot` 路径不会自动触发采集或放宽链接、UNC、sidecar、Schema 检查。索引缺口保存在 manifest 和回执的 `integrity_gaps`。

查询和导出沿用 [快照模式](windows-snapshot.md) 的只读保护、解码限额和正文展示层。账号 username 未明确提供时，消息方向保持 `unknown`，不要根据目录猜测自己是谁。新快照的 chat_id 会变化，须重新 `chats` 选择。

默认导出目录为本机私密应用数据区。明文库、聊天正文和密钥均不上传或回传到其他机器/项目目录；测试回执只报告数量、校验结果、时间范围及测试标记是否命中。用户确需导出正文时，先确定具体会话、时间范围与本地位置。

## 验收边界

合成测试覆盖 CNG AES 已知向量、加密页面、逐页篡改、真实 SQLite 回读、WAL 事务边界/增长/截断/校验损坏，以及来源隔离。通过合成测试只证明这些机制，不能证明真实微信密钥获取或聊天 Schema 已兼容。

真实验收需用户登录指定账号并手动向测试会话发送无敏感内容的唯一标记，然后后台采集，确认该会话中标记和时间命中；再由用户发送第二个标记，重新采集并验证第二条出现。只报告实际完成的阶段，不把安装、登录或旧消息命中当作实时采集通过。

来源与 MIT 许可证见 [PROVENANCE](windows-live/PROVENANCE.md)。

## 已验证的真实环境

2026-10-27 实测：Windows 11 build 26300 ARM64，运行 AMD64 微信 4.1.15.56、CPython 3.12.10 AMD64、SQLite 3.49.1 和 zstandard 0.25.0。已验证同用户与签名门禁、运行时 Config.Cipher 密钥提取、真实聊天库逐页认证/解密、WAL 组合读取、完整 integrity_check、Schema 和真实会话有界查询。

首轮验收证明上述环境中的聊天路径：两条手动发送的唯一新消息依次在新快照出现，旧快照保持不变；统一 CLI 的采集、搜索、双标记 Markdown 导出回读及中文路径均通过。后续全库、收藏和朋友圈正文验收见下段。其他客户端版本、原生 ARM64 客户端及媒体文件本体还原仍需分别验证。虚拟机共享网络与宿主机出网不兼容时，先解决网络并确认客户端可登录，再开始后台验收；仅 TCP 端口可连接不足以证明登录服务可用。

权限条件：本次真实全流程由本地测试服务触发，并在现有桌面管理员（高完整性）令牌下复验完整采集与新消息查询；未调整系统安全设置。普通非管理员/中完整性进程尚未验收，不能据此承诺所有权限环境可用。权限不足时报告失败，不自动提权或关闭保护。

2026-10-28 同环境任务验收进一步完成所选账号全部本地库的逐页认证解密、核心库完整 SQLite 校验，以及所有聊天主表的逐行解析和私密文件回读；三个搜索索引的校验仍报 `SQL logic error`。本地收藏、朋友圈样本已复用 `vault_cli.parse_favorite` / `parse_moment` 纯函数完成正文解析和回读，没有触发 Mac 配置或工作流；尚未封装成专用 Windows 查询子命令。详细账号统计仅留在本地任务回执，不进入分发包。该样本只覆盖电脑已同步的短期数据，不能证明手机多年历史、大规模库、媒体文件还原或完整 Mac 功能对齐。运行时必须使用安装了固定 `zstandard` 依赖的微信专用 Python；其他测试 Python 缺该依赖时，压缩正文会明确失败，不能当作已全量解析。

社区补充实测（#29，2026-11-04）：Windows 11 Pro 10.0.26300 x64 + 微信 4.2.0.11 + CPython 3.12.9 AMD64 + zstandard 0.25.0 上 `--scope chat` 跑通（含 838 MiB 消息分片）。同报告指出超过 1 GiB 的旧分片在第 262145 页（`0x40000000`）存在 SQLite 标准锁字节全零页；代码已按 SQLite/SQLCipher 规范增加对该位置全零页的严格透传处理，待实机复验 1 GiB+ 分片。

## 朋友圈和收藏正文解析

Windows 的这两项能力通过包内现成函数和只读快照提供。仅调用下列纯函数，不执行 Mac 命令、不读取 Mac 配置。

1. 先对明确选择的账号运行 `windows capture --scope all`，再用 `snapshot ... validate` 核对核心库和 `integrity_gaps`；需要最新内容时重新采集。
2. 用 `snapshot_reader.connect_read_only` 打开快照中的 `favorite/favorite.db` 或 `sns/sns.db`，按用户明确的时间、类型或联系人范围读取。保留单条解码和累计扫描预算，不一次把大量正文装入上下文。
3. 收藏读取 `fav_db_item` 的 `type`、`update_time`、`content` 等字段；用 `snapshot_reader.decode` 解码正文后交给 `vault_cli.parse_favorite(content, fav_type)`。
4. 朋友圈读取 `SnsTimeLine` 的 `tid`、`user_name`、`content`；解码后交给 `vault_cli.parse_moment(content, tid, db_user)`。函数只提取本地正文及媒体引用，不访问链接或下载远程媒体。
5. XML 含 `DOCTYPE` / `ENTITY` 时拒绝解析；不因失败而输出原始 XML。结果按共用展示规则隐藏账号标识和显式凭据，只保存到授权的本地私密输出目录；不要写进输入快照或回传完整正文。
6. 回读输出并核对源行数、成功解析数、失败或空正文数及文件行数。聊天主表全量解析同样逐行计数；CLI 查询和导出的默认条数限制不代表整库记录总数，大结果按会话和时间分批落盘。

已完成真实收藏和朋友圈正文的解析、私密文件保存及回读。当前接口形式为上述共用函数工作流，尚未单独提供 `snapshot favorites` / `snapshot moments` 命令。
