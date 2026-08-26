# 逸尘统一搜索

[English](./README.md) | 简体中文

`yichen-unified-search` 是一个安全优先、全程只读的公开网页与平台搜索编排器。
它覆盖通用网页、AI 时效动态、站点链接枚举，以及 11 个明确平台路由：
GitHub、知乎、微信公众号、微博、小红书、抖音、今日头条、X/Twitter、B站、
YouTube 和小宇宙。

你只需给出主题、平台、时间范围和期望数量，它会先在本地生成一份离线计划，
选定一条有界路由，显式列出授权状态、执行步骤和已知限制。仓库内置适配器
会输出可审核的统一候选包；直接调用外部 CLI 的路由依然保持原始输出，不会被冒充为
已经标准化。

这个 Skill 的核心价值是“**找到可核验的候选线索**”，不是把搜索卡片、摘要或热度排名
当成事实。它不下载媒体、不归档页面、不读取私人收藏、不操控微信，也不做发布、
评论、点赞等写操作。已知 URL 的读取、下载和归档属于 `yichen-content-archive`。

## 为什么需要统一路由

同一个查询不应该无差别地发给所有已安装服务。统一搜索会先判断需要哪种发现方式，
再只把请求交给选中的后端：

```text
主题 + 范围 + 平台 + 时间窗口
  -> route_search.py 离线路由计划
  -> 一条公开或已认证公开的受限路由
  -> 有界搜索
  -> 统一候选包，或有明确说明的原生 CLI 输出
  -> 可选：打开本轮搜索的签名候选做原文核验
```

路由器返回 `status`、`authorization`、`route`、`steps` 和 `limitations`。
它本身不联网，也不直接调用搜索后端。

## 三种支持层级

下面的平台表使用三种输出标记：

- **统一候选包**：仓库内置适配器直接输出 schema `1.0`，包含候选、覆盖率、
  来源追踪和脱敏错误。
- **需后续适配**：计划中的后端结果必须再通过指定的内置适配器，才能变成统一候选包。
  X/Grok 属于这一类。
- **原生 CLI 计划**：路由器负责选择并限制外部 CLI，但本仓库不宣称其直接输出
  已经统一字段的候选包。

缺少某个可选 CLI 只会减少覆盖，不会自动安装、放宽私域访问、升级登录态，
或静默切换到另一个后端。

## 公开网页与 AI 发现

| 需求 | 选中路由 | 访问方式 | 输出 | 重要边界 |
|---|---|---|---|---|
| 最新 AI 新闻、发布、动态或日报 | `aihot_search.py` 调用 AI HOT | 匿名公共 API | 统一候选包 | items 最多覆盖近 7 天；聚合摘要或 AI 生成摘要只是发现线索。 |
| 通用网页、新闻、批量查询、`site:` 查询和法律/学术/金融/安全等垂直域 | `anysearch_adapter.py` 调用 AnySearch | 已有 AnySearch 运行时 | 统一候选包 | 展开后单批最多 5 个请求，每查询最多 10 条；失败时显式报告，不静默换后端。 |
| 明确枚举一个公开站点或文档目录下的链接 | `firecrawl_adapter.py` 调用 Firecrawl Map | 私密环境/文件中的 API Key | 统一候选包 | 最多 100 个公开、同源、位于种子路径范围内的链接；Map 不读正文，也不保证穷尽。 |
| 打开一条本轮 AnySearch 候选 | AnySearch Extract，或明确选择 Firecrawl Scrape | 有效的短期候选回执；Firecrawl 另需 Key | 富化后的候选包 | 只接受本轮搜索的完整、未篡改 candidate JSON，不接受裸 URL；打开页面不等于证明主张。 |

AI HOT 只在查询同时具有 AI 主题和明确时效意图，或用户直接点名 AI HOT 时使用。
普通 AI 概念、教程、历史和更长时间线调研仍走 AnySearch。Firecrawl 永远不是普通关键词
搜索的默认回退。

## 社媒与公开平台覆盖总表

