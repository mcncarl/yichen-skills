---
name: yichen-web-research
description: 逸尘自用的互联网研究总入口。用于跨平台且跨阶段、用户尚未确定工具，或明确要求对公司、产品、人物、技术、行业和领域做横纵分析、发展史加现状对比或有来源约束的系统深度研究；先生成有截止日期和证据闸门的计划，再把搜索发现、候选核验、有限归档、按需转写和证据综合路由到 yichen-unified-search、yichen-content-archive、yichen-bookmarks-export 与 yichen-asr。若用户只要求搜索、只处理已知链接、只导出私人收藏或只转写已有音视频，应直接使用对应子 Skill。Use when an internet-research request spans multiple stages, requires evidence-grounded longitudinal and cross-sectional synthesis, the correct child route is unclear, or the user explicitly invokes $yichen-web-research.
---

# 逸尘互联网研究

这是用户自有的研究路由层，不是 OpenCLI、AnySearch 或任何单一 CLI 的包装。底层后端可以替换，用户意图和安全边界保持稳定。

## 何时使用总入口

仅在以下情况使用本 Skill：

- 请求跨越两个以上阶段，例如“先搜索，再选出并归档来源”。
- 请求跨越多个平台且不止搜索，还需要候选确认、归档、转写或后续分析。
- 用户只描述研究目标，尚未指定搜索、归档或收藏导出。
- 需要先体检多个后端，再决定安全可用路线。
- 用户明确要求横纵分析、发展史与当前格局交叉、竞品或行业全景，以及有来源约束的系统深度研究。

单一明确动作直接路由：

单阶段搜索无论涉及一个还是多个平台，都直接进入 `$yichen-unified-search`；“跨平台”本身不是触发总路由的充分条件。

| 用户意图 | 目标 Skill |
|---|---|
| 横纵分析、发展史 + 当前格局、证据账本、交汇洞察或三情景深度研究 | `$yichen-web-research` |
| 关键词搜索、批量发现、平台站内搜索、候选核验，或显式有界的站点 URL Map | `$yichen-unified-search` |
| 已知 URL、URL 文件、已确认候选或明确容器的读取、下载、归档（含 X Post、Quote、Article） | `$yichen-content-archive` |
| 导出小红书、抖音或 X/Twitter 的私人收藏与书签链接 | `$yichen-bookmarks-export` |
| 已有音视频的字幕、ASR、口播粗剪或内容分析 | `$yichen-asr` |

## 固定流程

```text
研究目标
  -> yichen-unified-search
  -> 标准候选清单
  -> 是否由用户明确要求归档且范围已经限定？
       ├─ 否：返回候选，或继续获准的原文核验与分析
       └─ 是：yichen-content-archive
              -> 按需交给 yichen-asr、视觉分析或知识库 Skill
```

仅在用户明确要求归档且范围已限定时进入 `$yichen-content-archive`。搜索结束后不得自动归档或下载；收藏导出结束后也不得自动读取正文或下载媒体。归档与下载都需要独立、明确的当轮请求。

## 横纵研究模式

只有任务同时需要历史演进、当前横向结构和综合判断时才进入本模式。单个事实查证、搜索候选、已知链接读取或快速总结不得为了显得深入而扩展成横纵研究。

触发后完整读取 [references/hengzong-research.md](references/hengzong-research.md)，并按下列顺序执行：

1. 建立研究 brief，固定 `subject`、`goal`、`object_type`、`subtype`、`as_of`、`start_date`、`geography`、`audience` 和 `languages`。这些 key 必须出现；未知值保持 `unknown`，不得猜测。`start_date`、`geography`、`audience`、`languages` 是 scope keys，任一为 `unknown` 都进入不可保留的 scope gap，并阻止正式报告就绪。
2. 联网前运行纯离线计划器：

   ```bash
   python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-web-research/scripts/plan_hengzong_research.py" --brief -
   ```

