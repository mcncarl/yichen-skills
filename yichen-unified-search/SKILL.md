---
name: yichen-unified-search
description: 逸尘自用的统一网页与社交平台搜索编排器。用于关键词驱动的实时公共网页检索、AI HOT 最新 AI 动态发现、并行批量搜索、金融/学术/法律/安全等垂直搜索，以及 GitHub、微信公众号、微博、小红书、抖音、今日头条、知乎、Twitter/X、B站、YouTube、小宇宙等平台的公开内容发现；X 支持逐查询 Quick 与有界多查询 Research。可显式执行受限站点 Map，或对本次搜索所得候选做原文核验和轻量富化，并把不同后端结果统一交接为候选记录。AI HOT 只处理具有时间性的 AI 新闻/发布/日报发现，AnySearch 负责其余公共网页、批量与垂直搜索，Firecrawl 只处理显式站点 Map 或显式候选核验，平台原生/OpenCLI/受限匿名适配器只作对应平台发现。不用于读取或下载用户直接给出的已知 URL、URL 文件或已确认候选；此类任务使用 yichen-content-archive。
---

# 逸尘统一搜索

把搜索拆成“定范围 → 选后端 → 取候选 → 标准化 → 核验”。通过现有工具和受限本地适配器统一执行，不复制登录态或账号数据。

## 固定边界

1. 只搜索和读取用户当轮目标所需的公开内容；不发帖、不评论、不点赞、不关注、不私信、不改变账号状态。
2. 绝对不得操控微信桌面端或移动端 UI。微信公众号只走匿名公共搜索；需要公众号后台或非公开数据时停止并说明此 Skill 不处理。
3. 不读取、同步或搜索私人收藏、书签、个人 Feed、群组、通知、私信、草稿或后台数据。
4. 不下载媒体、不归档、不建立长期数据库、不运行定时监控。用户要读取、下载、转写或归档已审核 URL 清单时，交给 `$yichen-content-archive` 并重新确认动作与范围。
5. 不绕过验证码、登录墙、限流或风控。缺失字段写 `null`，零结果只表示本次后端未返回候选。
6. 用户直接给出已知 URL、URL 文件，或要求读取/下载/归档已确认候选时，停止搜索并交给 `$yichen-content-archive`。唯一的发现型例外是用户明确要求枚举某个公开站点范围时使用显式 `--mode site-map`；它只返回同源且位于输入路径范围内的链接候选，不读取正文。只有用户明确要求“搜索引用、讨论或关联这个 URL 的其他公开内容”时，才把 URL 标记为 `--input-kind url-seed`；该模式只把 URL 当发现线索，不读取或归档 URL 本身。
7. AI HOT 是聚合发现源，不是事实核验源；它的中文摘要可能由 AI 生成，只能作为候选线索。最终引用的事实必须打开候选原始 URL 核验，不能引用 AI HOT 摘要替代原文。
8. AI 实时发现词会发给 AI HOT，公共网页搜索词、默认候选核验 URL 和垂直参数会发给 AnySearch；知乎搜索词会通过另行安装的 Open Platform CLI 兼容运行时发给知乎，该公开内容路线使用 Keychain 认证并标记 `authenticated_public` / `login_state_used=true`；微博搜索词先发给 `m.weibo.cn` 并使用仅驻留内存的临时匿名访客会话，只有匿名路线遇到明确的登录/验证重定向或访问拒绝时，才自动执行一次有界只读 OpenCLI 搜索并复用现有 Chrome 会话；普通非 JSON/解析错误、网络错误和限流不会触发该回退。小红书、抖音的有界公开只读搜索也可复用现有 Chrome 会话。OpenCLI 直接管理会话，Cookie 值不得进入命令、结果或日志。只有显式 `site-map` 的种子 URL 或显式选择 Firecrawl 的当前候选 URL 会发给 Firecrawl；X 公共搜索词首先发给官方 Grok CLI 原生 `x_search`，只有明确额度耗尽时才会发给匿名 FxTwitter。OpenCLI/xreach 可能读取本机 X 登录态，因此计划默认传 `allow_authenticated_fallback=false`；只有用户在当前任务明确授权后，才能用 `--login-approved` 生成 `true`。不得提交密码、Cookie、个人数据、商业秘密或其他敏感查询。