| 平台 | 搜索对象 | 实际路由 | 登录态 | 有界上限 | 输出层级 |
|---|---|---|---|---|---|
| GitHub | 公开仓库 | `gh search repos --visibility public` | `gh` 可使用本机凭据访问公共 API | 1–50 条请求候选 | 原生 CLI 计划 |
| 知乎 | 公开关键词结果和显式热榜 | `zhihu_adapter.py` → 另行安装的 CLI 兼容运行时 | Keychain 管理凭据；结果标记为 `authenticated_public` | search 每词 10；batch 5 词；hot 30 | 统一候选包 |
| 微信公众号 | 跨公众号公开文章候选 | `opencli weixin search` 公开路由 | 匿名 | 第 1 页；1–50 条请求候选 | 原生 CLI 计划 |
| 微博 | 公开关键词博文候选 | `weibo_adapter.py`：先匿名移动端，再限定访问门回退 | 先匿名；符合访问门时才复用 Chrome | 3 页 / 20 条；batch 最多 5 词串行 | 统一候选包 |
| 小红书 | 公开笔记关键词候选 | `opencli xiaohongshu search` | 可在该有界公开只读路由内复用已有 Chrome 会话 | 一次一词，20 条，步骤间隔至少 5 秒 | 原生 CLI 计划 |
| 抖音 | 公开视频/帖子关键词候选 | `opencli douyin search` | 可在该有界公开只读路由内复用已有 Chrome 会话 | 一次一词，30 条，步骤间隔至少 5 秒 | 原生 CLI 计划 |
| 今日头条 | 当前公开非视频结果 | `opencli toutiao search` 专用匿名 profile | 匿名 | 一次一词，最多 50 条，1–30 天 | 原生 CLI 计划 |
| X / Twitter | 一个或多个聚焦查询的公开帖子 | Grok 原生 `x_search`，严格门控后备路由 | 先用 Grok OAuth；后续登录态回退默认禁用 | 每外层调用 20 条，1–7 天；Research 最多 40 次 + 1 轮补搜 | 需后续适配 |
| B站 | 公开视频候选 | `bili search` | 匿名优先 | 第 1 页；1–50 条请求候选 | 原生 CLI 计划 |
| YouTube | 公开视频或一个明确公开频道 | `youtube_search.py`：Data API v3 或匿名 `yt-dlp` | 环境中已有 API Key 时使用；否则不用登录 Cookie | 1–50 条；search/channel 两种模式 | 统一候选包 |
| 小宇宙 | 公开节目/页面关键词候选 | AnySearch `site:xiaoyuzhoufm.com` | 匿名公开网页 | 每查询 10 条 | 统一候选包 |

所有上限都是“本次调用的有界候选数”，不是对平台全量索引的承诺。搜索卡片中的
正文片段、作者、时间、互动量和排名都属于候选元数据，引用前仍需打开原始来源核对。

## 各平台详细说明

### GitHub

- 当前原生路由只搜索**公开仓库**。
- 查询放在 `--` 之后，防止查询文本被 `gh` 当成新的命令选项。
- 不宣称支持 code、Issue 或 Pull Request 对象搜索，不 clone，不修改仓库。

### 知乎

- 关键词搜索和显式热榜都通过内置白名单适配器，输出统一候选包。
- search 每查询最多 10 条，当前无分页和时间过滤；batch 最多产生 5 次独立搜索。
- hot 必须显式选择，最多返回 30 条当前排名快照。
- 另行安装的 CLI 兼容运行时在 macOS Keychain 管理 Access Secret；本仓库不独立
  核验该运行时的厂商来源。个人命令、收藏、关注列表和其他私域全部排除。

### 微信公众号

- 这里的“微信”只指跨公众号的公开文章发现，不是搜索个人微信、读取聊天、
  管理账号或进入公众号后台。
- 路由通过 OpenCLI 使用匿名公开搜索面。
- 绝不操控微信桌面端或移动端 UI。

### 微博

- 每个进程先建立一个只存在于内存中的临时匿名访客会话，访问公开移动搜索面。
- 只有明确的访问门失败，例如登录/验证重定向或访问被拒，才能触发一次复用已有
  Chrome 会话的有界只读 OpenCLI 搜索。网络错误、限流、普通解析错误和零结果都不会
  解锁这个回退。
- 单查询最多 3 页 / 20 条。batch 最多 5 个词，必须串行，步骤间隔至少 5 秒。
- `--days` 只对有界返回页做客户端时间过滤，不是服务端全量日期检索。不获取评论、
  个人主页和媒体；Cookie 值不进入适配器输入、输出或日志。

### 小红书与抖音

- 两条路由都只做公开关键词发现。它们可在这个狭窄的有界公开只读路由内自动复用
  已有 Chrome 会话。
- 每次只搜一个关键词，使用后台临时站点会话，完成后释放标签页，并且串行执行、
  步骤间隔至少 5 秒。
- 小红书最多 20 条，抖音最多 30 条。平台时间参数只允许 `0`、`1`、`7` 或 `180`
  天，但不代表严格时间覆盖，仍应核对返回的 `published_at`。
- 不包含发布、评论、点赞、收藏、关注、私信、私域 Feed/收藏夹、账号变更、验证码处理、
  媒体下载或评论展开。