3. 只有 `coverage_dimensions.query_group_matrix.status=ready` 时，才把计划中各 workstream 的 `query_groups` 交给 `$yichen-unified-search`。`query_text` 必须是可直接搜索的自然语言，不得把 `facet:`、`axis:`、`search_language:`、`time_scope:` 或 `evidence_intent:` 伪装成搜索操作符。每个已知地区和语言都要形成有界覆盖；只有 subject 与 geography 都可靠本地化时才能标为 `localization_status=native`，否则保留原文并输出 localization gap。
4. 搜索 envelope 只是候选交接包。只有打开原文并逐主张核对后才标为 verified；搜索摘要、AI 摘要、排名和 `opened_original=true` 均不能单独证明事实。
5. 只有用户明确要求持久化原文或下载媒体，且范围已限定时，才通过 `$yichen-content-archive` 的独立安全门。搜索完成本身绝不转移归档授权。
6. 写作前把 canonical plan、绑定同一 `plan_id` 与 workstream 的 envelopes、来源 annotations、原子 claims 和 retained gaps 组成 bundle，运行纯离线整理器：

   ```bash
   python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-web-research/scripts/assemble_hengzong_evidence.py" --bundle -
   ```

7. 只有 `scope_complete`、逐 workstream 基础 claim、非空 timeline、非空 cross-sectional matrix、逐地区/语言 coverage、矛盾处理、横纵交汇和三情景等结构门全部满足时才写正式报告。任何 `supports`/`contradicts` link 都必须含 `locator`、`event_date` 和 `scope`；`notes` 可选但提供后必须保留。缺少必填 link 字段的输入是 `invalid_bundle`，不是可披露 gap；缺少 `published_at` 的来源不具 temporal eligibility。
8. 普通缺口输出 `blocking`。只有真实的 coverage/claim gap 已执行至少两条结构化补搜，且每条 `query_or_path` 与 `route` 均彼此不同，并提供 `impact`、`disclosure`、`bounded_conclusion`，才可输出 `ready_with_disclosure`；retained disclosure 不得豁免任何结构门。固定 1–3 万字不是完成标准，完成度只由范围、证据与结构闸门决定。

`start_date` 之前的材料默认越界；只有明确标为 `pre_scope_context` 时才可作为透明前史保留，且不能计入 claim、coverage、timeline、交汇、情景或机会地图的证据资格。任何决策原因只允许 `explicit`、`supported_inference` 或 `unknown`；每条横纵交汇必须可回溯为 `past_event -> present_effect -> implication`。三情景必须包含 `horizon`、可观察 `triggers` 与 `invalidators`，不得编造概率。

行业研究的 `goal` 含未来、机会、机遇、前景或对应英文意图时，计划与报告必须包含非空 `opportunity_map`；其 evidence basis 必须绑定 ready claim IDs 并同时覆盖纵向与横向基础 claim。指定两种交付语言时，`report_contract` 必须把双语输出设为硬要求。

本模式基于、受启发并扩展 KKKKhazix/khazix-skills 的 `hv-analysis`，作者为数字生命卡兹克，固定参考上游提交 `7a5c4934be4106ac740ffdb95280bb81b3f4b83c`。完整归属与 MIT 许可见仓库根目录 `THIRD_PARTY_NOTICES.md` 及 `licenses/KKKKhazix-khazix-skills-LICENSE.txt`。

## 后端定位

- AnySearch：公共网页、批量搜索、垂直搜索和搜索候选的轻量原文核验。
- Firecrawl：只作显式的有界站点 Map，以及当前 AnySearch 候选的单页 Scrape 回退；不进入默认搜索链，也不声明支持 Crawl 或归档。
- 知乎 CLI 公开搜索：只作显式 `zhihu` 平台后端，由 `$yichen-unified-search` 的白名单适配器调用另行安装的 Open Platform CLI 兼容运行时进行公开站内搜索或显式热榜发现；本仓库不独立核验该运行时的厂商来源，并且不替换 AnySearch 的普通网页搜索。`global_search`、知乎直答（`zhida`/`answer`）与 `me` 账号命令不进入总路由。
- Twitter/X：关键词搜索交给 `$yichen-unified-search`，固定 Grok CLI 原生 `x_search` 优先；已知 X URL 交给 `$yichen-content-archive`，固定匿名 FxTwitter → Jina 优先。
- 平台原生 CLI/API：GitHub、YouTube、B站等结构化公共搜索。
- OpenCLI：仅作为部分平台的只读适配器，不是本体系的强制依赖或总入口。
- 本地平台 Skill：已知链接解析、媒体下载、公众号正文和批量归档。
- 浏览器或账号登录态：小红书、抖音的有界公开只读搜索，以及微博匿名访问门失败后的一次有界只读回退，可按子 Skill 的固定范围和限速规则自动复用现有会话；其他登录态读取按具体目标取得当轮授权。

不得因为某个后端已安装或浏览器已登录，就绕过子 Skill 的范围、限速和高风险授权门。

## 安全边界

