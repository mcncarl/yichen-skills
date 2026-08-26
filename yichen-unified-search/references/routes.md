# 后端路由与命令契约

只在需要执行具体平台搜索时读取本文件。命令均为只读搜索；不要附带下载、收藏、评论、发布或归档步骤。

平台适配器的总安全规则以 `${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-web-research/SKILL.md` 为事实源；具体搜索边界以本 Skill 为准。多后端或登录态任务先运行：

```bash
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-web-research/scripts/doctor_yichen.py"
opencli doctor  # 仅 OpenCLI 路线需要
```

按照体检的真实 active backend 执行；命令存在不等于后端可用。

## AnySearch：默认公共后端

搜索、批量和候选核验统一调用本 Skill 的适配器。它会安全读取 `YICHEN_ANYSEARCH_RUNTIME_CONF` 指定的绝对路径配置；未设置时默认使用 `${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/anysearch/runtime.conf`。相对路径 fail closed。适配器执行既有 AnySearch CLI，并把 Markdown 结果直接归一成候选 envelope。不要复制 AnySearch CLI，不要覆盖其配置。

```bash
# 公共网页
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/anysearch_adapter.py" \
  search "query" --max-results 10

# 仅核验/轻量富化本次搜索所得、带有效短期回执的完整 AnySearch candidate；
# 不接受裸 URL 或自行拼接的 candidate
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/anysearch_adapter.py" \
  verify --candidate-from-search @candidate.json

# 批量；单批最多 5 个查询，每个查询最多 10 条
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/anysearch_adapter.py" \
  batch --queries \
  '[{"query":"q1","max_results":10},{"query":"q2","max_results":10}]'

# 垂直领域：先从 runtime.conf 读取 <anysearch_cmd>，发现子域和必填参数，
# 再让归一化适配器执行搜索
<anysearch_cmd> get_sub_domains --domain legal
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/anysearch_adapter.py" \
  search "query" --domain legal --sub-domain "<returned-sub-domain>" \
  --sub-domain-params '{"required_key":""}' --max-results 10

# 不确定是否需要垂直域：离线路由器为每个关键词生成 general + vertical 两份请求
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --query "query" --platform web --domain legal --hybrid --limit 10
```

支持的垂直大类以 AnySearch 实时 `get_sub_domains` 输出为准。所有标记为 required 的参数都必须出现；没有适用值时传空字符串。`--hybrid` 必须与 `--domain` 同用，展开后的 `batch_search` 仍按最多 5 条切批。AnySearch 非空输出无法解析时，适配器会返回显式 `parse_error`，不得当成真实零结果。AnySearch 失败后先报告，不静默换后端。

## 知乎：另行安装的 CLI 候选后端

查询中明确出现“知乎”或 `zhihu`，或显式指定 `--platform zhihu` 时，路由到 `backend=zhihu-open-platform-cli`。该另行安装的运行时声明兼容知乎 Open Platform CLI 能力，本仓库不独立核验其厂商来源。单个关键词最多返回 10 个候选；`--mode batch` 最多接受 5 个关键词，并为每个关键词生成一个独立 `zhihu_adapter.py search` 调用。不得改写为 `site:zhihu.com`，也不得静默改用 AnySearch。

```bash
# 单查询；适配器再调用固定 CLI search zhihu 能力
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/zhihu_adapter.py" \
  search --query "query" --limit 10

# 批量不组装一个私有 batch 协议；按路由计划独立执行最多 5 次上述命令
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --platform zhihu --mode batch --limit 10 \
  --query "query one" --query "query two"

# 热榜必须显式选择 hot；最多 30 条
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/zhihu_adapter.py" \
  hot --limit 30
```

`--mode hot` 只允许显式 `platform=zhihu`，或者 `platform=auto` 且查询文本能识别出知乎；不得把普通“热门”请求猜成知乎热榜。当前配置的 CLI search 能力无分页（no pagination）且无时间过滤（no time filter）；返回量只是本次有界候选，不是全量结果。摘要、赞同数、评论数、`AuthorityLevel` 与 `RankingScore` 都是 candidate 元数据，不代表已打开原文核验。