### 今日头条

- 使用专用匿名 profile，不读取用户 Chrome 状态。
- 低频、单关键词搜索当前公开非视频结果，不自动重试。
- 路由器接受 1–30 天时间参数，单步骤最多 50 条。

### X / Twitter：Quick 与 Research

两种深度都从官方 Grok CLI 账号 OAuth 和原生 `x_search` 开始。Grok 结果必须通过
`grok_x_result_adapter.py`，只保留工具结构化 `matched` 时间验证桶中的帖子。

| 模式 | 适用场景 | 执行方式 | 停止条件 |
|---|---|---|---|
| Quick | 少量聚焦查询 | 每个 `--query` 各调用一次外层 `search_x_with_grok`；每次最多 20 条 | 执行完指定查询，或主路由发生任何故障 |
| Research | 更广、可审计的 X 覆盖 | 至少 3 个互不重复的聚焦查询；每波最多 5 个；离线合并并按 `tweet_id` 去重 | 达到目标、无实质缺口、补搜无新增、已用 1 轮补搜、达到 40 次上限，或主链发生非额度故障 |

时间窗口只支持 1–7 天。Repost/Reply、作者、语言、互动阈值和排序参数会指导检索，
但离线合并器只能重新筛选候选中真实存在的结构化字段。缺失数据保持未知，不从自然语言
摘要推测。

后备链是明确不对称的：

1. 始终先用 Grok 原生 `x_search`。
2. 只有输出明确证明 Grok 账号额度或使用上限耗尽，才允许进入匿名 FxTwitter。
3. FxTwitter 也失败或零结果时，默认停止。
4. OpenCLI/xreach 可能使用本机 X 会话，默认禁用；只有用户在当前任务明确授权后，
   才能用 `--login-approved` 重新生成计划并放行。

未登录、401/403、权限错误、超时、网络/服务错误、无法验证搜索证据和零结果都不是
“额度耗尽”，不得解锁后备链。

### B站

- 原生路由通过 `bili` 搜索公开视频，从一个有界结果页返回候选 URL 和元数据。
- 不下载视频、音频、字幕或评论，不读取账号数据。

### YouTube

- `search` 搜索公开视频；`channel` 把一个明确的 handle、channel ID 或频道 URL 作为公开发现容器。
- 环境中已有 `YT_BROWSE_API_KEY` 或 `YOUTUBE_API_KEY` 时，可用 Data API v3 做频道解析、
  时间控制和排序。
- 否则使用匿名 `yt-dlp`，强制忽略用户配置、插件、缓存和登录 Cookie，只传入最小非凭据
  环境，并始终使用 `--skip-download`。
- 两条路由都输出统一候选包，最多 50 条。匿名路由不保证所有 API 级排序选项。

### 小宇宙

- 当前 OpenCLI 没有可用的全站关键词路由，因此使用 AnySearch 执行
  `site:xiaoyuzhoufm.com`。
- 结果会被标准化，但它只是公开网页索引视角，不是小宇宙原生完整索引。

### 平台批量搜索的例外

知乎和微博支持最多 5 个独立原生适配器调用。其他具名平台在 `--mode batch` 下会被
明确改写成 AnySearch `site:` 查询。这种公开网页索引适合跨关键词发现，但不等于平台原生全量搜索。

## 快速上手

只有 Skills 没有安装在默认目录时，才需要覆盖父目录：

```bash
export YICHEN_SKILLS_ROOT="$HOME/.agents/skills"
```

先生成离线计划，不调用任何搜索后端：

```bash
python3 "$YICHEN_SKILLS_ROOT/yichen-unified-search/scripts/route_search.py" \
  --query "最新公开 AI 模型发布" --platform auto --limit 10
```

常见平台示例：

```bash
# 微博公开候选；只对最多 3 页有界结果做本地时间过滤
python3 "$YICHEN_SKILLS_ROOT/yichen-unified-search/scripts/route_search.py" \
  --query "iPhone 18" --platform weibo --days 30 --limit 20

# 显式读取知乎热榜快照
python3 "$YICHEN_SKILLS_ROOT/yichen-unified-search/scripts/route_search.py" \
  --query "知乎热榜" --platform zhihu --mode hot --limit 30

# 小红书公开只读关键词计划
python3 "$YICHEN_SKILLS_ROOT/yichen-unified-search/scripts/route_search.py" \
  --query "AI 硬件" --platform xiaohongshu --days 7 --limit 20

# 一个明确的公开 YouTube 频道
python3 "$YICHEN_SKILLS_ROOT/yichen-unified-search/scripts/route_search.py" \
  --query "@channelHandle" --platform youtube --mode channel --limit 20

# 有界 X Research；至少提供 3 个互不重复的聚焦查询
python3 "$YICHEN_SKILLS_ROOT/yichen-unified-search/scripts/route_search.py" \
  --platform x --depth research --days 7 --limit 20 \
  --target-results 100 --max-searches 8 \
  --query "主题 官方发布" \
  --query "主题 独立评测" \
  --query "主题 开发者失败报告"

# 显式同源站点 Map：只列链接，不读正文
python3 "$YICHEN_SKILLS_ROOT/yichen-unified-search/scripts/route_search.py" \
  --query "https://example.com/docs/" --platform web --mode site-map --limit 100
```