## 路由

先运行离线路由器检查计划；它不联网，也不执行后端：

```bash
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --query "检索词" --platform auto --mode search --limit 10
```

查询明确提及“知乎”或 `zhihu` 时会自动使用另行安装的知乎 CLI 搜索运行时；也可显式指定。本仓库不独立核验该运行时的厂商来源。单查询最多 10 条，`batch` 最多 5 个关键词且每个关键词都是独立 adapter 调用；不改写为 `site:zhihu.com`，也不静默切到 AnySearch。只有显式 `--mode hot` 才读取知乎热榜，最多 30 条：

```bash
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --query "Agent memory" --platform zhihu --mode search --limit 10
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --query "知乎热榜" --platform auto --mode hot --limit 30
```

查询明确提及“微博”或 `weibo` 时会使用本 Skill 的免费优先只读适配器：先尝试临时匿名访客会话，只有访问门失败时自动回退一次 OpenCLI 只读搜索。单查询最多 3 页、最多 20 个候选，批量最多 5 个独立关键词且必须串行、步骤间至少间隔 5 秒；不接收、输出或持久化 Cookie 值，不展开评论、个人主页或媒体：

```bash
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --query "iPhone 18" --platform weibo --mode search --limit 20 --days 30
```

X 默认是 `--depth quick`：每个重复的 `--query` 各生成一次独立 `search_x_with_grok` 调用。单次 `max_results` 最多 20，`--days` 只接受 1–7；默认排除 Repost 和 Reply，可用 `--x-include-reposts`、`--x-include-replies`，以及重复 `--x-author`、`--x-language`、`--x-min-*`、`--x-sort relevance|recent|engagement` 调整检索条件。

```bash
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --platform x --depth quick --days 7 --limit 20 \
  --query "主题 官方发布" --query "主题 独立评测"
```

该计划默认禁用 OpenCLI/xreach 登录态回退。如果 Grok 明确额度耗尽且匿名 FxTwitter 仍失败，应停止并请求当前任务授权；只有取得授权后才可重新生成计划并加 `--login-approved`。

X `--depth research` 必须先把目标拆成至少 3 个互不重复的聚焦查询。路由器顶层 `steps` 每次只放出当前 ready 波次：最多 5 条，且首波不会超过按“目标 ÷ 单次容量”计算的理论最少调用数；其余初始波次保持 `gated`，只有上一波完成归一化、合并且未触发停止条件后才能解锁。每次 Grok 输出必须经 `grok_x_result_adapter.py`，且只把 `<x_post_time_verification>.matched` 映射成统一 envelope；禁止混入 `excluded_outside_window`。将多个 envelope 交给 `x_research_merge.py`，按 `tweet_id`（缺失时 canonical URL）去重；若仍有明确覆盖缺口且尚有预算，最多补搜一轮，该轮可包含多个新的聚焦查询但不得超过剩余外层调用预算。达到 `--target-results`、补搜无新增、无实质缺口、达到 `--max-searches`（最多 40），或主链发生任何非额度故障时停止。500 条目标应规划约 30–40 个独立聚焦查询，并设置 `--target-results 500 --max-searches 40`；这是通用容量示例，不是固定业务规则。

Grok `criteria` 只是检索约束；只有离线合并器会对结果中实际存在的结构化字段做确定性筛选和排序。字段缺失时保留 `null` 与限制说明，绝不能宣称作者、语言、互动阈值、Repost/Reply 类型或排序指标已验证。合并器只读取本轮多个 envelope，不联网、不缓存、不监控。

浏览一个明确的 YouTube 频道时，使用专门的频道模式；频道 URL 在这里是发现容器，不按“读取已知视频 URL”处理：

```bash
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --query "@channelHandle" --platform youtube --mode channel --limit 20
```