1. 所有社交平台保持只读：不发帖、不评论、不点赞、不收藏、不关注、不私信，不改变账号状态。
2. 绝对不得操控微信桌面端或移动端 UI；不得发消息、发布、编辑、创建草稿、删除、群发或关注。
3. 小红书、抖音的有界公开只读搜索，以及微博匿名访问门失败后的一次有界只读回退，可自动复用现有 Chrome 登录态，无需逐次授权；必须遵守子 Skill 的单关键词、条数上限、串行与间隔规则。小红书最多 20 条，抖音最多 30 条，必须串行且请求间隔不少于 5 秒。发帖、评论、点赞、收藏、关注、私信、删除、账号变更、验证码处理以及私域读取必须停下，并由用户当轮明确提出和授权。
4. 私人收藏、书签、Feed 和账号后台数据必须取得当轮对具体平台与范围的明确授权；授权不可转移到下载。
5. 匿名公开路线优先。不得绕过验证码、登录墙、付费墙、限流、地区限制或访问控制。
6. 不打印或保存 Cookie、Token、API Key、登录凭证及敏感 URL 参数。
7. 不覆盖既有产物，不自动删除临时文件。任何清理都必须先获得用户明确允许，并且只能移入废纸篓。
8. 付费 API 或可能产生显著额度消耗的批量转写，在执行前说明范围和预计数量。
9. ASR 自动路由在任务提交后不得跨服务商重提；余额未知时不得表述为充足或不足。
10. Firecrawl Map 必须固定公开站点和输入路径，最多 100 条，只保留同源且位于输入路径范围内的公开 URL；默认禁止子域、外域、登录态、交互动作和持续监控。Map 只产生候选，不能自动跨过确认门进入归档。Scrape 只用于带有效短期回执的当前 AnySearch 候选，不扩展为 Crawl 或归档。
11. Firecrawl API Key 只从 `FIRECRAWL_API_KEY` 或 `${FIRECRAWL_KEY_FILE:-$HOME/.config/agent-secrets/firecrawl-api-key}` 读取；doctor 只根据环境变量是否非空，或私有文件的类型、owner、权限和大小报告是否存在，不输出密钥值、不读取凭据文件内容，也不发起网络或计费探针。
12. 知乎 CLI 兼容运行时只允许经统一搜索适配器暴露公开 `search`/`hot` 能力；不得暴露 `global_search`、`zhida`/`answer` 或任何 `me` 私人命令。doctor 只运行离线 `version`、`capabilities`、`auth status` 元数据检查，子进程使用最小环境白名单，只报告 Keychain 是否配置，不透传 stdout、stderr 或 Secret，也不发送搜索或热榜请求。

## 多后端体检

跨平台或登录态任务开始前运行：

```bash
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-web-research/scripts/doctor_yichen.py"
```

OpenCLI 相关任务再运行：

```bash
opencli doctor
```

体检只证明后端和安全契约可识别。它不授权任何写操作或私人数据读取；有界公开只读会话复用是否允许，以当前子 Skill 的固定范围和限速规则为准。

知乎通道缺少配置的 CLI 运行时或 Keychain 认证时只报告 `warn`，不把整个研究家族误判为结构损坏；统一搜索侧 `zhihu_adapter.py` 缺失才属于结构错误。该通道固定 `default_backend=false`、`network_probe_performed=false`、`public_commands_only=true`、`personal_commands_exposed=false`。

## 交接约定

搜索层至少交接：

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

归档层只接收用户已知链接、已确认候选或明确的有限容器；收藏层只输出链接文件和不可转移授权状态。各子 Skill 的当前 `SKILL.md` 与 references 是执行事实源。

## 唯一入口与子 Skill 调用

- 本 Skill 是唯一的互联网研究总入口，不保留旧名称兼容入口。
- 横纵研究是本总入口的一种显式研究协议，不新增兼容入口，也不改变 `$yichen-unified-search` 的候选搜索职责。
- 用户显式调用 `$yichen-web-research` 时，先按上表判断任务阶段；需要子 Skill 时，必须完整读取对应当前文件后再执行：
  - `${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/SKILL.md`
  - `${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-content-archive/SKILL.md`
  - `${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-bookmarks-export/SKILL.md`
  - `${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-asr/SKILL.md`
- 子 Skill 是独立的执行规则，不是可递归调用的函数。路由后直接按目标 Skill 执行，目标 Skill 不得再回到本总入口。
- 若子 Skill、必要后端、登录态或额度不可用，如实报告具体缺口；不得把“已经正确路由”表述成“外部平台必然成功”。
