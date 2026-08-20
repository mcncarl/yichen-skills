# 横纵研究协议

横纵研究把“沿时间解释如何走到今天”和“在同一时间截面解释当前结构”组合成可核验的研究流程。它是 `yichen-web-research` 的规划与证据综合协议，不是新的搜索后端，也不改变各子 Skill 的授权边界。

本协议基于、受启发并扩展 KKKKhazix/khazix-skills 的 `hv-analysis`，作者为数字生命卡兹克，固定参考上游提交 `7a5c4934be4106ac740ffdb95280bb81b3f4b83c`。完整归属和 MIT 许可见仓库根目录 `THIRD_PARTY_NOTICES.md` 与 `licenses/KKKKhazix-khazix-skills-LICENSE.txt`。

## 目录

1. [触发边界](#1-触发边界)
2. [研究 brief](#2-研究-brief)
3. [规划与证据脚本](#3-规划与证据脚本)
4. [纵向与横向 workstream](#4-纵向与横向-workstream)
5. [查询组与范围覆盖](#5-查询组与范围覆盖)
6. [来源与逐主张核验](#6-来源与逐主张核验)
7. [日期、范围与决策逻辑](#7-日期范围与决策逻辑)
8. [用户口碑采样](#8-用户口碑采样)
9. [Claim-source ledger](#9-claim-source-ledger)
10. [横纵交汇、机会与三情景](#10-横纵交汇机会与三情景)
11. [停止闸门](#11-停止闸门)
12. [子 Skill 交接](#12-子-skill-交接)

## 1. 触发边界

满足下列任一条件时进入横纵研究：

- 用户明确要求“横纵分析”“深度研究”“发展史 + 现状对比”或同义任务。
- 问题同时要求历史演进、当前竞争或结构，以及机会、风险或未来判断。
- 对象是公司、产品、人物、协议、项目、机构、行业、赛道或知识领域，单次事实查询不足以回答目标。
- 结论需要把过去事件与当前格局建立可追溯联系，而不是只汇总资料。

以下情况不触发：

- 单个事实、当前状态、价格、日期或定义查证。
- 单平台或多平台的单阶段搜索、候选发现或轻量核验。
- 已知链接、已确认候选或明确有限容器的读取与归档。
- 单篇文档总结、已有音视频转写、私人收藏链接导出。
- 用户只要快速答案，且未要求历史、横向结构或情景推演。

不触发时直接进入对应子 Skill，不为追求篇幅而扩展范围。

## 2. 研究 brief

检索前必须规范化下列字段。所有 key 都必须出现；无法确认的范围字段写 `unknown`，不得猜测：

| 字段 | 要求 |
|---|---|
| `subject` | 对象规范名称，以及必要别名、旧名或同名消歧。 |
| `goal` | 要回答的问题或支持的判断；不能只写“全面了解”。 |
| `object_type` | `entity` 或 `industry`。 |
| `subtype` | 实体可为 `company`、`product`、`person`、`protocol`、`project`、`institution` 等；行业可为 `market`、`sector`、`category`、`ecosystem`、`policy_domain` 等。 |
| `as_of` | 当前截面截止日，格式 `YYYY-MM-DD`。 |
| `start_date` | 纵向窗口起点，格式 `YYYY-MM-DD`；不明时为 `unknown`。 |
| `geography` | 一个地区用字符串，多个地区用字符串数组；每个已知值都形成覆盖义务。 |
| `audience` | 报告读者、知识水平与决策场景。 |
| `languages` | 检索与交付语言；一个值用字符串，多个值用字符串数组。 |

可以补充研究问题、排除项、来源限制、时间或费用预算和交付形式。`object_type`、`subtype`、`goal`、`as_of` 或范围实质变化时，旧计划失效，必须重新规划。

`start_date`、`geography`、`audience`、`languages` 是 scope keys。任一为 `unknown` 时，planner 必须在 `coverage_dimensions.gaps` 记录对应维度。Assembler 将其输出为没有 `gap_key`、`retained=false` 的 `kind=scope` gap，并令 `gates.scope_complete=false`；scope gap 不能通过 retained disclosure 豁免。

## 3. 规划与证据脚本

### `plan_hengzong_research.py`

- 在 brief 完整后、任何网络检索前读取其契约并运行。
- 将 brief 转为纵向和横向 workstream、`query_groups`、来源优先级、覆盖维度、停止条件和报告契约；计划本身不是证据。
- `plan_id` 绑定 canonical plan。执行器不得接受只复制 ID、正文已经变化的计划。
- 对象类型、目标、截止日、时间窗或地域变化时重新运行。
- 证据证明切面选择错误时可以修订，但必须保留原因，不能迁就现有材料而静默改题。

从仓库根目录运行：

```bash
python3 yichen-web-research/scripts/plan_hengzong_research.py --brief brief.json
```

### `assemble_hengzong_evidence.py`

- 在候选已完成原文核验、证据已进入 ledger 后，正式写作前读取其契约并运行。
- 组装来源、时间线、横向矩阵、矛盾项、覆盖缺口、横纵交汇、机会地图、三情景和停止闸门。
- 新增关键证据、解决矛盾或调整 material claim 后重新运行。
- 只整理输入的结构化证据；不联网、下载、自动归档，也不把候选摘要升级为事实。
- Bundle 必须提供与 canonical plan 一致的 `plan_id`。每个 envelope 的 `research_context` 必须匹配同一 `plan_id` 和所属 `workstream_id`；来自查询组时，其 `query_group_id` 也必须属于该 workstream。任何漂移都 fail closed。

从仓库根目录运行：

```bash
python3 yichen-web-research/scripts/assemble_hengzong_evidence.py --bundle bundle.json
```

## 4. 纵向与横向 workstream

### 4.1 实体纵向

按目标选择并排序，不机械覆盖全部：

1. 前史、需求、技术、制度和人物背景。
2. 成立、首次发布或首次提出的可核验节点。
3. 产品、技术、商业模式或组织演进。
4. 融资、收入、用户、合作、并购等规模节点。
5. 团队、治理、战略和市场定位变化。
6. 监管、诉讼、危机、失败与重大争议。
7. 转折点、当时约束及其路径依赖。

按 `event_date` 重建因果，不把新闻发布日期排成流水账。

### 4.2 实体横向

以 `as_of` 为统一截面，选择直接竞品、间接替代、技术路线、产品形态、用户场景、商业模式、定价、渠道、单位经济性、团队、治理、资本、生态依赖、用户口碑、监管与执行风险等。

没有直接竞品时解释品类边界、替代方案、进入壁垒和潜在竞争方向，不硬凑名单。候选过多时按代表性而非知名度选取，并说明纳入和排除理由。

### 4.3 行业纵向

1. 萌芽条件与最早可核验形态。
2. 阶段划分及阶段转换判据。
3. 政策和监管周期。
4. 技术范式、成本曲线与基础设施变化。
5. 供需、用户认知和渠道变化。
6. 资本周期、集中度与商业模式演变。
7. 危机、标杆兴衰和跨界玩家进入。
8. 驱动力的替换、增强或衰减。

每个阶段都要有起止依据、关键事件和可观察转折条件，不能只用事后命名。

### 4.4 行业横向

候选切面为 `value_chain`、`segments`、`business_models`、`players`、`regions`、`users`、`regulation`、`capital`。显式指定时选择 3–5 个；未指定时由 planner 按 `goal` 确定性选择，并在 `classification.horizontal_selection.selection_reason` 说明原因。

每个入选切面必须满足：

1. **目标相关**：会改变目标对应的判断。
2. **可比**：对象、区域或方案有共同口径。
3. **可证**：存在可追溯来源、指标或观察。
4. **重要**：实质影响竞争、供需、机会或风险。
5. **非重复**：提供独立解释力。
6. **截面一致**：尽量接近 `as_of`；口径或年份不同必须标明。

切面不可证时替换或降级为 gap，不用印象填充。固定 3–5 个是行业显式选择约束，不是要求所有研究机械凑数。

## 5. 查询组与范围覆盖

每个 workstream 都必须有自己的 `query_groups`。每组继承 `workstream_id`，并记录 group ID、地域、语言、查询问题和来源意图。

- `query_text` 必须是可直接提交搜索的自然语言短语，并吸收 facet 的问题和来源路径。禁止把 `facet:`、`axis:`、`search_language:`、`time_scope:`、`evidence_intent:` 等内部元数据伪装成搜索操作符。
- 双语 subject 选择对应语言片段；常见中英地理名双向本地化。只有 subject 和 geography 都可靠本地化时，group 才能标为 `localization_status=native`。
- subject 无法本地化时保留原文，并记录 `subject_localization_status` 与 `localization_gap`；geography 无法本地化时保留原文，并记录 `geography_localization_status` 与 `geography_localization_gap`。不得把未翻译查询标成 native。
- 多地区时每个已知地区至少进入一个定向 group；多语言时每种语言至少进入一个对应语言 group。地域和语言均多值时，为每个“地区 × 语言”组合建立有界 group。
- 每个 workstream 最多 64 个 group；超过上限先缩小 brief，不转为无界笛卡尔积。
- `source_annotations.geographies` 与 `source_annotations.languages` 记录来源实际覆盖，不能从域名或标题猜测。
- 每个 workstream 的每个已知地区和每种已知语言，至少需要一条 temporal-eligible verified source。Assembler 输出 `dimension_counts`、`required_dimensions` 和 `missing_dimensions`。
- 一个地区或语言的证据不得外推为其他已知范围。缺失维度必须成为 blocking gap，或在满足严格 retained 条件后成为报告可见的有限缺口。
- 未知 scope key 不生成虚构值；其中未知 geography/languages 不生成虚构 group、annotation 或 coverage 值，只保留不可豁免的 scope gap。

## 6. 来源与逐主张核验

来源按与原始事实的距离分级：

| 等级 | 典型来源 | 用途与边界 |
|---|---|---|
| `L0` | 法律法规、监管文件、法院文书、公司申报、审计报告、官方统计、原始数据集 | 关键法律、财务、主体和事件事实；仍需核对范围与口径。 |
| `L1` | 当事方公告、产品文档、论文、演讲、访谈、定价页、版本记录 | 证明当事方做了什么或说了什么；不能单独证明自我评价或市场效果。 |
| `L2` | 有方法说明的研究、数据库、行业报告、可靠媒体独立报道 | 交叉核验、估算和第三方观察；尽量追溯原始数据。 |
| `L3` | 论坛、社交媒体、应用商店评论、社区帖子、聚合页、转载、搜索摘要 | 发现线索和口碑主题；不能自动升级为事实或总体结论。 |

核验单位是主张，不是“段落里有一个链接”：

- 每个 material claim 都进入 ledger，并绑定支持、反驳或背景来源。
- 决定性事实优先 `L0`/`L1`，并尽量加入独立来源；高风险或争议主张至少两条独立证据线。
- 数字保留统计期、单位、币种、地域、样本和定义；不同口径不得直接计算。
- 引用链尽量回到原始材料；不能回溯时标记 `secondary_only`。
- Coverage 的 `independent_sources` 只统计 `source_role=independent` 的第三方来源，并按 `independence_group` 去重。
- `supported_inference` 要求至少两个不同 `independence_group` 的 eligible supporting evidence lines，不要求都为 `source_role=independent`；不同主体的一手记录可以构成两条证据线。
- 已知转载、同一新闻稿或复用同一底层数据集必须归入同一 `independence_group`。URL、标题或媒体品牌数量不等于独立来源数。
- 搜索摘要、AI 摘要和候选卡片只用于发现；`opened_original=true` 也不能替代逐主张核验。
- 否定主张必须记录检索范围，不能把“未找到”写成“已证明不存在”。
- 官方与独立来源冲突时记录口径和未决部分，不默认偏信任一方。

## 7. 日期、范围与决策逻辑

每条事件证据至少区分：

- `event_date`：事件实际发生或生效日期。
- `published_at`：来源公开发布或更新日期。
- `as_of`：报告允许使用的当前截面，必须等于 canonical plan 的截止日。
- `start_date`：纵向主窗口起点。
- `retrospective`：来源晚于 `as_of` 但回顾更早事件时显式为 `true`。
- `pre_scope_context`：claim、evidence link 或 source annotation 的事件早于已知 `start_date` 时显式为 `true`。
- `in_scope`：Assembler 根据事件是否处于时间窗内输出，不由作者自行扩大。

时间线按 `event_date` 排序，来源新鲜度按 `published_at` 判断。规则如下：

- Claim 的 `as_of` 必须等于 plan；claim 和 evidence link 的 `event_date` 不得晚于 `as_of`。
- `source_annotations.published_at` 缺失时，来源 `temporal_eligible=false`，不能计入 coverage 或 claim 支持。
- `published_at` 晚于 `as_of` 的来源只有在 `retrospective=true` 时可透明保留，仍不得计入 as-of coverage 或 material claim。
- 已知 `start_date` 时，早于起点的 claim 或 evidence link 默认 `invalid_claim`。只有准确设置 `pre_scope_context=true` 才可保留为前史；对窗口内事件错误设置该值同样无效。
- Pre-scope 内容输出 `in_scope=false`、`eligible_evidence=false`，不得计入基础 claim、timeline、cross-sectional matrix、交汇、情景或 opportunity map。
- 只有年月或日期有争议时保留粒度或候选区间，不补造具体日。

决策原因只允许：

- `explicit`：可归责的一手来源明确说明原因并可定位。
- `supported_inference`：至少两条独立证据线支持的推断；列出证据链、假设与替代解释。
- `unknown`：证据不足或冲突；直接说明未知及其影响。

## 8. 用户口碑采样

用户口碑只说明“被采样用户如何描述体验”，不是总体市场真相。采样前固定平台、时间窗、语言、地域、查询词、纳入规则和目标样本量：

- 只读获准范围内的公开内容或当轮明确授权的私人范围；绝不操控微信。
- 按帖子、评论或评测唯一标识去重，识别转载、营销、返利、机器人和同一作者重复发言。
- 同时采集正面、负面和中性场景，不只搜索预设结论。
- 报告样本数、独立作者数、平台与时间分布和缺失，不用样本占比冒充总体发生率。
- 分开编码功能事实、个人体验、传闻和情绪；`L3` 产品事实回到更高等级来源核验。
- 只总结反复出现且有代表性原例的主题；低频但严重的问题单列，不使用超出样本的“普遍认为”。

## 9. Claim-source ledger

Ledger 规范化为 `claims`、`sources` 和 `evidence_links`，保留多对多关系。

### `claims`

| 字段 | 含义 |
|---|---|
| `claim_id` | 稳定唯一 ID。 |
| `statement` | 单一、可判断真假的原子主张。 |
| `claim_type` | `fact`、`decision_logic`、`cross_insight` 或 `scenario`。 |
| `basis` | `explicit`、`supported_inference`、`unknown` 或 `not_applicable`。 |
| `workstream_ids` | 所属 workstream；交汇与情景同时引用纵横轴。 |
| `event_date`、`as_of` | 事件日与判断截面。 |
| `pre_scope_context`、`in_scope` | 前史声明与整理器输出的窗口状态。 |
| `evidence` | 关联来源及 relation、locator、日期与 scope。 |
| `cross_link` | 交汇主张的 `past_event`、`present_effect`、`implication`。 |
| `scenario` | 标签、horizon、起点、因果路径、触发信号、反证条件和影响。 |
| `contradiction_resolution` | `resolved` 或 `retained_uncertainty` 及理由。 |

Claim 状态固定为 `ready`、`ready_with_uncertainty`、`retained_with_disclosure`、`insufficient`、`unknown` 或 `contested`。`contested` 表示尚未处理的已核验反证；不要使用未定义的 `contradicted`。Claim 状态与报告级 `ready`、`ready_with_disclosure`、`blocking` 不得混用。

### `sources`

| 字段 | 含义 |
|---|---|
| `source_id` | 稳定唯一 ID。 |
| `title`、`publisher`、`url` | 来源身份与规范链接。 |
| `source_tier` | `L0`–`L3` 或 `unknown`。 |
| `source_role` | `primary`、`authoritative`、`independent`、`community`、`aggregator` 或 `unknown`。 |
| `publisher_kind` | 法规发布者、公司、数据库、媒体、社区等。 |
| `published_at`、`retrieved_at` | 发布或更新日及本次取得时间。 |
| `independence_group` | 转载、同一数据或同一当事方的去重组。 |
| `geographies`、`languages` | annotation 明示的实际覆盖。 |
| `retrospective`、`pre_scope_context`、`temporal_eligible` | 回顾性、前史声明与截止日资格。 |

### `evidence_links`

| 字段 | 含义 |
|---|---|
| `claim_id`、`source_id` | 连接主张和来源。 |
| `relation` | `supports`、`contradicts` 或 `context_only`。 |
| `locator` | 页码、章节、表格、段落或时间戳；只保留必要短摘录。 |
| `event_date` | 证据所指事件日期。 |
| `scope` | 地域、对象、统计期、样本、单位和定义。 |
| `notes` | 可选的口径、推断或冲突说明；提供后必须原样保留。 |
| `pre_scope_context`、`in_scope` | 前史声明和整理器输出的窗口状态。 |

每条 `supports` 或 `contradicts` link 都必须有非空 `source_id`、`relation`、`locator`、`event_date`、`scope`；`notes` 可选。`context_only` 不计支持强度。缺字段、日期越界或前史状态错误会使 CLI 返回 `invalid_bundle`，不是可以 retained 的证据 gap。

## 10. 横纵交汇、机会与三情景

每条核心交汇必须在 ledger 中形成：

```text
past_event -> present_effect -> implication
```

- `past_event` 来自 eligible 的纵向节点。
- `present_effect` 在 `as_of` 横向截面可观察。
- `implication` 写明适用条件、受益或受损对象与不确定性。

至少构造 `most_likely`、`danger`、`optimistic` 三个可区分情景：

| 字段 | 要求 |
|---|---|
| `horizon` | 推演截止日期或时间跨度。 |
| `starting_conditions` | 与当前证据一致的起点。 |
| `causal_path` | 从关键变量到结果的因果链。 |
| `triggers` | 可观察、可跟踪的先行信号。 |
| `invalidators` | 足以否定或重写情景的事实。 |
| `implications` | 对目标、对象和关键相关方的影响。 |

没有可解释模型或基准时不编造概率；出现 invalidator 后重做推演。

Assembler 必须从 `brief.object_type` 与 `goal` 独立推导 opportunity requirement，并与 plan 和 `report_contract` 的三处声明保持一致。行业 goal 含未来、机会、机遇、前景或对应英文意图时，`opportunity_map` 必须非空且通过 `opportunity_map_ready`：

`report_contract` 必须显式要求非空 `opportunity_map`；三情景不能替代该独立报告结构。

- 每项含唯一 `opportunity_id`、`opportunity`、`historical_driver`、`current_condition`、`evidence_basis`、`beneficiaries`、`constraints`、`leading_indicators`、`invalidators`。
- `evidence_basis` 只绑定 in-scope ready claim IDs，并同时覆盖至少一个纵向和一个横向基础 claim。
- 不能把 optimistic scenario 政名后充当机会地图。

指定两种交付语言时，必须建立双语报告契约：`report_contract.language_requirements.delivery_languages` 必须同时列出两种语言并设为硬要求。两种版本的关键主张、数字、限定语和引用保持等义；双语检索与双语交付不能互相替代。

## 11. 停止闸门

每轮检索后检查 coverage、gap 和 contradiction。

### Coverage

- `scope_complete` 必须为 true；未知 start_date/geography/audience/languages scope gap 不可 retained。
- 每个 workstream 至少一个 in-scope `ready` 基础 claim（`fact` 或 `decision_logic`）。
- 每个 critical 问题有已核验主张或明确为 unknown。
- 每个已知地区和语言达到逐 workstream temporal-eligible verified source 要求。
- `views.timeline` 至少一个窗口内纵向基础 claim；`views.cross_sectional` 至少一个窗口内横向基础 claim。
- 核心结论、交汇、机会和情景起点能回指 ledger。

### Gap

- 每个缺口记录缺什么、为何重要、已尝试路径、下一步与剩余影响。
- `retained_gaps` 只匹配真实的 `coverage:{workstream_id}` 或 `claim:{claim_id}`；scope gap 没有 `gap_key`，不得 retained。
- 每项 retained gap 必须含 `gap_key`、`impact`、`disclosure`、`bounded_conclusion` 和至少 2 条结构化 `search_attempts`。
- 每条 attempt 含非空 `query_or_path` 与 `route`；各条 query/path 彼此不同、route 也彼此不同。同一查询换写法或同一路由重复调用不能凑数。
- 两条不同定向补搜后仍不可得，才保留 unknown 并约束结论；不得用低等级材料填空。

### Contradiction

- 冲突来源分别入账，不平均不兼容数字，不静默挑选。
- 检查时间、定义、地域、样本、主体和来源独立性。
- 无法解决的重大冲突保持 `contested`，正文披露其影响。

报告级停止状态只有：

- `blocking`：任一不可豁免结构门失败，或关键缺口尚未完成合格定向补搜。
- `ready_with_disclosure`：所有结构门通过，剩余真实 coverage/claim gap 满足严格 attempts、impact、disclosure 和 bounded conclusion。
- `ready`：关键结论可追溯，重大缺口和冲突已解决或不影响结论。

不可豁免门包括 canonical plan 绑定、`scope_complete`、所有 supports/contradicts link 的 locator/date/scope、逐 workstream 基础 claim、非空 timeline、非空 cross-sectional matrix、横纵交汇、三情景，以及适用时的 opportunity map 与双语 report contract。Pre-scope 内容不能帮助通过这些门。

Retained disclosure 只改变“已尽合理检索但仍不可得”的 coverage/claim gap 状态；它不改变结构契约。任一结构门失败仍为 `blocking`。

固定 1–3 万字不是完成标准。完成度取决于问题覆盖、证据质量、矛盾处理和结论可追溯性；篇幅不能弥补缺口。

## 12. 子 Skill 交接

```text
完整 brief
  -> plan_hengzong_research.py
  -> bounded workstreams、query_groups 与覆盖目标
  -> yichen-unified-search
  -> 标准候选清单与轻量核验
  -> 是否由用户明确要求归档且范围已经限定？
       ├─ 否：进入获准的原文核验与 claim-source ledger
       └─ 是：yichen-content-archive（只处理该范围）
              -> claim-source ledger
  -> assemble_hengzong_evidence.py
  -> 时间线、横向矩阵、交汇、机会、情景与停止状态
```

- `yichen-unified-search` 负责多查询发现、去重、候选级核验与缺口补搜；候选不等于证据。
- `yichen-content-archive` 只接收用户明确要求归档的已知链接、已确认候选或原请求明确限定的公开容器。确认候选可用不等于要求归档。
- 搜索结束后不得自动归档、下载或读取私人范围。只有用户当轮明确要求并限定范围，或随后明确要求归档具体候选，才可越过安全门。
- `yichen-bookmarks-export` 的私人数据授权、`yichen-asr` 的付费与跨服务商规则保持独立，不能由计划、候选或 assembler 输出转移。
- 归档不是完成研究的必选步骤；可凭已核验原文和可追溯 locator 完成 ledger 时，避免不必要持久化。