本 Skill 只通过适配器调用配置的 CLI；可用绝对路径 `ZHIHU_CLI` 覆盖二进制位置，macOS 默认使用当前用户 `~/Library/Application Support/zhihu-cli/current/zhihu-cli`。不接受 endpoint 或密钥参数。Access Secret 必须由该 CLI 的配置流程保存到 macOS Keychain，查询词会发送给知乎；适配器不读取、打印或写入 Access Secret。因为该公开内容路线使用 Keychain 凭证，route 与 candidate 都标记 `login_state_used=true`，候选的 `visibility=authenticated_public`。该 CLI 的 `global_search` 不替换 Unified Search 的 AnySearch 公共网页路由；`zhida` 与 `me` 下的 contents/followees/favorites 等私有或个人命令不进入 Unified Search。

## 微博：免费优先的自动只读候选后端

查询中明确出现“微博”或 `weibo`，或显式指定 `--platform weibo` 时，路由到计划后端 `backend=weibo-readonly-auto`。适配器先访问 `m.weibo.cn` 公共移动搜索端点；每个进程生成一个仅驻留内存的临时匿名访客会话。只有匿名路线遇到明确的登录/验证重定向或访问拒绝时，才自动执行一次固定参数的 `weibo-opencli-readonly` 搜索并复用现有 Chrome 会话。普通非 JSON/解析错误、网络错误和限流不触发回退。这个有界公开只读回退无需逐次授权，OpenCLI 直接管理会话，Cookie 值不进入命令、结果或日志。

```bash
# 单查询：最多 3 页、最多 20 个候选；--days 是本地时间过滤
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/weibo_adapter.py" \
  search --query "iPhone 18" --limit 20 --max-pages 3 --days 30 --session-mode auto

# 批量按路由计划串行执行最多 5 次上述命令，步骤间至少间隔 5 秒
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --platform weibo --mode batch --limit 20 \
  --query "iPhone 18" --query "Apple A20"
```

这是免费优先的非官方发现路线，不等于微博官方、完整或稳定索引。匿名请求固定低频串行、间隔 5–8 秒且无自动重试；浏览器回退也只执行一次搜索。不展开评论、个人主页或媒体，不下载，不调用发布、删除、收藏、关注、私信、feed、profile 或验证码处理。`--days` 只过滤有界返回且时间可解析的候选，不是服务端日期检索；时间无法解析的候选保留并明确标注未知。HTTP、网络、限流、重定向、非 JSON 或结构变化都显式写入 `errors`，不得伪装成零结果；普通网络错误不触发登录态回退。

## Firecrawl：仅显式 Map 与候选核验

Firecrawl 不是普通搜索后端，也不是 AnySearch 的静默回退。只有用户明确要求枚举某个公开站点/文档目录的链接时才走 `site-map`；只有用户明确选择 Firecrawl 核验时才走 Scrape：

```bash
# 离线路由：单个公开种子，最多 100 条
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --query "https://example.com/docs/" --platform web --mode site-map --limit 100

# 执行路由生成的 Map step
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/firecrawl_adapter.py" \
  map --url "https://example.com/docs/" --limit 100

# 明确选择 Firecrawl 核验；路由器只放完整候选占位符，不把裸 URL 放进 argv
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --query "原始搜索词" --mode verify-candidate \
  --candidate-url "https://example.com/result" --candidate-from-search \
  --verify-backend firecrawl
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/firecrawl_adapter.py" \
  scrape --candidate-from-search @candidate.json
```

适配器只访问固定官方 v2 `https://api.firecrawl.dev/v2/map` 与 `https://api.firecrawl.dev/v2/scrape`。Map 请求显式 `includeSubdomains=false`，输入必须是公共 HTTP(S) URL；返回链接还要在本地重新通过公共 URL、同源和输入路径范围检查，跨域、私网、本机和路径外链接不得成为候选。Map 是链接发现，不读取正文、不保证站点穷尽，也不参与普通关键词搜索。

Scrape 只接受 `anysearch_adapter.py` 本轮 search/batch 生成、结构完整且 `provenance.anysearch_receipt` 仍有效的 candidate；不提供 `--url`、自定义 endpoint 或任意请求载荷入口。固定请求只有 `formats=[markdown]`、`storeInCache=false`、`proxy=basic`、`skipTlsVerification=false`，不得传 actions、页面 headers、cookies 或 `zeroDataRetention`。`storeInCache=false` 只关闭该请求的 Firecrawl 缓存写入，不等于绝对零数据保留；ZDR 需要团队侧开通，当前契约不声称具备。

