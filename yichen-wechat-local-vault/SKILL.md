---
name: yichen-wechat-local-vault
description: |
  微信本地数字资产库：支持 macOS 与已实测 Windows 环境的本地全量解析，包括全库采集、认证解密、聊天记录读取/搜索/导出，以及朋友圈和收藏正文解析。Mac 另支持增量刷新和漏看/待回复检查，默认微信1，微信2须明确指定。Windows 本机采集走 windows，离线聊天查询走 snapshot，朋友圈/收藏复用包内纯函数工作流；不触发 Mac 配置或流程。依赖最新聊天时必须先刷新相应来源，不能拿旧记录代替目标。Windows 版本及功能边界见本机采集参考。
---

# 微信本地解析 Vault

这个 skill 提供同一个本地入口，分别处理 Mac vault、Windows 本机聊天采集和显式离线明文快照。Mac 模式处理官方微信容器 `com.tencent.xinWeChat` 内已确认的账号数据，默认微信1，微信2须由用户明确指定；这里的账号编号不等于双开容器编号，不自动处理双开/第二独立微信容器。遵守用户的界面操作限制；Windows 登录和测试消息由用户手动完成。`snapshot` 模式完全不访问微信进程、密钥、Mac 配置或运行中客户端。

本版本吸收了两类外部工具的优点：

- WeChat CLI 风格：统一命令入口、JSON 默认输出、最近会话、历史记录、全局搜索、联系人详情、群成员、统计、导出、收藏夹、未读和增量新消息。
- 宝玉群聊摘要工作流：按群归档、从上次摘要继续、摘要素材包、群友画像目录、历史索引、图片说明扩展点，以及“大批量先落文件再分析”的安全习惯。

## 隐私边界

- 不在回复或日志里输出 key、完整 salt、wxid、原始聊天库内容，除非用户明确要求展示。
- 密钥、配置、明文库、manifest、增量状态和导出目录都由本机配置文件管理；skill 文档不要写入任何个人机器的真实绝对路径、wxid、联系人或聊天内容。
- 建议把密钥和明文库放在本机私有应用数据目录，把可读报告放在用户自选的导出目录；路径以占位符或配置字段说明即可。
- 不要把明文数据库复制到项目工作区、桌面、网盘目录或聊天回复里；工作区只放用户明确要求的导出报告。
- 查询和导出的消息正文统一经过 `scripts/message_display.py`：入群/撤回通知转为可读事件，链接、文件和合并转发只提取可读字段；未知、破损或带实体声明的 XML 返回占位提示，不回退输出原文。正文里的显式凭据字段默认隐藏。
- Mac CLI 默认在 JSON、`--format text` 和导出中隐藏账号标识（username、微信号），名字缺失时回退成的标识也一并隐藏，显示为“[内部标识已隐藏]”；用于本机精确匹配的内部读取函数仍保留标识。确需从 CLI 导出这些字段时，在子命令前加 `--include-identifiers`，并直接保存到本机私密 JSON，不把输出打印到日志或回复。只有用户明确要求展示时才显示标识；该参数不会放开原始 XML 或附件凭据。
- 这些保护不代表正文已匿名化：昵称、自我介绍、用户主动发送的联系方式等仍可能包含个人资料。不要靠“字符串以 `<` 开头”筛除 XML，群号前缀、转义内容和嵌套转发都可能绕过该判断。

## 先确定数据来源

