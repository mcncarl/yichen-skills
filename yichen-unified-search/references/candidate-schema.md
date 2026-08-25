# 候选结果交接结构

把所有后端结果映射到同一个 envelope。未知值使用 JSON `null`，不要用空字符串或 `0` 伪造。

## Envelope

```json
{
  "schema_version": "1.0",
  "request": {
    "queries": ["example"],
    "platforms": ["web"],
    "time_range": null,
    "requested_limit": 10
  },
  "routes": [
    {
      "platform": "web",
      "backend": "anysearch",
      "mode": "search",
      "login_state_used": false,
      "status": "completed",
      "limitations": []
    }
  ],
  "candidates": [],
  "coverage": [],
  "errors": []
}
```

## Candidate

```json
{
  "candidate_id": "web:stable-source-id-or-url-hash",
  "query": "example",
  "platform": "web",
  "backend": "anysearch",
  "rank": 1,
  "title": "Result title",
  "url": "https://example.com/item",
  "canonical_url": "https://example.com/item",
  "snippet": "Search-result snippet, not verified body text.",
  "author": null,
  "published_at": null,
  "content_type": "web_page",
  "language": null,
  "metrics": {
    "likes": null,
    "comments": null,
    "collects": null,
    "shares": null,
    "views": null
  },
  "access": {
    "visibility": "public",
    "login_state_used": false
  },
  "verification": {
    "status": "candidate",
    "opened_original": false,
    "checked_at": null
  },
  "provenance": {
    "source_id": null,
    "retrieved_at": "2026-01-01T00:00:00+08:00",
    "route_reason": "public_web_default"
  },
  "limitations": []
}
```

## X 多查询合并扩展

`x_research_merge.py` 读取多个 schema 1.0 envelope 后仍输出 schema 1.0。合并后的 `request` 在通用字段外增加 `source_requests`、`filters` 和 `sort`；若各输入时间窗不同，则 `time_range=null` 并增加 `time_ranges`。它们描述实际输入与离线 reducer 参数，不代表 X 已验证所有约束。

Grok `search_x_with_grok` 的文本结果必须先交给 `grok_x_result_adapter.py`：它验证 completed native `x_search`，只读取 `<x_post_time_verification>.matched` 中的 URL、`tweet_id`、作者 handle 和解码时间并映射成 X candidate，同时写入 `grok_time_verification_bucket=matched` 与 `grok_native_x_search_verified=true`；`excluded_outside_window` 只计入 coverage，永远不得进入 envelope。合并器会拒绝缺失这一 provenance 闸门的 `backend=grok-consult` 候选。Grok 未结构化返回的正文、互动量、语言和 Reply/Repost 类型继续为 `null`/未知，不得从自然语言描述猜值。

同一候选命中多个查询时，用 `queries` 与 `provenance.merged_sources` 保留检索来源，而不是只留下获胜候选的单个 `query`：

```json
{
  "candidate_id": "x:1234567890",
  "query": "主题 官方发布",
  "queries": [
    "主题 官方发布",
    "主题 独立评测"
  ],
  "provenance": {
    "tweet_id": "1234567890",
    "merged_sources": [
      {
        "input_index": 1,
        "candidate_index": 3,
        "candidate_id": "x:1234567890",
        "backend": "grok-consult",
        "rank": 3,
        "queries": ["主题 官方发布"],
        "provenance": {}
      }
    ]
  },
  "platform_fields": {
    "x_research_merge": {
      "identity_type": "tweet_id",
      "tweet_id": "1234567890",
      "repost_status": "unknown",
      "reply_status": "false",
      "engagement_formula": "likes + reposts + replies",
      "engagement_components": {
        "likes": 10,
        "reposts": null,
        "replies": 2
      },
      "engagement_score": 12
    }
  }
}
```

- `queries`：该候选在所有输入 envelope 中命中的去重查询集合；`query` 为兼容字段，不得用它覆盖 `queries`。
- `merged_sources`：每次输入观察的索引、原候选 ID、真实后端、原排名、查询与原 provenance。合并数值指标时取各观察中已知最大值，并在限制说明中标明发生过合并。
- `provenance.tweet_id`：只有确实从结构化 source ID、candidate ID 或 status URL 解析到稳定 ID 时才写；否则按 canonical URL 去重并保持为 `null`/缺失。
- `repost_status`、`reply_status`：只允许 `true/false/unknown`。默认只排除明确为 `true` 的候选；`unknown` 保留并附限制说明，不能冒充已确认非 Repost/Reply。
- `engagement_score`：仅为离线排序值。公式中的未知分量按 0 参与排序，但原始 `metrics` 和 `engagement_components` 继续为 `null`；不得因此声称缺失互动量是 0。

合并器追加如下 coverage 统计；原输入 envelope 的 coverage 也继续保留：