API Key 只从 `FIRECRAWL_API_KEY` 或 `FIRECRAWL_KEY_FILE` 指定的权限为 `0600`（或更严格）的私有文件读取；文件默认位于 `~/.config/agent-secrets/firecrawl-api-key`，不接收命令行 Key、不回显。HTTP 非成功、超时、超限、非 JSON、`success!=true`、Map 结构异常或 Scrape 缺少非空 Markdown 都 fail closed：输出失败 envelope，不交付部分伪成功结果，也不自动改用别的后端。

## AI HOT：AI 实时发现后端

仅当查询同时具有 AI 主题和明确时间性，或用户明确点名 AI HOT 时使用。它提供最近 AI 动态的精选、全量、分类、关键词和日报发现；它不是通用网页搜索，也不是最终事实核验源。

离线路由器会生成适配器命令。适配器内置 AI HOT 公开 API 契约、携带浏览器 User-Agent，并把结果直接转成统一候选 envelope：

```bash
# 默认：滚动时间窗内的精选 AI 动态
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/aihot_search.py" \
  --query "今天 AI 圈有什么" --feed selected --days 1 --limit 20

# 明确说“全部”时才取全量；分类和服务端关键词可叠加
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/aihot_search.py" \
  --query "OpenAI 最近全部模型发布" --feed all --days 7 --limit 30 \
  --category ai-models --keyword OpenAI

# 只有明确说“日报”才取日报；指定日期用于更早的日报存档
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/aihot_search.py" \
  --query "AI 日报" --feed daily --limit 30
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/aihot_search.py" \
  --query "7 月 30 日 AI 日报" --feed daily --date 2026-07-30 --limit 30
```

items 搜索最多覆盖最近 7 天。自动路由收到更长窗口时使用 AnySearch；显式指定 AI HOT 时返回范围错误，较早内容只能按日期查日报。AI HOT 的 `summary` 可能由 AI 生成，统一映射为 `verification.status=candidate`，最终引用前必须打开 `url` 核验原文。

## X Quick 与有界 Research

两种深度都只生成离线计划；真正搜索仍逐条调用 `grok-consult/search_x_with_grok`。每个调用的 `max_results` 会截到 20，X 的 `--days` 必须在 1–7 之间。无论一次 Grok 调用内部执行多少轮原生 `XSearch`，外层预算都按一次 `search_x_with_grok` 计算。

Quick 是默认值。每个重复的 `--query` 都生成一个独立 Grok 调用，不再丢弃第二个及后续查询：

```bash
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --platform x --depth quick --mode search --days 7 --limit 20 \
  --query "主题 官方发布" \
  --query "主题 独立评测"
```

Research 先要求至少 3 个互不重复、仍在用户原始范围内的聚焦查询。若不足，路由器返回 `needs_query_expansion` 和建议拆分轴，不执行搜索。顶层 `steps` 只包含当前 ready 波次；首波大小取查询数、5 条上限和按目标容量计算的理论最少调用数三者中的最小值，避免目标很小时仍无谓放出 5 次搜索。`research.initial_waves` 中后续波次为 `gated`，上一波经归一化、合并且未达到停止条件后才能执行。为避免重复执行，ready 首波的步骤实体只在顶层 `steps`，其波次对象用 `step_count` 计数且 `steps=[]`；gated 波次的步骤实体才存放在各自的 `steps_after_gate`。每次 Grok 工具结果必须先交给 `grok_x_result_adapter.py`，它只接受 `<x_post_time_verification>.matched` 并写入 matched provenance；`excluded_outside_window` 只计覆盖数，绝不进入候选池。初搜后把各次调用的 envelope 交给离线合并器；它按 `tweet_id`、缺失时按 canonical URL 去重，并拒绝未经 matched provenance 闸门的 Grok 候选。只有仍存在实质覆盖缺口且预算允许时，才能围绕缺口再补搜一轮；这一轮可以包含多个新查询，但总调用数仍受 `--max-searches` 限制。停止条件为：达到目标、补搜没有新增唯一候选、没有实质缺口、耗尽外层搜索预算，或主链发生任一非额度故障。

