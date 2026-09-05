---
name: yichen-unified-search
description: 统一编排关键词驱动的公共网页、AI 最新动态、垂直领域和社交平台搜索，返回标准化候选；支持有界 X Research、显式站点 Map，以及本次搜索所得候选的轻量核验。不用于读取或下载用户直接给出的已知 URL，此类任务使用 yichen-content-archive。
---

# 逸尘统一搜索

按“确定范围 → 离线路由 → 执行候选搜索 → 标准化与核验”处理任务。保留用户指定的平台、关键词和时间，不把候选当成已核实事实。

## 固定边界

- 只处理当轮目标所需的公开内容。不发帖、评论、点赞、关注、私信或改变账号状态；不读取、同步或搜索私人收藏、书签、个人 Feed、群组、通知、私信、草稿或后台。
- 绝对不得操控微信桌面或移动端 UI。公众号只走匿名公共搜索。
- 不下载媒体、不归档、不建长期数据库、不运行定时监控。用户给出已知 URL、URL 文件或要求读取/下载/归档已确认候选时，交给 `$yichen-content-archive`，传递动作、范围和输出位置，并重新确认动作与范围；搜索不授予下载、私域、登录态或费用权限。
- 不绕过验证码、登录墙或风控。以下明确列出的只读登录态路线以外，不升级账号访问。后端失败与零结果分开报告；未知字段保留 `null`。
- 查询和候选 URL 会发送给计划指定的服务。不得包含密码、Cookie、个人数据、商业秘密或其他敏感内容；凭证处理与各服务的数据流见 [访问与凭证边界](references/access-boundaries.md)。

## 离线路由

下文 `SKILL_DIR` 指本 Skill 的安装目录，`YICHEN_SKILLS_ROOT` 指同级 Skills 根目录；使用前按实际安装位置设置并导出这两个变量。

```bash
python3 "${SKILL_DIR}/scripts/route_search.py" \
  --query "检索词" --platform auto --mode search --limit 10
```

路由器不联网。执行前检查 `status`、`authorization`、`steps` 和 `limitations`。`invalid_request` 无可执行步骤，CLI 退出码为 2；依据提示在已授权范围内调整参数，不把它当成零结果。范围清楚时直接执行，不要求用户逐项重复确认。

| 目标 | 路线与使用方式 |
|---|---|
| 普通网页、概念/教程、批量关键词、垂直领域 | AnySearch；`anysearch_adapter.py` 输出统一 envelope，垂直域先发现子域与全部必填参数 |
| AI 主题且具有新闻/最近/发布意图 | AI HOT 精选；明确“日报”才用日报，明确“全部”才用全量 |
| 指定平台站内搜索 | 平台意图优先于 AI HOT；使用计划中的平台适配器 |
| 多平台或多个关键词 | 每个原始查询必须有执行或拆分记录，不能丢弃；不同平台意图返回 `query_routes`，按平台拆分并显式传 `--platform` |
| 公开站点链接枚举 | 仅显式 `--mode site-map`，Firecrawl 最多 100 条同源且位于种子路径范围内的候选，不读正文 |
| 本次搜索所得候选核验 | 默认 AnySearch；仅显式 `--verify-backend firecrawl` 才用 Firecrawl |

“微博公司财报”是搜索对象，不等于微博站内搜索。自动识别有歧义时，根据当前任务直接显式选择平台；只有无法判断用户意图时才询问。普通 `issue` 不触发 GitHub 路线。

- YouTube、GitHub、B站、公众号、小红书、抖音、头条、小宇宙的原生 `search` 一次只接收一个查询；多查询应分别运行，或明确选 `batch` 使用公共 `site:` 索引。知乎和微博有各自的显式原生 batch；X Quick 支持重复 `--query`。具体能力见 [路由契约](references/routes.md)，单查询限制集中在 `scripts/search_policy.py`。
- AI HOT items 最多 7 天；路由器同时检查自然语言和显式 `--days`，后者优先。超过范围的自动请求走 AnySearch，显式 AI HOT 报范围错误。多主题最多 5 个，适配器分别检索、合并去重并记录 `matched_topics` 与逐主题 coverage。数量不足或主题失败必须如实交付。日期、日报与滚动窗口不同，严格时间任务还需核对原文时间。
- AnySearch 通用路线不直接落实 `--days`，必须在查询中保留时间范围，交付前核对日期。长窗口转到 AnySearch 不代表已完成确定性日期筛选。
- URL 仅在用户明确要求搜索其引用/讨论时作为 `--input-kind url-seed`；不读取种子本身。站点 Map 和明确 YouTube 频道浏览是发现容器例外；普通已知 URL 仍交归档层。

