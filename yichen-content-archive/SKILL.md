---
name: yichen-content-archive
description: 读取、下载并归档用户已提供的普通网页、Twitter/X 推文与 Article、小红书、抖音、微信公众号、YouTube、B站和小宇宙链接、URL 文件、上游已确认候选或用户明确指定的 known_collection；内置小红书图文/视频与抖音视频抓取，并可在用户明确要求时把小红书素材沉淀到指定飞书多维表格。用于“把这些已知链接读一下/下载/归档”“下载这条抖音”“抓取/沉淀这篇小红书”“读取这条 X 推文或 X Article”“归档这个明确播放列表/播客清单/公众号历史”等已有明确输入的任务；不得用于关键词搜索、站点爬取、账号/频道发现、相似推荐、跨来源扩展、私人收藏导出或未确认候选扩展。
---

# 已知内容归档

优先使用本 Skill 内置的固定安全执行器，再编排仍独立维护的平台 Skill。小红书与抖音抓取已经内置，不再调用旧的独立抓取 Skill；不要复制搜索、收藏导出或其他平台的认证实现。

## 入口闸门

仅接受以下输入：

- 用户当轮直接给出的一个或多个内容 URL。
- 用户给出的本地 URL 文件。
- 上游产物中逐项标为 `confirmed` 的候选，或用户当轮明确选中的候选。
- 用户明确指定的 `known_collection`：URL 文件、YouTube/B站播放列表、已知小宇宙播客或 episode 清单、已知公众号历史容器。
- `$yichen-bookmarks-export` 生成的链接文件，但只有用户另行明确要求读取、下载或归档后才可使用。

`known_collection` 必须带精确容器 URL、ID、用户给出的准确账号名称或本地清单路径，并指定数量上限、时间范围或明确全量。精确容器枚举只列出该容器直接包含的条目，不属于搜索发现；不得从条目继续进入作者主页、推荐区、相似列表或其他来源。

不满足以上条件时停止并说明需要已知链接、已确认候选或明确容器。不得替用户搜索、浏览未指定账号/频道、扩展相似内容或补齐推荐列表。

## 硬边界

1. 不得执行关键词搜索或开放式发现；禁止站点爬取、未指定频道/账号浏览、推荐扩展、相似内容查找和跨来源补齐。只允许用户明确指定 `known_collection` 的精确容器枚举。
2. 不得调用任何总路由；不得再次调用 `$yichen-content-archive`；不得通过其他 Skill 间接回到本 Skill。
3. 不得把“读取”推断成“下载”，不得把“下载”推断成登录态授权，也不得把“归档”推断成写入飞书多维表格。仅执行用户当轮明确要求的动作。
4. 不得自动读取私人收藏。收藏导出的当轮授权不能转移为媒体下载授权。
5. 不得删除任何文件。目标存在时创建不冲突的新目录或文件名，不静默覆盖。
6. 不得打印或写入普通日志中的 Cookie、Token、登录凭证或带敏感查询参数的完整 URL。
7. 不得绕过登录、验证码、付费墙、删除状态、地区限制或访问控制。
8. 微信公众号路线只处理已知公开文章 URL 或用户明确指定的公众号历史容器；绝对不得操控微信客户端。若本地 exporter 登录失效，只能说明用户需本人完成本地页面扫码与手机确认并等待其回复，不得代替点击、扫码或确认。
9. Twitter/X 已知链接先走 FxTwitter → Jina 匿名公共读取。只有匿名路线失败或 Article 正文不完整时，才列出 OpenCLI → xreach 回退；执行任何一个登录态回退前必须针对当前链接取得当轮明确授权。
10. 小红书默认匿名读取。只有当前笔记匿名解析或媒体下载失败，且用户对该目标当轮明确授权后，才可从私有配置向子进程注入 `XHS_COOKIE` 并显式传 `--use-cookie`；不得读取、打印或保存 Cookie。

## 执行流程

### 1. 固化范围

记录：

- 输入类型：`known_urls`、`url_file`、`confirmed_candidates` 或 `known_collection`。
- 平台与条数。
- `known_collection` 的精确容器引用、枚举上限/范围及是否允许当前请求内枚举后直接归档。
- 动作：`read`、`download`、`archive` 中用户明确要求的集合。
- 输出目录；未指定时使用新的日期时间目录，不覆盖旧产物。
- 是否需要登录态；如需要，必须按目标平台或本 Skill 对应执行器的规则取得当轮授权。
- 是否明确要求把小红书素材写入飞书多维表格；没有明确要求时只做本地读取、下载或归档。

候选只有在上游明确标记或用户当轮选择后才算 `confirmed`。只存在标题或关键词不算可执行输入。账号名、频道名或播客名只有在用户明确把它指定为 `known_collection` 容器，并给出范围后才可用于容器解析；不得作为搜索词扩展其他结果。

### 2. 选择单个平台路由

完整读取 [references/platform-routes.md](references/platform-routes.md)，再读取表中指定的现有平台 Skill、参考文件或脚本帮助。只调用允许的已知链接/精确容器路径：