```bash
# 通用 500 条容量示例：实际应先生成约 30–40 个独立聚焦查询，
# 每个都以独立 --query 传入；这里仅展示参数形状。
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --platform x --depth research --mode search --days 7 --limit 20 \
  --query "主题 官方发布" \
  --query "主题 技术证据与演示" \
  --query "主题 独立分析与失败报告" \
  --target-results 500 --max-searches 40
```

`--max-searches` 最多 40，`--target-results` 是全局去重后的目标，不是单次返回量；目标必须能被 `max_searches × 20` 的有界容量覆盖。500 条不是保证值，重复结果、零结果和字段缺失都会降低实际唯一候选数。

X 默认请求排除 Repost 和 Reply。需要放开时使用 `--x-include-reposts`、`--x-include-replies`；作者用可重复的 `--x-author`，另有 `--x-language`、`--x-min-likes`、`--x-min-reposts`、`--x-min-replies`、`--x-min-views` 和 `--x-sort relevance|recent|engagement`。

这些选项首先写进 Grok `criteria`，属于检索约束，不是已验证字段。只有离线 `x_research_merge.py` 能对候选中实际存在的结构化字段重新做确定性筛选与排序；缺失指标、作者、语言或 Reply/Repost 标志时不得猜测，也不得声称阈值已经验证。合并器只读取本轮提供的多个统一 envelope，不发网络请求、不保存缓存、不建立 watchlist 或定时监控。

```bash
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/grok_x_result_adapter.py" \
  --input grok-query-01.txt --query "主题 官方发布" \
  --call-index 1 --phase initial

python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/x_research_merge.py" \
  --input x-query-01.json --input x-query-02.json --input x-query-03.json \
  --author example --language zh --min-likes 10 \
  --sort engagement --limit 500
```

两个离线脚本的 `--input` 都可使用一次 `-` 从 stdin 读取；合并器的 `--input` 还可重复，`--author`、`--language`（也可写 `--lang`）同样可重复。合并器默认只排除结构化字段明确标记为 `true` 的 Repost/Reply；状态未知的候选会保留并附限制说明。互动阈值字段缺失时不能通过对应阈值。

## 平台适配器

| 平台意图 | 既有适配器 | 登录门槛 | 重要限制 |
|---|---|---|---|
| 最近 AI 新闻/发布/动态/日报 | 内置 `aihot_search.py` | 匿名公共 API | 聚合发现，不穷尽；摘要可能由 AI 生成，引用前核验原文 |
| GitHub 公共仓库 | `gh search repos --visibility public --limit N -- <query>` | `gh` 可使用本机 GitHub 凭据访问公开 API；命令强制只搜公开仓库 | 查询位于 `--` 之后，不能注入 `gh` 选项；不声称实现 code/Issue/PR 对象选择，不 clone、不改仓库 |
| 知乎关键词/热榜 | 本 Skill `zhihu_adapter.py search|hot` → 另行安装的 `zhihu-cli` 兼容运行时 | Access Secret 由该 CLI 保存到 macOS Keychain | 只返回 candidate；search 单查询最多 10、无分页/时间过滤；hot 最多 30 |
| 微信公众号跨号关键词 | `opencli weixin search` | 匿名公共搜狗微信路线 | 绝不操控微信 UI；不进后台 |
| 微博公开关键词 | 本 Skill `weibo_adapter.py search --session-mode auto`；匿名 `m.weibo.cn` 优先，访问门失败后一次 `weibo-opencli-readonly` | 临时匿名访客会话；必要时自动复用现有 Chrome 会话，无需逐次授权 | 免费优先、只返回 candidate；单查询最多 3 页/20 条，不接收、输出或持久化 Cookie 值，不取评论/主页/媒体 |
| 小红书站内关键词 | `opencli xiaohongshu search` | 有界公开只读搜索可自动复用现有 Chrome 会话，无需逐次授权 | 单关键词、后台临时会话、串行；最多 20 条，不下载、不展开评论；严格时间窗须按返回时间再过滤 |
| 抖音站内关键词 | `opencli douyin search` | 有界公开只读搜索可自动复用现有 Chrome 会话，无需逐次授权 | 单关键词、后台临时会话、串行；最多 30 条，不下载、不展开评论；严格时间窗须按返回时间再过滤 |
| 今日头条综合非视频 | `opencli toutiao search` | 专用匿名 profile，不读取用户 Chrome | 单关键词、低频、无自动重试 |
| Twitter/X 公共搜索 | `route_search.py --depth quick|research` → `grok-consult/search_x_with_grok` → 仅额度耗尽时 `fxtwitter_search.py` → 仅当前任务授权时 OpenCLI → xreach | Grok CLI 使用账号 OAuth；FxTwitter 匿名；OpenCLI/xreach 默认禁用，只有计划 `--login-approved` 传入 `allow_authenticated_fallback=true` 时才可读取本机会话 | 每个 `--query` 一次外层调用、单次最多 20、时间窗最多 7 天；Research 才跨查询去重并最多补搜一轮 |
| B站公开视频 | `bili search` | 匿名优先 | 只生成候选 URL，不下载 |
| YouTube 公开视频/明确频道 | 本 Skill `youtube_search.py`；环境中已有 API Key 时用 YouTube Data API v3，否则匿名 `yt-dlp` | API Key 只从环境读取；匿名回退不使用登录 Cookie | 只列统一候选元数据和 URL，不下载；频道模式只接受明确频道 |
| 小宇宙全站关键词 | AnySearch `site:xiaoyuzhoufm.com` | 匿名公共网页 | OpenCLI 不提供全站关键词搜索 |