## 执行与核验

1. 根据路由读取 [references/routes.md](references/routes.md) 中对应后端的参数与限制；不要默认加载全部平台细节。X、多后端或登录态路线先运行 `${YICHEN_SKILLS_ROOT}/yichen-web-research/scripts/doctor_yichen.py`；OpenCLI 路线再运行 `opencli doctor`。命令存在不等于可用，不回调总路由 Skill。
2. 只执行计划中的后端。AnySearch 使用 `anysearch_adapter.py`（读取现有 runtime.conf），AI HOT 使用 `aihot_search.py`，知乎使用 `zhihu_adapter.py search|hot`，微博使用 `weibo_adapter.py search --session-mode auto`，YouTube 使用 `youtube_search.py`；不复制 CLI、硬编码代理或 Key。
3. AI HOT、AnySearch、显式 Firecrawl 不可用时报告错误，只有用户同意后才改换公共网页后端。已有明确登录态例外见下一节；不要扩大例外。
4. 按 [candidate-schema.md](references/candidate-schema.md) 交接候选、routes、coverage、errors。非空原始结果无法解析必须记为错误；保留真实后端、原始 URL、时间限制和登录态。AI HOT 异常条目计入 rejected_count，全部异常为 failed，部分异常为 partial，不能冒充成功零结果。
5. X 按 tweet_id、再 canonical URL 去重；其他平台按 URL 去重，并保留命中查询与来源。标题/作者/时间均高度一致才合并近重复；互动量不能证明事实。
6. 搜索卡片、AI HOT 的 AI 摘要都只是线索。最终引用前打开原文核验具体主张。本轮 AnySearch 核验必须向 `anysearch_adapter.py verify --candidate-from-search` 提供带有效 HMAC 回执的完整 candidate JSON 或 `@file`；明确选择 Firecrawl 时交给 `firecrawl_adapter.py scrape`。不接受裸 URL 或自行拼接候选，打开页面本身也不等于事实核验。

## 登录态与 X Research

- 小红书、抖音：允许有界公开只读搜索自动复用现有 Chrome 会话；后台临时会话、一次一个关键词、串行且间隔至少 5 秒，单次分别最多 20/30 条。不复制或输出 Cookie。
- 微博：临时匿名访客会话优先，仅访问门失败后自动执行一次有界 OpenCLI 只读搜索；网络错误不触发回退。每次最多 3 页、最多 20 条，批量最多 5 次且串行间隔至少 5 秒。
- 知乎只走另行安装的 Open Platform CLI 兼容运行时 与其 Keychain，不接收 Secret。B站、YouTube、微信公众号、头条、小宇宙先匿名，登录限定时停止。
- X 一律先官方 Grok CLI OAuth + 原生 `x_search`。只有明确额度耗尽才能转 FxTwitter；随后失败或零结果才进入 OpenCLI → xreach，使用浏览器登录态前按工具要求取得当轮授权。未登录、401/403、超时、网络、服务错误和主链零结果都不能当成额度耗尽。
- X Quick 每个查询独立调用，单次最多 20 条、1–7 天。`--depth research` 至少 3 个独立聚焦查询；只执行当前 ready 波次，归一化并合并后才解锁后续波次。最多 40 次外层搜索、最多补搜一轮，达到目标、预算耗尽、无缺口、补搜无新增或主链非额度故障时停止。详见路由契约的 X 节。
- 每次 Grok 输出必须经过 `grok_x_result_adapter.py`，只映射 `<x_post_time_verification>.matched`，排除 `excluded_outside_window`，然后用 `x_research_merge.py`。Grok `criteria` 只是检索约束；作者、语言、互动阈值和转评类型只对实际结构化字段筛选，缺失时保留未知，不能声称已验证。

X 的浏览器回退默认关闭。只有取得当轮明确授权后才传 `--login-approved`；路由器据此设置 `allow_authenticated_fallback=true`，未授权时保持 false。知乎路线使用 `zhihu-open-platform-cli`，Keychain 认证访问公开内容并标记 `authenticated_public` / `login_state_used=true`；不以官方身份背书。

## 交付

返回 `{schema_version, request, routes, candidates, coverage, errors}`。用户只要答案时用 Markdown 展示精选结果，保留相同字段语义。说明各平台覆盖、失败、截断、日期与登录态限制，不宣称穷尽或把候选当事实。上游许可见 [THIRD_PARTY_NOTICES.md](references/THIRD_PARTY_NOTICES.md)。