把 URL 当作公开搜索种子而不是已知内容读取时，必须显式标记：

```bash
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --query "搜索引用 https://example.com/research 的公开报道" \
  --platform web --input-kind url-seed --limit 10
```

只有明确要求枚举某一站点或文档目录下的公开链接时，才使用受限 Map：

```bash
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --query "https://example.com/docs/" --platform web --mode site-map --limit 100
```

按以下优先级执行：

1. 查询同时具有“AI 主题 + 最近/今天/最新/新闻/动态/发布/日报”等时间性意图，或明确点名 AI HOT 时，先用内置 `aihot_search.py` 的公共 API 契约。普通 AI 概念、教程、原理、历史研究仍走 AnySearch。
2. AI HOT 默认取精选；只有明确说“日报”才走日报，只有明确说“全部/完整/所有/全量”才取全量。items 时间窗最多 7 天；自动路由遇到更长时间窗改走 AnySearch，显式指定 `--platform aihot` 则返回范围错误。
3. 明确要求某平台站内内容时，平台意图优先于 AI HOT。例如“X 上最近的 AI 动态”走 X，“知乎上的 AI 讨论”走 `zhihu_adapter.py search`，“微博上的 iPhone 18 讨论”走 `weibo_adapter.py search`。
4. 明确要求公共网页、普通新闻、多个独立关键词、`site:` 查询或垂直领域发现时，使用 AnySearch。
5. 垂直领域先执行 AnySearch `get_sub_domains`，再带齐所有必填参数搜索；不确定是否垂直时，显式传 `--domain <domain> --hybrid`，用 `batch_search` 为每个原始关键词并行一条通用查询和一条垂直查询。展开后的批次仍不得超过 5 条。
6. 明确要求批量跨关键词时，优先使用 AnySearch；只有显式指定 `--platform aihot` 的纯 AI 批量查询才逐条走 AI HOT。知乎与微博是例外：明确指定时各自最多生成 5 个独立适配器搜索调用。其他平台限定批量才改成公共 `site:` 查询，并标明它不是站内全量结果。
7. 只有需要核验或轻量富化本次搜索刚返回的候选时，才对该候选使用 AnySearch `extract`。不得用它读取用户直接给出的已知 URL。
8. Firecrawl 永不参与普通关键词搜索或静默回退。只有用户明确要求站点链接枚举时，才用 `--mode site-map`，最多 100 条且只保留与种子同源、位于种子路径范围内的公开 URL；只有用户明确选择 `--verify-backend firecrawl` 时，才 Scrape 本轮 AnySearch 搜索产生且短期回执有效的完整候选。
9. AI HOT、AnySearch 或显式 Firecrawl 路线不可用时说明错误；只有用户同意后才改用其他公共网页搜索。唯一预先声明的登录态自动路线是小红书/抖音的有界公开只读搜索，以及微博匿名访问门失败后的一次有界 OpenCLI 只读回退；不得把该许可扩展到私域或写操作。
10. YouTube 关键词搜索和明确频道浏览调用本 Skill 的 `youtube_search.py`。本机存在 `YT_BROWSE_API_KEY` 或 `YOUTUBE_API_KEY` 时可用 Data API 的频道解析、时间和排序能力；否则匿名回退到 `yt-dlp` 公共列表。匿名路线强制忽略用户配置、插件和缓存，仅传入最小非凭证环境并强制 `--skip-download`；两条路线都只返回候选，不下载媒体。
11. X Quick 逐查询调用；X Research 才执行查询拆分、跨 envelope 合并和最多一轮缺口补搜。Research 不得变成持续监控或无界循环。

完整后端、命令形状和登录门槛见 [references/routes.md](references/routes.md)。

## 登录与安全门