- 普通网页：Jina Reader / Web Reader；只读用户给出的 HTTP(S) URL，不做站点爬取。
- Twitter/X：本 Skill `x_known_url.py` 识别已知 Post、Quote 与 Article；匿名 FxTwitter 优先，必要时匿名 Jina，登录态 OpenCLI/xreach 只作授权后的回退。
- 小红书：本 Skill `xiaohongshu_fetch.py`；`--skip-media` 只读 HTML 与元数据，去掉该参数才下载已知笔记媒体，授权后才可 `--use-cookie`。明确要求沉淀到飞书时再读取 [references/xiaohongshu-bitable.md](references/xiaohongshu-bitable.md)。
- 抖音：本 Skill `douyin_download.py`；`--metadata-only` 只读元数据，去掉该参数才下载已知视频。
- 微信公众号：单篇与已知 URL 文件归档用 `$yichen-wechat-mp-batch-exporter` 或本机 `wechat_mp_local.py`；已知公众号历史只走本机精确容器路线，并在当轮授权后传入 `--allow-local-account-session`。
- YouTube：直接使用 `yt-dlp` 读取、下载或获取已知 URL 字幕；已知播放列表先平铺枚举。
- B站：`bili-cli` 读取已知 BV/AV/完整 URL，`yt-dlp` 下载；已知播放列表先平铺枚举。
- 小宇宙：`xiaoyuzhou_stepfun.py` 匿名读取/下载已知 episode；已知播客清单仅在当轮授权后用 `xiaoyuzhou_opencli.py` 枚举，再回到匿名批量下载。

目标平台没有明确路由，或精确容器无法由现有后端枚举时，将该项记为 `unsupported`；不要转给总路由、自行发明抓取实现或降级成搜索。

### 3. 先预检，再执行授权动作

- `read`：使用平台 Skill 的元数据、正文或字幕读取路径，不顺带下载媒体。
- `download`：只下载用户明确要求的正文、图片、视频、音频或字幕类型。
- `archive`：把平台 Skill 产物写入新目录，并保留来源、状态和失败清单。

`known_collection` 先生成 `enumerated-urls.txt` 或平台现有等价清单，记录容器引用、枚举上限、返回数与截断状态，再只对清单内条目执行归档。用户已在同一请求明确要求“枚举后归档”时无需重复确认清单；但登录态、会员内容、StepFun 额度或其他目标级门仍需单独满足。

批量任务低并发、可断点续跑。单项失败后记录原因并继续其余已确认项；不要为了补数量搜索新内容。

### 4. 执行防覆盖

只使用本 Skill `scripts/` 下的安全执行器，不直接调用旧同名脚本：

- `xiaohongshu_fetch.py`：只接受小红书已知 HTTPS 链接，默认匿名抓取并优先解析 `window.__INITIAL_STATE__`，失败时回退网页 meta；输出目录存在时自动创建 `-run-N` 新目录。只有当前目标获当轮登录态授权后才可显式传 `--use-cookie`。
- `douyin_download.py`：只接受抖音已知 HTTPS 链接，使用 Playwright 获取目标视频详情；`--metadata-only` 不下载视频。视频或相邻 metadata 已存在时自动创建 `-run-N` 新文件名。
- `x_known_url.py`：只接受 `x.com`/`twitter.com` 的 status 或 `/i/article/` URL；status 返回内嵌 `article` 对象时自动判定为 Article，只有直接输入 `/i/article/<ID>` 时才在 FxTwitter 搜索结果中精确匹配 `article.id` 定位父推文。这属于解析已知对象，不得扩展其他候选。默认不使用任何登录态；匿名不完整时仅输出授权回退计划。
- `xiaoyuzhou_stepfun.py`：默认 episode 目录已存在时自动创建 `-run-N` 新目录；`--resume` 只复用 `source.json`、文件大小和 SHA-256 全部一致的产物，绝不重写 `source.json`。用户显式指定的单集输出目录已存在时默认拒绝。
- `xiaoyuzhou_opencli.py`：默认排他创建输出目录与清单文件。Agent 禁止自动使用兼容 `--overwrite`；只有用户当轮明确点名覆盖同一绝对目录，并同时提供独立的 `--confirm-overwrite-exact-dir <绝对路径>` 高摩擦确认后，包装器才接受。
- `wechat_mp_local.py`：用户指定的输出目录已存在时默认拒绝。需要续跑时显式传 `--resume-existing --output-dir <既有目录>`；既有目录只作为只读 checkpoint，待处理项写入同级新的 `<name>-resume-<run_id>` 目录，不在旧 run 内新增或修改文件。

不得通过换用旧脚本、直接调用底层 OpenCLI 或自行写文件绕过这些闸门。

### 5. 生成归档清单

归档根目录至少包含：

```text
<archive-root>/
|-- archive-manifest.jsonl
|-- run-summary.json
|-- failures.json
`-- <platform>/
    `-- <content-id-or-sequence>/
```

`archive-manifest.jsonl` 每行只记录一个已确认输入，至少包含：

```json
{"item_ref":"opaque-or-line-ref","platform":"xiaohongshu","source_url_ref":"input.txt:3","requested_actions":["archive"],"status":"success","artifact_paths":["/absolute/path"],"route_backend":"xiaohongshu-known-url","fetched_at":"RFC3339"}
```

容器条目额外记录 `container_ref`、`container_position` 和 `enumeration_status`。后端不是 Skill 时使用 `route_backend`，例如 `jina-reader`、`yt-dlp` 或 `xiaoyuzhou-stepfun`。

敏感 URL 优先使用文件行号引用，不在摘要、聊天或普通日志中重复完整值。缺失字段写 `null`，不得推断补齐。

### 6. 输出标准交接

读取并遵守 [references/handoff-contract.md](references/handoff-contract.md)。交接必须写明 `discovery_performed: false`；`known_collection` 使用 `scope.input_kind: known_collection`，并把枚举清单作为 artifact 引用。精确容器枚举不改变“未执行搜索发现”的事实。继续写明实际授权、产物绝对路径、成功/失败计数和下一步是否需要新的明确请求。

最终只报告：

- 已处理、成功、失败、跳过和不支持数量。
- 实际调用的平台 Skill 或现有后端。
- 归档根目录、清单和失败文件路径。
- 尚需用户决定或重新授权的动作。

不要把抽样成功表述为全部内容永久可访问。