只执行计划中实际生成的 `steps`。完整命令形状和路由门槛见
[`references/routes.md`](references/routes.md)。

## 安装与按需依赖

将本目录放在关联 Skills 旁边：

```text
~/.agents/skills/
  anysearch/
    runtime.conf
  yichen-content-archive/
  yichen-unified-search/
  yichen-web-research/
```

Python 适配器除可选 `idna` 外只使用标准库。`idna` 用于加强 UTS #46 主机名验证；
非 ASCII 主机在缺少该依赖时会 fail closed。

只安装实际要使用的路由依赖：

| 路由 | 可选外部运行时/配置 |
|---|---|
| 通用/垂直网页与小宇宙 | AnySearch 与 `anysearch/runtime.conf` |
| 站点 Map 或 Firecrawl 候选 Scrape | Firecrawl API Key |
| 知乎 | 另行安装的知乎 CLI 兼容运行时 |
| 微信公众号、小红书、抖音、今日头条与微博条件回退 | OpenCLI 与对应公开/会话能力 |
| GitHub | `gh` |
| X | Grok CLI 与 `yichen-grok-consult`；`xreach` 只能用于当前任务授权后备路由 |
| B站 | `bili` |
| YouTube | `yt-dlp`，或已有 YouTube Data API v3 Key |

仓库不捆绑任何外部可执行文件、浏览器状态、凭据或 API Key。

## 候选包与核验

内置标准化器统一输出 schema `1.0`：

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

每个候选都保留真实平台、真实后端、URL、排名、已有元数据、访问状态、核验状态、
来源追踪和局限。未知值保持 `null`，不伪造为 `0`，也不从摘要推测。完整字段见
[`references/candidate-schema.md`](references/candidate-schema.md)。

### “2 小时 HMAC 候选回执”到底是什么

AnySearch 每条搜索候选会带一个短期签名，绑定本次 run ID、candidate ID、URL、原查询、
检索时间和过期时间，默认有效期两小时。后续打开原文时，只接受带有有效回执的完整、
未篡改 candidate JSON。

讲人话：它用来防止任意 URL 或以前保存的 URL 被伪装成“本轮搜索结果”。它只证明
**这条链接最近确实由本轮适配器搜到**，不证明网站本身真实、不证明页面中的主张，也不会
自动把 `verification.status=candidate` 变成 `verified`。

## 只读与隐私边界

- 只做公开或已认证公开内容发现；不搜索私人收藏、书签、Feed、群组、通知、私信、草稿或后台。
- 不发布、评论、点赞、收藏、关注、私信、删除、修改账号或处理验证码。
- 不下载媒体、不归档页面、不建持久数据库、不建 watchlist、不定时监控、不无界重试。
- 绝不操控微信桌面端或移动端 UI。本 Skill 中的微信只指匿名公开公众号文章发现。
- 已有 Chrome 状态只能用于文档明确列出的小红书、抖音和条件微博有界路由；Cookie 值不进入命令参数、候选包或日志。
- 登录墙、验证码、权限错误、额度耗尽、网络失败、解析失败或后端不可用都会显式报告，不会静默扩大范围或自动安装工具。
- 搜索卡片和摘要只是候选。要引用的事实必须打开原始来源核对。

## 校验

在仓库根目录执行：

```bash
python3 -m unittest discover -s yichen-unified-search/tests -p 'test_*.py'
python3 -m compileall -q yichen-unified-search/scripts yichen-unified-search/tests
python3 yichen-web-research/scripts/validate_family.py
```

离线测试覆盖路由、标准化、HMAC 回执、URL 验证、有界回退、脱敏和公开发布合同。
`validate_family.py` 负责检查与相关调研 Skills 的集成。

第三方归属见
[`references/THIRD_PARTY_NOTICES.md`](references/THIRD_PARTY_NOTICES.md)。