- 小红书、抖音站内搜索：有界公开只读搜索可自动复用现有 Chrome 登录态，无需逐次授权。必须一次只跑一个关键词、后台临时会话、串行执行并在步骤间至少间隔 5 秒；小红书单次最多 20 条，抖音单次最多 30 条。发帖、评论、点赞、收藏、关注、私信、删除、账号修改、私域 feed/收藏夹以及验证码处理都不属于搜索许可，必须由用户当轮明确提出并授权，且本 Skill 不执行这些操作。
- Twitter/X：所有关键词搜索第一层固定为官方 Grok CLI 账号 OAuth + 原生 `x_search`。只有输出明确证明账号额度或使用上限耗尽时，才进入匿名 FxTwitter；未登录、401/403、权限、输入、超时、网络和服务错误都必须停止，不能冒充额度错误。FxTwitter 仍失败或零结果时，工具必须因 `allow_authenticated_fallback=false` 停止；只有用户在当前任务明确授权后，计划才能通过 `--login-approved` 传入 `true` 并放行 OpenCLI → xreach。
- 知乎：只调用已单独安装的 Open Platform CLI 兼容运行时；本仓库不独立核验其厂商来源。Access Secret 由该运行时管理在 macOS Keychain，本 Skill 和 adapter 不接收、读取或回显 Secret；关键词查询会发送给知乎。不搜索私人收藏、关注列表或个人内容。
- 微博：只调用 `weibo_adapter.py` 的 `weibo-readonly-auto` 契约。每个进程先新建只驻留内存的临时匿名访客会话；仅当登录/验证重定向、访问拒绝或非 JSON 等访问门失败时，自动执行一次 `weibo-opencli-readonly` 搜索并复用现有 Chrome 会话，无需逐次授权。适配器只允许 `weibo search`，不接收、输出或持久化 Cookie 值；不调用发布、删除、评论、收藏、关注、私信、feed、profile 或验证码处理。网络错误不会触发登录态回退。
- B站、YouTube、微信、今日头条和小宇宙公共发现：先匿名。出现登录限定时停止；本 Skill 不升级为登录读取。
- YouTube API Key 只从现有环境变量读取，不打印、不写入 Skill；缺少 Key 时使用匿名 `yt-dlp`，不得要求用户为普通搜索提供登录 Cookie。
- AnySearch API Key：匿名额度可直接使用。收到新 Key 时先询问，用户明确同意后才能保存；不要让用户在聊天中粘贴 Key。
- AnySearch 候选核验回执使用本机专用 HMAC 密钥；可用 `YICHEN_UNIFIED_SEARCH_RECEIPT_KEY_FILE` 指定私有文件，默认位于 `~/.config/agent-secrets/yichen-unified-search-receipt-key`。适配器首次成功返回候选时以 `0600` 原子创建，绝不打印、不得传给 AnySearch。回执只证明该 URL 确由近期搜索产生，不代表内容事实已核验。
- Firecrawl API Key 只从 `FIRECRAWL_API_KEY` 或 `FIRECRAWL_KEY_FILE` 指定的权限受限私有文件读取；文件默认位于 `~/.config/agent-secrets/firecrawl-api-key`。不接受命令行 Key、不回显。缺少 Key 时显式失败，不自动切换普通搜索后端。

## 标准流程