- **Mac 本机聊天 / 增量刷新**：先按下方账号选择规则确定微信1或微信2，再沿用 Mac 工作流和现有 `vault_cli.py` 命令；不能把“当前登录账号”当作默认账号。
- **用户提供的 Windows 离线明文快照**：阅读 [Windows 快照模式](references/windows-snapshot.md)，使用 `vault_cli.py snapshot --snapshot <目录> ...`。先 `validate`，再 `chats` 选出精确 `chat_id`，最后查询或导出。不要求另装独立 Windows Skill。
- **Windows 本机已登录账号，且明确授权采集与解密**：阅读 [Windows 本机采集](references/windows-live.md)，使用 `vault_cli.py windows discover/capture`，再把成功生成的快照交给 `snapshot` 查询。只读目标账号的聊天库与签名通过、同属该 Windows 用户的 `Weixin.exe` 内存；密钥仅驻内存。此路径仍为实验性，已验证环境及未完成的验收见该参考文档，不扩展为所有 Windows 版本和功能兼容。
- **Windows 本地全量解析已实现**：用户要求“全量”“全部本地数据”时，使用 `windows capture --scope all --source-id ...`，采集所选账号的全部本地数据库，包括收藏、朋友圈和媒体库；未要求全库时默认只选聊天必需库。聊天查询使用 `snapshot` 的 `validate`、`chats`、`history`、`search` 和 Markdown `export`；朋友圈/收藏正文按 [Windows 正文解析工作流](references/windows-live.md#朋友圈和收藏正文解析)复用包内纯函数执行。当前未单独封装这两个查询子命令。`complete_with_index_gaps` 表示搜索索引校验仍有缺口，不能说所有库完整性均通过；媒体库解密也不等于媒体文件已还原。最新消息必须重新采集；新快照须重新选择 chat_id。缺库、Schema 不兼容或快照内有 WAL/SHM 时报告缺口，不尝试 Mac 流程、不删除 sidecar、不伪造缺失库。
- 快照源系统由用户提供的信息确定，不根据当前运行的是 Mac 还是 Windows 猜测。可以在 Mac 上分析已授权的 Windows 明文快照，但真实 Windows 微信版本兼容性仍为实验性。

## Mac 模式：账号选择规则

账号选择先于全量、增量、新鲜度检查、查询和导出：

1. **未明确指定账号的新请求，一律使用微信1。** “解析微信”“微信增量”“全部解析”“查最新消息”等均指本机已确认的第一个账号；微信1绑定既有默认配置，不按当前登录账号、数据库更新时间、目录扫描排序或上次解析对象重新选择。
2. **只有用户明确说“微信2”“另外一个微信”“另一个微信”或明确指定第二账号，才使用微信2。** 该选择仅作用于这次请求及其必要后续，不把微信2设成之后任务的默认账号。只有明确要求两个账号一起处理时，才分别读取并合并结果。
3. **两个账号的数据与状态隔离。** 微信2使用自己对应的配置、密钥、明文目录、manifest、增量状态和导出位置，不覆盖微信1的默认配置或混用微信1的解析状态。命令若仅支持全局配置，应采用显式隔离配置的调用或已验证的指定快照，不通过临时改写全局配置来切换账号。
4. **执行前核对所选账号的数据源与输出路径。** 默认账号的数据缺失、未同步或查不到结果时，报告该账号的缺口，不自动尝试微信2；无法可靠确认账号绑定时，先说明缺口，不按目录先后猜测。

## Mac 模式：强制新鲜度闸门

先完成账号选择，再判断所选账号的数据新鲜度。不要默认把现有 `decrypted/current` 当成最新数据；“最新、当前、继续”等词只决定是否刷新，不改变默认账号规则。

出现以下任一情况，必须先自动运行 `decrypt_all_dbs.py --mode incremental`，无需让用户再次说“增量”或重复确认：

- 用户说“最新、今天、刚才、刚发、刚收到、最近、当前、继续、新消息、看看我和某人的对话、帮我回这一条”。
- 用户要求读取刚提到的聊天记录转发、文件、链接、图片、语音或某个新会话。
- 任务目标是判断对方当前诉求、写下一条回复、跟进客户或分析最近关系变化。
- 首次查询没有命中，只有时间明显更早的同名结果，或最新消息时间早于用户明确给出的时间。
- 用户纠正“不是这个”“是今天发的”“刚刚才发”。此时立即作废旧命中，增量刷新后按新的精确日期和会话重新查询，不能继续沿用旧结论。
- 只读检查发现源数据库或 WAL 比最近一次解密 manifest 更新。

自动增量后的固定校验顺序：

1. 读取本次 manifest，确认目标所需的 `contact`、`session` 和相关 `message_*` 数据库为成功或“未变化”；无关的媒体/资源库失败不能冒充消息增量失败。
2. 按用户给出的日期、联系人和消息类型缩小查询范围；同名联系人优先用别名、微信号或最新会话时间消歧，不能猜。需要看微信号或 username 时用 `--include-identifiers contacts --query ...`，只在本机核对，不写进回复。
3. 核对目标消息时间和会话最新时间确实落在用户指定范围内，再开始分析。
4. 如果仍未命中，只允许再检查一次源数据库/WAL 是否在本次解析后发生变化；发生变化时再增量一次，否则明确说明“尚未落入本地库”。不要静默改查旧记录、全量重建、抓新 key、启动微信或点击 UI。

以下情况可以跳过自动增量：用户明确要求只看固定旧快照；任务只分析已经给出的本地导出文件；查询的是明确的历史时间段且现有明文库已覆盖；任务只是解释 Skill 或数据库结构。拿不准时优先增量，因为它只更新私密 vault，不写回微信源库。

## Mac 模式：自动选择工作流

根据用户指令选最小必要动作：

1. 用户说“第一次用、解不开、key 没了、全部解密、全量重建”：走全量路线。
2. 用户说“继续、更新一下、增量、最近、今天、新消息”，或语义上依赖当前聊天：先过“强制新鲜度闸门”，再走增量路线。
3. 用户点名联系人/群聊/会话 ID：只查询这一条会话；如果涉及当前状态，必须先增量解密消息库。
4. 用户给时间范围：只按该时间范围导出或分析。
5. 用户问朋友圈/收藏夹：只读取对应已解密库；缺 key 再补抓。
6. 用户明确说“群聊摘要、群聊精华、日报、复盘、从上次继续”时，优先用 `vault_cli.py digest-source` 生成素材包，再基于素材写简报；不要把整个 skill 解释成摘要工具。
7. 用户问“有没有漏回/漏看”“谁在等我回复”“有没有人 @我”时：先过“强制新鲜度闸门”，再用 `vault_cli.py pending`；不要只看 `unread`，对方已读未回、群里被 @ 或引用都可能是 0 未读。
8. 用户问“转账记录”“谁转了我多少钱”“某段时间收了多少转账”时：先过“强制新鲜度闸门”，再用 `vault_cli.py transfers`；它只覆盖聊天里的转账消息，不是微信支付账单。
9. 用户要求不操作微信界面时，只能使用 `--match-only`、已保存 key、已解密库或本地数据库文件；不要启动 Computer Use。

## 统一查询入口

日常查询优先使用 `scripts/vault_cli.py`。下列旧命令用于 Mac 已解密 vault；Windows 快照在脚本名后加 `snapshot`，按来源专用命令执行。查询入口本身不抓 key、不碰微信 UI。

```bash
python3 {{SKILL_DIR}}/scripts/vault_cli.py status --format text
python3 {{SKILL_DIR}}/scripts/vault_cli.py sessions --limit 20 --format text
python3 {{SKILL_DIR}}/scripts/vault_cli.py unread --format text
python3 {{SKILL_DIR}}/scripts/vault_cli.py new-messages --format text
python3 {{SKILL_DIR}}/scripts/vault_cli.py pending --since 48h --format text
python3 {{SKILL_DIR}}/scripts/vault_cli.py transfers --chat "联系人或群名" --start-time "2026-01-01" --format text
python3 {{SKILL_DIR}}/scripts/vault_cli.py contacts --query "关键词" --format text
python3 {{SKILL_DIR}}/scripts/vault_cli.py members "群名" --format text
python3 {{SKILL_DIR}}/scripts/vault_cli.py history "联系人或群名" --start-time "2026-05-01" --end-time "2026-05-14" --format text
python3 {{SKILL_DIR}}/scripts/vault_cli.py search "关键词" --chat "群名" --type link --format text
python3 {{SKILL_DIR}}/scripts/vault_cli.py stats "群名" --start-time "2026-05-01" --format text
python3 {{SKILL_DIR}}/scripts/vault_cli.py export "群名" --format markdown --output ./chat.md
python3 {{SKILL_DIR}}/scripts/vault_cli.py favorites --type article --query "关键词" --format text
python3 {{SKILL_DIR}}/scripts/vault_cli.py moments --name "联系人" --start "2026-05-01" --format text
```

消息类型过滤支持：`text`、`image`、`voice`、`video`、`sticker`、`location`、`link`、`file`、`call`、`system`。

`search` 会解开压缩存储的长文本、文件、链接、引用和合并转发，按可读文字（文件名、链接标题等）匹配；`--chat` 覆盖整个会话历史，不只最新几十条。只命中“[文件]”“[图片]”这类标签不算匹配。`history --media` 按消息记录的文件大小核对本地文件，能认出微信给同名文件自动改名的 `name(1).ext`；大小对不上时不给路径，避免指向别的会话的同名文件。

### 转账记录

`history`、`search`、`export` 把转账显示为“[转账] ￥88.00（备注：定金） · 发出/已收款/已退还”。要按时间段汇总，用 `transfers`：

- 每笔转账一行：发起时间、转入/转出、对方、金额、备注、状态（已收款、已退还、超时退还、已过期未收、待收款）和收款或退还时间；文本报告开头给转入已收、转出被收、净额、待收合计。
- `--chat` 可重复，不填为全部会话；`--start-time`/`--end-time` 按发起时间筛选，会多读 3 天以找到窗口外的收款或退还。
- 只统计聊天里留下的转账消息：删掉的聊天、扫码付款、红包和商户付款都不在内；完整流水以微信支付账单为准。只有收款或退还消息、缺少发起消息的转账不列出，数量写在 `gaps`。
- 账号标识默认隐藏；结果含金额和备注，回复里只给用户问到的部分。

### 漏看/待回复检查

`unread` 只看会话未读数；对方已读却没回、群里被 @ 或引用、待收转账和未接来电常常是 0 未读。这类问题用 `pending`：

```bash
python3 {{SKILL_DIR}}/scripts/vault_cli.py pending --since 7d --output ~/Documents/wechat-local-vault/exports/漏看检查/pending.json
python3 {{SKILL_DIR}}/scripts/vault_cli.py pending --since last --previous ~/Documents/wechat-local-vault/exports/漏看检查/pending.json --format text
```

- 信号：私聊里对方最后发言、本人未回（`--pending-days` 天内，默认 7）；群里 @我、引用我、提到我的昵称或备注、@所有人（每群最多 2 条，免打扰群排后）；待收或超时退回的转账、本人转出未被收的转账；私聊红包；未接/拒接来电。
- 规则：本账号从私聊发言识别，配置里的 wxid（去掉数据目录的 4 位十六进制后缀）作后备，`--decrypted-dir` 指向另一个账号的明文库时也按该库的发言认人；接通的通话算已沟通，拍一拍、表情、“好的/谢谢”类只标“疑似客套/表情”；在截止前由本人主动退还的转账不算漏收。
- 窗口：`--since` 支持 `48h`、`7d`、`YYYY-MM-DD HH:MM` 或 `last`，最多回看 14 天；终点是该明文目录最近一次成功解析的时间，manifest 缺口、中止或超过 2 小时都写进 `manifest.gaps`。
- 接续：`--previous` 读上次的 pending JSON（旧的漏看检查 JSON 也可），把上次列过且无新消息的私聊标为“上期已列出”；`--since last` 从上次终点接着查。命令本身不写状态。
- 隐私：默认 JSON，`--format text` 出可读报告；账号标识默认隐藏，`--include-identifiers` 才输出 `username` 供精确 `history` 查询。结果含私聊片段，大结果用 `--output` 落成权限 600 的私密文件；候选只是信号，回复里只引用判断所需的一两句。

### 群聊摘要素材包

用户要“群聊精华、日报、总结群聊、看看这个群最近聊了什么、从上次继续”时：

```bash
python3 {{SKILL_DIR}}/scripts/vault_cli.py digest-source "群名" --start "2026-05-01" --end "2026-05-14" --format text
python3 {{SKILL_DIR}}/scripts/vault_cli.py digest-source "群名" --since-last --data-root ~/Documents/wechat-digests --format text
```

输出会落到 `{data_root}/{group_id}-{group_name}/sources/`，并创建：

- `profiles/`：普通版群友画像。
- `profiles-roast/`：毒舌版画像，必须和普通版分开。
- `imgs/`：图片说明扩展点，格式为 `{message_id}.txt`，一行描述一张图。
- `sources/*.json`：可机器读取的消息素材、发言统计和路径信息。
- `sources/*.md`：便于人工阅读和写作的素材稿。

素材包不自动更新 `history.json`。只有最终摘要写完并确认后，才更新摘要历史，避免半成品污染“从上次继续”的锚点。

## 常用命令

查看本机有哪些库，不启动微信：

```bash
python3 {{SKILL_DIR}}/scripts/extract_keys.py --list-dbs
```

用已有抓取日志匹配 key，不启动微信：

```bash
python3 {{SKILL_DIR}}/scripts/extract_keys.py --match-only --targets all --reuse-log
```

首次全量抓 key。只在需要抓新 key 时使用；不要碰第二微信：

```bash
python3 {{SKILL_DIR}}/scripts/extract_keys.py --targets all --duration 240
```

全量解密到私密 vault：

```bash
python3 {{SKILL_DIR}}/scripts/decrypt_all_dbs.py --mode full
```

日常增量刷新。只跳过未变化的库，不重新处理全部内容：

```bash
python3 {{SKILL_DIR}}/scripts/decrypt_all_dbs.py --mode incremental
```

导出某个联系人完整聊天：

```bash
python3 {{SKILL_DIR}}/scripts/export_chat.py --contact "联系人备注" --mode full
```

导出某个联系人新增聊天：

```bash
python3 {{SKILL_DIR}}/scripts/export_chat.py --contact "联系人备注" --mode incremental
```

按精确会话 ID 和时间范围导出：

```bash
python3 {{SKILL_DIR}}/scripts/export_chat.py --chat-id "contact_username" --since "2025-01-01"
```

旧脚本仍可用于窄任务；如果用户没有特别指定，优先使用 `vault_cli.py`。

## 工作流

### 全量路线

用于首次配置、换设备、微信升级后 key 变化、用户明确要求全量重建。

1. 先运行 `extract_keys.py --list-dbs` 看本地库，不展示敏感 salt。
2. 如果 `~/.config/wechat-keys.json` 已有 key，先用 `--match-only --targets all --reuse-log` 尝试复用。
3. 只有复用失败或缺关键库时，才运行抓 key。
4. 运行 `decrypt_all_dbs.py --mode full`，明文库写入私密 vault。
5. 读取 manifest 确认解密数量和失败项。

### 增量路线

用于日常更新、继续上次工作、分析近期新增内容，以及任何虽未明说“增量”但答案依赖当前聊天的任务。

1. 运行 `decrypt_all_dbs.py --mode incremental`。
2. 读取最新 manifest，先确认目标所需数据库成功或未变化，再查询会话。
3. 如果目标是联系人/群聊，按精确日期先用 `vault_cli.py history` 查询；只有需要生成可读文件时才运行 `export_chat.py --mode incremental`。
4. 如果没有新增消息，核对源数据库/WAL 的更新时间和目标会话最新时间；确认本地尚无目标后再告诉用户，不能回退成旧同名记录。
5. 增量状态只写入 vault 的 `state` 目录，不写进 skill 文档。

### 指定会话分析

用于“分析我和某某的聊天”“导出这个会话 ID”“帮我写下一条怎么回”。

1. 若用户给的是备注/昵称，使用 `export_chat.py --contact`。
2. 若用户给的是微信 userName 或会话 ID，使用 `export_chat.py --chat-id`。
3. 导出后读取报告，按用户目标分析关系、语气、风险、下一步话术。
4. 不要默认展示全部原文；用户要“仔细解析”时再给完整时间线或报告路径。

### 朋友圈/收藏夹解析

优先使用已解密的 `sns/sns.db`、`favorite/favorite.db`、`message_resource.db`。缺 key 时只补相关库，不全量抓取。输出到用户配置的导出目录。

### 群聊精华/日报路线

1. 先运行增量解密，确保明文 vault 是最新的。
2. 用 `vault_cli.py contacts` 或 `sessions` 解析群名，确认唯一群聊。
3. 用 `digest-source` 按时间范围生成素材包；大群或长时间范围先落文件，不要把几百上千条原始消息直接塞进对话。
4. 读取 `sources/*.md` 和必要的 `sources/*.json`，先列话题骨架，再写正文。
5. 输出结构优先采用：标题、消息统计、发言排行、开篇概览、群友画像、分类正文、待解决问题、固定结尾。
6. 需要毒舌版时，可以基于同一素材另写，但不得做人身攻击、健康/家庭/身份属性推断，也不得用时间戳推断作息或所在地。
7. 图片内容默认不可见；如果 `imgs/{message_id}.txt` 存在，才把其中描述用于摘要。否则只能写“图片内容不可见，根据上下文推断到这里围绕一张图片讨论”，不要编造画面。
8. 摘要确认完成后，再更新群目录下的 `history.json` 和 `history-digests.jsonl`；用户要求“从上次继续”依赖这些文件。

授权范围内的群图片需要本地识字时，使用 `scripts/group_image_media.py` 的 `AttachmentFinder`、`image_key_candidates`、`decode_image_dat_to_preview` 和 `ocr_image_with_local_engine`。调用方须先核对账号绑定、按范围过滤消息，并把解码文件放在私有目录；该模块只处理本地附件，不查询消息库、不操作微信界面或调用网络 OCR。附件查找只在当前群的哈希目录中精确匹配图片 MD5；扫描超时或失败要读取 `finder.gaps`，不能当作“图片无字”。不要为群图识字导入外部 sidecar 或其他业务项目的附件查找代码。识字文字只是候选，重要事实须看原图核对。

## 输出原则

- 回复里优先给结论、文件路径、下一步建议；完整原文放 Markdown 文件。
- 涉及私聊时，少量引用必要原文即可，避免把整库内容贴到聊天里。
- 明确区分“已解密明文库”“可读导出报告”“密钥配置”。
- 每次涉及解密完成，说明保存位置和是否包含明文隐私。

## 现有脚本

- `scripts/vault_cli.py`：统一本地查询入口，保留 Mac 命令（含 `pending` 漏看/待回复检查和 `transfers` 转账记录）并路由 Windows `snapshot` 子命令。
- `scripts/snapshot_reader.py`：有边界的 Windows 离线明文快照查询/导出后端。
- `scripts/wechat_schema.py`：两种来源共用的消息表名和字段别名；来源验证与解码策略分别保留。
- `scripts/message_display.py`：查询、会话摘要和聊天导出共用的消息展示与字段脱敏；不读配置、不访问客户端、不改写源库。
- `scripts/extract_keys.py`：本机 key 捕获、复用和匹配。
- `scripts/decrypt_all_dbs.py`：全量/增量解密，写入私密 vault，并生成 manifest；日志和 manifest 里的账号目录（以 wxid 命名）显示为 `<账号目录>`。
- `scripts/export_chat.py`：按联系人、群聊或会话 ID 导出完整/增量聊天记录。
- `scripts/list_contacts.py`：列出联系人和群聊。
- `scripts/wechat_digest.py`：按天摘要脚本，仅在用户明确要摘要时使用。
- `scripts/search_sns.py`：朋友圈搜索辅助。