### 命令形状

```bash
# GitHub：当前只路由公共仓库搜索；查询位于 `--` 之后
gh search repos --visibility public --limit 10 -- "query"

# 微信公众号公共关键词
opencli weixin search "query" --page 1 --limit 10

# 微博：匿名优先、访问门失败后一次只读浏览器回退；不取评论、主页或媒体
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/weibo_adapter.py" \
  search --query "iPhone 18" --limit 20 --max-pages 3 --days 30 --session-mode auto

# 小红书/抖音：有界公开只读搜索无需逐次授权；后台临时会话并在完成后释放标签页
opencli xiaohongshu search "query" --days 1 --content all --limit 20 --enrich --window background --site-session ephemeral --keep-tab false -f yaml
opencli douyin search "query" --days 1 --content all --limit 30 --enrich --window background --site-session ephemeral --keep-tab false -f yaml

# 今日头条：只保留文章和非视频图文帖
opencli toutiao search "query" --days 1 --limit 20 -f yaml

# X 第一层：先体检并调用 Grok CLI 原生 x_search
grok models
# 然后按 route_search.py 的每个 step 各调用一次
# grok-consult/search_x_with_grok；它负责核验 completed XSearch。

# 仅当 Grok 输出明确证明账号额度或使用上限耗尽时，工具内部才运行：
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/fxtwitter_search.py" \
  --query "query" --limit 20 --days 1

# FxTwitter 仍失败或零结果时默认停止；只有当前任务已授权且计划含 `--login-approved` 时才继续 OpenCLI → xreach。

# B站 / YouTube：仅发现候选
bili search "query" --type video --page 1 -n 20 --json
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/youtube_search.py" \
  search "query" --limit 20 --backend auto

# 明确频道浏览；匿名路线需 @handle、UC channel ID 或精确频道 URL
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/youtube_search.py" \
  channel "@handle" --limit 20 --backend auto
```

## 选择细则