1. 复述范围：关键词、平台、时间范围、条数、是否需要原生站内覆盖。
2. 运行 `route_search.py`；检查 `status`、`authorization`、`steps` 和 `limitations`。
3. X 搜索先运行 `python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-web-research/scripts/doctor_yichen.py"`，确认 `grok-consult/search_x_with_grok`、Grok CLI OAuth 与原生 `x_search` 可用，再逐条执行计划当前波次中的 Grok 调用。每次结果先用计划指定的 `grok_x_result_adapter.py` 归一化；Research 先处理 `needs_query_expansion`，每波再用 `x_research_merge.py` 合并并检查停止条件，未停止时才解锁下一波或最多一次缺口补搜。工具内部固定执行 Grok CLI → 仅明确额度耗尽时 FxTwitter；默认在这里停止。只有当前任务已明确授权且计划传入 `allow_authenticated_fallback=true` 时，才继续 OpenCLI → xreach。不得因零结果、超时、网络或服务错误提前跳到 FxTwitter。其他多后端或登录态任务也运行该 doctor；OpenCLI 路线再运行 `opencli doctor`。不要回调总路由 Skill，也不要把命令存在当成可用。
4. 仅调用计划中的既有后端。AnySearch 的搜索、批量和候选核验必须调用 `${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/anysearch_adapter.py`；适配器从 `YICHEN_ANYSEARCH_RUNTIME_CONF` 指定的文件读取当前 `Command`，未设置时使用 Skill 根下的 `anysearch/runtime.conf`，并直接输出统一候选 envelope。知乎路由只调用 `${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/zhihu_adapter.py search|hot`，不直接调用未经适配器白名单限制的二进制，也不回退 AnySearch。微博路由只调用 `${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/weibo_adapter.py search --session-mode auto`；它先直连公共端点、忽略环境代理、每次匿名请求间隔 5–8 秒、最多 3 页，只有访问门失败时才执行一次固定参数的 OpenCLI `weibo search`。适配器不得接收或回显 Cookie。只有垂直路由发现子域时才按计划直接调用 `get_sub_domains`。不要复制 CLI，也不要硬编码代理或 Key。
5. 显式 Firecrawl 路线只调用 `${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/firecrawl_adapter.py`。Map 固定官方 v2 endpoint、最多 100 条并在本地重做公开 URL、同源和输入路径过滤；Scrape 只接收带有效 AnySearch HMAC 回执的完整候选，固定 `formats=[markdown]`、`storeInCache=false`、`proxy=basic`、`skipTlsVerification=false`，不传 actions、页面 headers、cookies 或 `zeroDataRetention`。`storeInCache=false` 不等于绝对零数据保留；不要声称启用了 ZDR。
6. AI HOT 路线调用 `${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/aihot_search.py`；该适配器按内置的公共 API 契约访问并直接输出统一候选 envelope。不得去掉浏览器 User-Agent，也不得把 AI HOT 摘要标记为已核验。
7. YouTube 路线调用 `${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/youtube_search.py search ...`；明确频道用同一脚本的 `channel` 子命令。脚本直接输出统一候选 envelope，不得从候选继续下载。上游许可见 [references/THIRD_PARTY_NOTICES.md](references/THIRD_PARTY_NOTICES.md)。
8. AnySearch、知乎 CLI 兼容运行时、微博匿名公共端点/只读 OpenCLI 回退、Firecrawl、AI HOT、FxTwitter 和 YouTube 的本地适配器已直接输出 [references/candidate-schema.md](references/candidate-schema.md) envelope；Grok X 必须经 `grok_x_result_adapter.py`，它只映射 `<x_post_time_verification>.matched`，不得把 `excluded_outside_window` 交给合并器。X Research 的合并器拒绝未经该 matched provenance 闸门的 Grok 候选，并保留每个候选命中的查询与阶段。保持原始 URL、来源平台、真实后端和限制；任何非空原始结果若解析失败，必须写入 `errors`，不得伪装成成功的零结果。
9. X 先按 `tweet_id`、再按 canonical URL 去重；其他平台先 URL 去重。随后才按标题/作者/发布时间做近重复合并；不要把互动量当成事实正确性。
10. 对最终将引用的本轮搜索候选，可把带有适配器签名短期回执的完整 AnySearch candidate JSON（或 `@file`）交给 `anysearch_adapter.py verify --candidate-from-search`；明确需要 Firecrawl 页面渲染时才交给 `firecrawl_adapter.py scrape --candidate-from-search`。两者都不得只传裸 URL，也不得自行拼接 candidate。搜索卡片和摘要只能作发现线索；不要把核验扩展成下载或归档。
11. 交付候选与覆盖说明；标明每个平台的登录态使用、失败、截断、时间筛选和索引局限。

## 最小交付

返回一个候选交接包：

```json
{
  "schema_version": "1.0",
  "request": {},
  "routes": [],
  "candidates": [],
  "coverage": [],
  "errors": []
}
```

若用户只要答案，可用 Markdown 展示精选候选，但内部仍保留同一字段语义。不要把候选列表冒充完整、穷尽或已核验事实。