```json
{
  "platform": "x",
  "backend": "x-research-merge",
  "input_envelopes": 30,
  "input_candidates": 600,
  "unique_candidates": 520,
  "duplicate_observations_merged": 80,
  "unknown_repost_status": 25,
  "unknown_reply_status": 40,
  "filtered": {
    "reposts": 5,
    "replies": 8,
    "author": 0,
    "language": 0,
    "min_likes": 0,
    "min_reposts": 0,
    "min_replies": 0,
    "min_views": 0
  },
  "sort": "relevance",
  "requested_limit": 500,
  "eligible_before_limit": 507,
  "returned": 500,
  "truncated": true,
  "login_state_used": false,
  "limitations": []
}
```

`unique_candidates` 是筛选和 `--limit` 前的去重数量；`eligible_before_limit` 是确定性筛选后的数量；`returned` 才是最终交付量。`filtered` 逐项记录淘汰原因，互动阈值对应字段缺失时也计入该阈值的淘汰数。该 coverage 只证明离线合并过程，不证明原文真实性、搜索穷尽性或缺失字段。

## 字段规则

- `candidate_id`：使用平台稳定 ID；没有稳定 ID 时使用 canonical URL 的哈希。不要把排名当 ID。
- `platform`：使用 `web/github/wechat/weibo/xiaohongshu/douyin/toutiao/zhihu/x/bilibili/youtube/xiaoyuzhou` 等稳定枚举。AI HOT 是聚合后端而不是原始平台，因此 AI HOT 候选写 `platform=web`、`backend=aihot`。
- `backend`：记录真实执行后端，不写笼统的“搜索引擎”。
- `rank`：保留单次后端返回顺序；合并后不要据此宣称全网热度。
- X Research 合并后的 `rank` 是指定离线排序下的最终顺序；`provenance.merged_sources[*].rank` 才保留各输入后端的原排名。
- `canonical_url`：只移除明确的临时追踪参数；无法判断时与原始 `url` 相同。
- `published_at`、`retrieved_at`、`checked_at`：使用带时区 ISO 8601；相对时间无法可靠换算时保留在 `limitations`，时间字段为 `null`。
- `metrics`：后端未返回即为 `null`；明确返回零才写 `0`。
- X 的 `metrics.shares` 映射 repost 数，`metrics.comments` 映射 reply 数，`metrics.collects` 映射 bookmark 数；FxTwitter 额外返回的 quote 数可保存在 `metrics.quotes`。
- X 普通推文、引用推文和 Article 分别使用 `x_post/x_quote_post/x_article`。FxTwitter 的引用对象及 Article 标题、预览、封面只放在 `platform_fields.quoted_post` 与 `platform_fields.article`，不得把 Article `content.blocks` 混入搜索候选。
- `verification.status`：只允许 `candidate/verified/excluded`。只有真实打开原文并核对关键主张后才写 `verified`。
- AI HOT 的 `source/title_en/category/daily_date` 放入 `platform_fields.aihot`；其 `summary` 只映射到 `snippet`，默认保持 `candidate`，不得把 AI 生成摘要当作原文证据。
- 知乎关键词搜索和显式热榜必须经 `zhihu_adapter.py`归一化，写 `platform=zhihu`、`backend=zhihu-open-platform-cli`。由于配置的 CLI 运行时使用 Keychain 凭证，route/candidate/coverage 必须写 `login_state_used=true`，candidate 写 `access.visibility=authenticated_public`。search 使用 `content_type=zhihu_<cli-content-type-lowercase>`，热榜能从 URL 稳定判断时写 `zhihu_question`/`zhihu_article`，否则写 `zhihu_hot_item`；`provenance.route_reason` 分别为 `zhihu_cli_search` 或 `zhihu_cli_hot_list`。CLI 搜索返回的标题、摘要、作者、赞同数、评论数、`AuthorityLevel` 和 `RankingScore` 都只是搜索 candidate 元数据；不得因其声明兼容 Open Platform 就写 `verification.status=verified`或 `opened_original=true`。
- 知乎 search 的 `platform_fields.zhihu` 可保留 `content_id`、CLI 返回的 `content_type`、`updated_at`、`authority_level`、`ranking_score` 和 `featured_comments`；热榜保留 `hot_rank`，只有适配器完成公开 HTTPS URL 校验时才可保留 `thumbnail_url`。这些字段都不得代替原文核验。
- 知乎 search 单查询最多 10 条，batch 最多 5 个独立调用；当前 no pagination 且 no time filter。coverage 必须标明这两项限制，不得把返回数量写成站内全量。热榜只由显式 `mode=hot` 生成，最多 30 条。
- 微博关键词搜索必须经 `weibo_adapter.py` 的 `weibo-readonly-auto` 契约归一化，写 `platform=weibo`、`candidate_id=weibo:<post_id>`、`content_type=weibo_post`。匿名候选的真实 `backend=weibo-public-anonymous`、`provenance.route_reason=public_weibo_anonymous_search`、`access.visibility=public`、`login_state_used=false`；访问门失败后一次 OpenCLI 只读回退的真实 `backend=weibo-opencli-readonly`、`provenance.route_reason=public_weibo_readonly_browser_fallback`、`access.visibility=authenticated_public`、`login_state_used=true`。搜索卡片的正文片段、作者、时间和互动数仍只是 candidate 元数据，必须保持 `verification.status=candidate` 与 `opened_original=false`。
- 微博 `platform_fields.weibo` 只保留对应搜索结果明确返回的 `post_id/user_id/source/created_at_raw/verified/followers_count/picture_count/has_video`；浏览器结果没有返回的字段保持 `null`，不得猜测。两条路线都不保存临时图片或视频 URL，不获取评论、个人主页或媒体；未返回的互动字段写 `null`，只有明确数值零才写 `0`。
- 微博单查询最多 3 页/20 条，batch 最多 5 个独立调用且必须串行、步骤间至少间隔 5 秒。临时匿名访客会话只驻留当前进程内存；OpenCLI 浏览器回退只允许一次有界 `weibo search` 并直接管理现有 Chrome 会话。适配器不接收、输出或持久化 Cookie 值。coverage 必须记录实际后端、页数、拒绝/重复/时间未知/时间窗外数量及实际 `login_state_used`；`--days` 是有界返回页上的客户端过滤，不得描述成服务端日期检索或完整站内覆盖。
- AnySearch `search/batch_search` 必须经 `anysearch_adapter.py` 归一化。只有上游明确返回 `Search Results (0 results, ...)` 时才允许 `status=completed` 且候选为空；非空输出无法解析、数量不符或批次缺段必须写 `parse_error`，并标记 `partial/failed`。
- AnySearch 适配器为每个 search/batch candidate 写入 `provenance.anysearch_receipt`：版本、run ID、过期时间和 HMAC-SHA256 签名。默认有效 2 小时，并绑定 candidate ID、URL、query、检索时间和过期时间；它只证明候选来自近期适配器搜索，不证明正文事实。不得手工生成、复制到其他 URL 或移除后继续核验。
- AnySearch `extract` 只能由适配器核验或轻量富化本次搜索 envelope 中已有且回执有效的完整 AnySearch candidate；正文写入 `platform_fields.anysearch.extract_markdown`，读取时间写入 `extract_retrieved_at`，并在 `provenance.verification` 保留原始查询、candidate ID、实际后端和检查时间。打开原文后写 `opened_original=true`，但仅打开页面不足以证明主张，`verification.status` 仍保持 `candidate`。不得把用户直接给出的 URL 临时塞入候选后调用。
- Firecrawl Map 只在显式 `site-map` 模式产生候选：`backend=firecrawl`、`query` 为种子 URL、`provenance.route_reason=explicit_site_map`、`provenance.map_seed_url` 保留种子。适配器只输出公共 HTTP(S)、与种子同源且路径位于种子范围内的链接；Map 没有读取正文，候选必须保持 `opened_original=false` 与 `verification.status=candidate`。
- Firecrawl Scrape 不产生一个伪造的新搜索来源；它保留原 AnySearch candidate 的 `backend=anysearch` 与有效 `provenance.anysearch_receipt`，把 Markdown 写入 `platform_fields.firecrawl.scrape_markdown`、读取时间写入 `scrape_retrieved_at`，并在 `provenance.verification.backend=firecrawl` 记录实际核验后端。只打开页面仍保持 `verification.status=candidate`。
- Firecrawl Scrape 固定 `formats=[markdown]`、`storeInCache=false`、`proxy=basic`、`skipTlsVerification=false`，不传 actions、页面 headers、cookies 或 `zeroDataRetention`。`storeInCache=false` 不得被描述为绝对零数据保留或已启用 ZDR。
- `visibility`：只允许 `public/authenticated_public`；本 Skill 不产生 private 候选。
- `coverage`：逐后端记录查询数、返回数、截断、时间筛选、登录态和已知索引限制；X 多查询合并另记录输入 envelope 数、输入/唯一/重复数量、未知类型状态、逐项筛除数和最终返回数。
- `errors`：保存可公开的错误类别和影响；不得记录 Cookie、Token、Key、完整认证响应或敏感查询。

## 去重与核验

1. X 先按稳定 `tweet_id` 合并，缺失时按 canonical URL；其他平台先按 canonical URL 去重。
2. 保留所有命中查询与来源 provenance，不用单一获胜记录覆盖多查询证据。
3. 仅在标题、作者和发布时间均高度一致时合并近重复内容，并保留所有 provenance。
4. 把搜索摘要视为线索，不作为正文引文。
5. 对最终引用候选打开原文；无法访问则保留为 candidate 或排除，不根据摘要补写事实。