- 用户说“今天/最近/最新的 AI 新闻、AI 动态、AI 发布”时，使用 AI HOT 精选；明确说“日报”才用日报，明确说“全部/完整/所有/全量”才切全量。
- 普通 AI 概念、原理、教程、历史或超过 7 天的系统研究使用 AnySearch。指定平台优先，例如“X 上最近的 AI 动态”仍走 X。
- 用户说“全网、新闻、官网、多个关键词、批量、垂直领域”时，使用 AnySearch。
- 用户明确说“知乎上”或 `zhihu`时，使用 `zhihu-open-platform-cli`；批量最多 5 个独立 search 调用，不使用 AnySearch `site:` 代替。热榜只在显式 `--mode hot` 时使用。
- 用户明确说“微博上”或 `weibo` 时，使用 `weibo-readonly-auto`；匿名 `weibo-public-anonymous` 优先，只有明确的登录/验证重定向或访问拒绝时才自动执行一次 `weibo-opencli-readonly` 搜索；普通非 JSON/解析错误、网络错误和限流不触发。批量最多 5 个独立调用且必须串行、步骤间至少间隔 5 秒，不使用 AnySearch `site:` 代替；Cookie 值不得进入适配器输入、输出或日志。
- 用户明确说“列出这个站点/文档目录下有哪些页面”时，才使用 `--mode site-map`；普通 `site:` 搜索、关键词搜索和新闻搜索仍使用 AnySearch。
- 用户明确要求用 Firecrawl 打开本轮 AnySearch 候选时，才使用 `--verify-backend firecrawl`；未显式选择时继续用 AnySearch 核验，不得自动升级。
- 用户说“某平台站内、该平台最新帖子、平台账号/作品”时，使用对应平台适配器。
- YouTube 全站关键词走 `search`；用户给出明确 `@handle`、频道 ID 或频道 URL 并要求查看该频道作品时走 `channel`。人名/模糊频道名只有 Data API Key 可用时才允许解析；匿名路线不猜频道。
- 用户只说“社交媒体讨论”但未指定平台时，先用 AnySearch 的 `social_media` 垂直域发现公开候选；需要站内覆盖再让用户指定平台。
- 除知乎和微博外，平台限定的批量查询默认改成 AnySearch `site:` 公共网页查询；在覆盖说明中写明“不等于站内全量”。
- AnySearch `extract` 只能由 `anysearch_adapter.py verify` 间接调用；输入必须是本次搜索 envelope 中带有效 `provenance.anysearch_receipt` 的完整 AnySearch candidate，并保留候选 ID 与原始查询的 provenance。回执默认有效 2 小时，绑定 run ID、candidate ID、URL、query、检索时间和过期时间；缺失、篡改、密钥不匹配或过期均拒绝。用户直接给出的已知 URL、URL 文件，以及读取/下载/归档已确认候选的任务，交给 `$yichen-content-archive`。
- 用户明确要求“搜索引用、讨论或关联某 URL 的其他公开内容”时，可用 `--input-kind url-seed` 把 URL 作为发现查询的一部分；该模式不得读取、下载或归档种子 URL 本身。默认 `auto` 遇到任意 URL 仍安全交接到归档层。
- 平台原生适配器只在必须补平台结构化字段时使用。
- 小红书、抖音的有界公开只读搜索可直接按计划执行，无需逐次授权；一次只跑一个关键词，使用后台临时会话并低频串行。发帖、评论、点赞、收藏、关注、私信、删除、账号变更、私域 feed/收藏夹或验证码处理必须由用户当轮明确提出并授权，且不属于本搜索 Skill。
- X 关键词搜索一律先执行 `grok-consult/search_x_with_grok`。Quick 对每个重复 `--query` 各执行一次；Research 先拆成至少 3 个聚焦查询，再执行有界初搜、跨 envelope 去重和最多一轮缺口补搜。该工具固定使用 Grok CLI 原生 `x_search`；只有明确账号额度或使用上限耗尽时才进入 `fxtwitter_search.py`。FxTwitter 失败或零结果后默认停止；只有用户在当前任务明确授权且计划传入 `allow_authenticated_fallback=true` 时，才继续 OpenCLI → xreach。
- X 的 `limit` 只决定每个外层调用的期望条数并被截到 20；不要把 `--target-results` 写进单次 Grok 调用。Research 的 `--max-searches` 包含初搜和补搜，最多 40。
- Grok criteria 只约束检索；确定性筛选、排序与去重只以 `x_research_merge.py` 实际读到的结构化字段为准。未知指标继续为 `null`，不能根据自然语言摘要补值。
- 未登录、401/403、权限、输入、超时、网络、服务异常、零结果或搜索证据不可核验都不是额度耗尽；这些情况必须停止并报告，禁止静默调用 FxTwitter。
- FxTwitter 请求只发公开关键词，不携带 Cookie、Token 或 X 登录态；只请求一页，不自动翻页、不自动重试。它是第三方公共索引，零结果不能证明 X 上没有相关内容。
- FxTwitter 返回普通推文、引用推文和 Article 候选时，保留引用对象与 Article 标题、预览和封面元数据；搜索阶段不得展开 Article 全文。全文读取仍交给 `$yichen-content-archive`。
- `grok-consult/search_x_with_grok` 当前不可调用时，只报告主链不可用；不要自动安装插件，也不要绕过固定四层链另找账号后端。
- 任何验证码、登录墙、权限错误或账号安全提示都应停止，不尝试绕过或自动重试。
