---
name: x-article-draft-uploader
description: 将 Obsidian 或本地 Markdown 文章上传到 X/Twitter Articles 草稿；支持 Markdown pipe 表格转成 X 原生表格块；如果文章最上方有图片，则按当前 X 界面提示的 5:2 封面图上传；如果没有封面图，则跳过封面区域，直接上传标题、正文、表格和正文图片，完成后提醒用户补一张 5:2 封面。X Article 当前实测正文最多 25 个媒体项，封面单独上传且不占正文名额；表格尺寸选择器当前最大 10 x 10。适用于用户要求上传、发布、保存 Markdown 到 X Article，尤其是需要复用 Chrome 登录态、使用独立 Playwright 浏览器、不接管用户当前浏览器，或旧脚本出现缺图、错位、MPH_MARKER、表格变纯文本等问题时。
---

# X Article Draft Uploader

## 许可与商业授权

本 Skill 仅允许个人学习、研究和非商业个人工作流使用。客户交付、付费产品或服务、
公司内部部署、市场打包、课程打包及其他商业用途，必须事先取得作者明确的书面授权。
申请商业授权请添加微信 `yichen365ai`，并在验证信息中备注 `商业授权`；收到明确书面
授权前不得商用。完整条款见同目录 [`LICENSE`](LICENSE)。该限制只适用于本 Skill，
不改变 Ailu 核心的 AGPL-3.0-or-later 许可；第三方材料继续适用各自许可证。

## 核心原则

只创建草稿。除非用户明确确认可以公开发布，否则不要点击 X 最终的 `发布` 按钮。

封面图必须按 X Article 当前界面提示的封面比例 5:2 准备；不要沿用旧的错误比例。

X Article 当前实测正文最多按 25 个媒体项处理，封面单独上传、不占这 25 个正文名额；`1 张封面 + 25 张正文图` 是有效边界。如果 dry-run 显示 `expected_body_images > 25`，不要打开 X、不要硬传第 26 张正文图；先生成只用于上传的临时 Markdown，把连续截图合并成长图，或把文章拆成多篇。原始 Markdown 不要为了上传压缩版而直接改坏。

X Article 当前支持原生表格块，但不能靠 rich HTML 粘贴 `<table>` 自动生成表格。脚本会把 Markdown pipe 表格替换成临时 `X_TABLE_MARKER_*` 占位符，正文粘贴后在占位符位置插入 X 原生表格块，再打开表格块的 Markdown 编辑器写入原始表格。最终校验必须在自动保存后刷新同一个草稿：表格数量必须精确相等，每张表的可见行列与规范化单元格文本矩阵必须和本地一致、不能是空表，同时铅笔编辑器读回的 Markdown 也必须一致；只读回弹窗源码不算成功。

X 当前表格尺寸选择器实测最大为 `10 x 10`。如果 dry-run 出现 `table_too_large`，不要打开 X；先拆表、压缩列数，或把大表转成图片/正文段落后再上传。

使用独立的 Playwright 浏览器会话，不要抢占用户当前正在用的 Chrome 窗口。可以复用 Chrome 登录态，但只通过私有的 Playwright cookie JSON 使用。

默认只新建草稿。只有用户当轮明确确认要覆盖某个准确的 X 草稿 URL 时，才可以使用
`--draft-url`，并同时传入 `--confirm-existing-draft-write`；该模式默认会清空这个草稿已有的
标题、正文、表格、正文媒体和封面。不得把任意 URL 传给该参数，也不得用它处理他人的草稿。

## 快速开始

1. 使用 Ailu 时，通过设置页“从 Chrome 导入 / 粘贴 JSON / 选择 JSON”准备 Cookie。
独立运行 Skill 时，如果 `~/.ailu/secrets/x/cookies.json` 不存在或登录态失效，再显式导出：

```bash
python3 ~/.agents/skills/x-article-draft-uploader/scripts/export_x_cookies_from_chrome.py \
  --output ~/.ailu/secrets/x/cookies.json
```

2. 正式碰 X 之前，先 dry-run 解析文章，确认可选封面、正文图数量、表格数量、图片文件存在性、正文结尾验收文本、`content_checkpoints`、`expected_compact_length`、`expected_compact_sha256` 和锚点。封面图推荐比例按当前 X 界面提示为 5:2：

```bash
python3 ~/.agents/skills/x-article-draft-uploader/scripts/upload_markdown_to_x_article.py \
  "/absolute/path/to/article.md" \
  --cookies-json ~/.ailu/secrets/x/cookies.json \
  --dry-run
```

如果 dry-run 的 `preflight.errors` 非空，必须立刻停止工作。不要打开 X，不要创建草稿，不要自动重跑。按错误类型处理：

- `missing_cover_file` 或 `missing_body_image`：先修复 Markdown 图片路径或缺失文件。
- `weak_image_anchor`：先在对应图片前补一行唯一、明确的说明文字。
- `image_count_mismatch`：先检查 Markdown 图片语法是否异常。
- `table_too_large`：先拆表、改成图片，或改写成正文段落；不要直接创建 X 草稿。
- `unsupported_raw_html`：把代码围栏外的 raw HTML 改成 Markdown；URI/email autolink 不在此限制内。
- `unsupported_remote_image`：先把 `http://`、`https://` 或 `//` 远程图片下载到本地，再改用本地路径。
- `unsupported_reference_image`：把 `![Alt][label]`、`![Alt][]` 或 `![Alt]` 改成 inline image 语法 `![Alt](path)`。

如果 dry-run 只有 `missing_leading_cover` 这类 warning，不要阻断上传。继续创建草稿，封面区域保持空白；上传完成后提醒用户：你这篇文章忘补封面图了，是否需要我帮你补一张 5:2 封面图？

如果 dry-run 出现 `body_media_limit_exceeded`，结果会直接显示正文图片总数和超出数量。必须先处理超限：优先把连续截图合并成长图，生成临时上传版 Markdown，再对临时版重新 dry-run；不要直接重跑正式上传。封面单独计算，不要因为已有 1 张封面就把正文错误压到 24 张。

3. 新建一篇干净的 X Article 草稿并上传：

```bash
python3 ~/.agents/skills/x-article-draft-uploader/scripts/upload_markdown_to_x_article.py \
  "/absolute/path/to/article.md" \
  --cookies-json ~/.ailu/secrets/x/cookies.json
```

脚本会输出这些结果文件：

- 草稿 URL：`~/.ailu/runs/x-article-draft-uploader/draft-url.txt`
- 校验结果 JSON：`~/.ailu/runs/x-article-draft-uploader/result.json`
- 最终截图：`~/.ailu/runs/x-article-draft-uploader/final.png`

## 操作流程

1. 使用本 Skill 自带的 `scripts/parse_markdown.py` 解析 Markdown。
2. 执行 preflight。正文图片文件、图片数量、图片锚点问题必须在打开 X 之前解决；缺少置顶封面只作为 warning，不阻断上传。
3. 核算正文媒体：`expected_body_images` 必须小于或等于 25，封面单独上传、不占正文名额。超过 25 张正文图时，先制作临时上传版，合并连续截图或拆分文章，并重新 dry-run 到 25 以内。
4. 核算表格：`expected_tables` 可以大于 0，但每张表必须在 `10 x 10` 以内。表格上传必须走 X 原生表格块，不要只粘贴 `<table>` HTML，也不要接受表格被压成普通文本。
5. 如果文章最开头的第一张图片存在，把它当作 5:2 封面图；如果文章不是以图片开头，不要自动挑正文图做封面，而是把所有图片按正文图处理。
6. 从原始 Markdown 中读取每张正文图前一行，作为图片插入锚点。图片必须按 Markdown 原始 destination 解析后的完整规范路径与 occurrence 定位，不能只按 basename 匹配；不同目录下的同名图片必须保持各自锚点。锚点以“用户最终看见的语义文字”比较：source 端规范化粗体、斜体、删除线、代码、Markdown 链接、autolink、转义、HTML entity、NFC、零宽字符和标题/列表/引用结构前缀，DOM 端只规范化已经渲染的可见文字，不能再次把字面 `*`、反引号或内部 `|` 当 Markdown 删除。段落末尾同行图片使用图片前完整且未截断的最近可见语义段；紧随其后的连续纯图片行自动跳过前一张图片标记并继承该语义段，用户不需要为了上传改写 Markdown。只接受语义全文相等，或 X 把连续非空行合并时 actual 以完整 expected 为后缀；禁止无约束双向 substring 或截断段落。语义相同的非相邻锚点必须在 preflight 阻断；连续图片可以共享锚点，但要靠 occurrence 与最终 DOM 顺序区分。锚点必须是正文里真实存在、相对唯一、长度足够的文字；不要使用代码围栏、空行、短横线、列表序号或过短文本。唯一例外是解析后 `block_index=0` 的正文图：这类图片必须形成正文媒体序列最前面的连续 `composer-start` 前缀，全部使用空锚点，通过真实编辑器首块与 occurrence/DOM order 定位；一旦出现普通 `after-anchor` 图片，后面不得再出现 `composer-start`。最终回读还必须确认这些图片前没有正文文本，不能拿已删除的 H1 当锚点。
7. 启动全新的 Playwright Chromium context，并添加 X cookies。
8. 打开 `https://x.com/compose/articles`，点击 `create`，记录新生成的 `/compose/articles/edit/...` URL。
9. 如果有封面图，通过封面区域的 file input 上传封面，然后点击 X 的 `应用`。如果没有封面图，直接跳过封面上传，保持封面区域空白。
10. 填写标题，并把 rich HTML 正文粘贴到 `[data-testid="composer"]`。正文里的 Markdown 表格位置此时会是临时 `X_TABLE_MARKER_*`。
11. 对每张表格按正文顺序处理：定位 `X_TABLE_MARKER_*`，删除占位符，点击 `插入 -> 表格`，选择对应行列，打开表格块右上角铅笔，把原始 Markdown 表格写入文本框，点击 `更新`。
12. 正文图片从后往前插入。每张图都按这个顺序处理：
   - 在当前编辑器里找到优先级最高的 anchor。
   - 点击该段落末尾。
   - 按 `End`，再按 `Enter`。
   - 通过 clipboard paste event 粘贴图片文件。
   - 等页面里检测到的 media count 增加后再继续下一张。
13. 轮询 X autosave 后，刷新同一个 `/compose/articles/edit/...` 草稿并重新读取；同 URL 的最终 reload 是权威硬门。autosave UI 只能观察真实保存状态节点（`#detail-header`、`role=status`、`aria-live` 或明确 save 标识），并绑定本轮 mutation epoch；事件游标必须使用单调递增的 sequence，不能使用会被裁剪的事件数组长度。事件流只记录对应 channel 自身的 token 或 `nodeInstance` 变化，且保存证据必须仍绑定当前 saved channel；优先接受本轮 `saving -> saved` 或同一保存节点 token 在 mutation 后改变。X 未改变“刚刚最后保存”文本时，只能接受该节点自身在 `observedAt > lastMutationAt` 后重挂载或从同 channel 的另一状态回到“刚刚保存”的证据，不能因无关 status 节点变化而重放旧 Saved。不能扫描整页文本，也不能把进入页面前的旧 `Saved` 当作证据。若 autosave UI 事件/`saveText` 没捕获到，不要立刻终止；只在同一草稿最终 reload 后标题、正文哈希与有序检查点、全部表格、封面、正文图片身份/数量/顺序/语义位置均严格通过时，才能以 `reload_persistence_fallback` 成功并记录 warning。封面上传后、正文粘贴后、表格刚更新后或图片刚粘贴后的瞬时 DOM/解码观测也可以延期为 warning；每次图片粘贴仍必须找到目标位置并让正文媒体总数精确增加 1，但瞬时 identity、anchor、runtime key、旧节点序列或 binding 观测不稳定时不提前中止，交由最终 reload 独立重算。最终 reload 后标题与正文精确码点长度、SHA-256、有序检查点、每张表的可见行列/非空规范化矩阵/Markdown 回读、封面源图、全部正文图片的源图身份、数量、occurrence、DOM 顺序和语义锚点必须全部通过；此时错图、少图、多图、旧节点丢失、错位或顺序破坏一律失败关闭。诊断 screenshot、autosave 文案和 runtime DOM key 不是核心持久化证据，缺失只记录 warning。

    正文图片按 composer 内媒体块精确计数，并把本地源图的 `visual-dhash-v1` 指纹、8 x 8 RGB/亮度样本、同源图出现序号、语义锚点与最终 DOM 顺序组合成 binding key。256-bit dHash 在 64-bit Hamming 半径内可直接匹配；若 X 重编码使距离落在 65 至 80 bit，只能在预期源图是全部不同源图中的唯一最近组、与第二近源图至少相差 16 bit、自然宽高比漂移不超过 3%时采用 dHash 自适应匹配。dHash 超过 80 或对平滑渐变不稳定时，只有 8 x 8 RGB 平均误差不超过 12%、亮度误差不超过 10%、亮度结构相关性至少 0.88（纯色低方差图除外），且样本仍唯一指向预期源图时，才能采用多信号共识。相同源图重复出现仍按 occurrence、anchor 与 DOM order 区分；允许 X 重编码导致刷新前后指纹不完全相等。正文 SHA 只能剥离已通过源图证据并在真实媒体根上绑定 binding key 的节点，不能仅凭 `aria-label` 与数量猜 section。封面使用同一严格/多信号视觉契约，但还必须从封面 file input 的有界祖先区域取证，且相对已验证的零封面状态只新增一张；若 X 托管封面触发 Canvas 跨域限制，只允许通过同一 Playwright 会话从 X 控制的 HTTPS 主机只读取回图片字节后计算相同证据。独立请求通道失败时，可以退回同一浏览器会话中的临时只读页面获取图片，但必须重新校验最终 HTTPS URL、X 允许主机、图片类型与 32 MiB 上限，并在取证后关闭临时页面；不能退化为只看数量或宽高比。结果 JSON 必须包含固定 `verification_contract=x-article-persistence-v1`、`persistence_verified=true` 及对应 `persistence_evidence`；任一最终持久化证据缺失或不一致都只能算 partial/失败，不能输出 `RESULT_OK True`，也不能对用户称上传成功。
14. 如果本次没有封面图，上传完成后明确提醒用户：你这篇文章忘补封面图了，是否需要我帮你补一张 5:2 封面图？
15. 如果运行失败但已经生成 `/compose/articles/edit/...`，不要立刻重跑。先查看 `~/.ailu/runs/x-article-draft-uploader/` 下的 `draft-url.txt`、`result.json` 和 `final.png`，确认是否只是校验误报或半成品草稿。需要删除重复草稿时，必须先问用户。

## 常见卡点

- 如果 X 跳转到 `/login`，说明登录态失效，重新导出 cookies。
- 如果文章不是以图片开头，不要停止，也不要自动挑正文图当封面。直接上传标题、正文、表格和正文图片，让封面保持空白；上传完成后提醒用户补一张 5:2 封面图。
- 如果 dry-run 发现缺图，立即修 Markdown 或移动图片；不要等脚本跑到 X 里面再炸。
- 如果正文媒体超过 25，优先制作临时上传版：合并连续截图、保留正文顺序、重新 dry-run 到 25 以内。封面单独上传、不占正文名额；不要把原文永久改成压缩版，除非用户明确要求。
- 如果 dry-run 发现 `expected_tables > 0`，确认每张表的 `rows` / `columns`；表格上传成功时结果 JSON 里会有 `inserted_tables`、`tableCount` 和 `tableDetails`。
- 表格成功上传后，结果 JSON 必须同时有 `visible_matrix_matches=true` 与 `readback_matches=true`；只有源码一致、可见表格为空或错位仍算失败。
- 如果最终截图里表格看起来只是用空格排版、没有网格线，说明不是 X 原生表格。不要判成功；必须让 `tableCount` 大于等于 `expected_table_count`。
- 如果 dry-run 发现 `weak_image_anchor`，在图片前补一行明确说明，例如 `Word 文档验收截图：`。不要让锚点落在 ` ``` `、`---`、列表编号或过短文本上。
- 如果正文第一张图紧跟会被抽取为标题的开篇 H1，不要要求用户为了上传改原文；脚本应把该图识别为 `composer-start`，从正文第一个真实文本块前插入，并在刷新后验证它仍位于所有正文文本之前。
- 如果 dry-run 发现 `reused_anchor`，必须先把非相邻图片前的说明改成彼此唯一；不要在模糊位置关系下创建 X 草稿。
- 如果一次运行失败后草稿箱出现半成品，先记录失败草稿 URL。不要无脑重跑制造更多重复草稿；需要清理时先问用户确认。
- 如果最终校验失败，但媒体数、标题、截图都看起来正确，先检查 `~/.ailu/runs/x-article-draft-uploader/result.json` 的具体字段，不要直接重新上传。
- 如果上传封面后编辑器被遮罩挡住，找 `应用` 按钮并点击。
- 正文图片不要直接用隐藏 file input。它可能指向封面上传器，导致替换封面。
- 不要只看 media count。列表后的图片尤其要看 anchor 是否正确。脚本会在结果 JSON 里记录 `anchor_used` 和 `expected_anchor`。
- 如果某次运行只是部分成功，但图片位置不对，优先新建干净草稿重跑，不要在旧草稿上硬修。

## 脚本说明

- `upload_markdown_to_x_article.py --dry-run` 是安全检查，不会打开 X。
- Markdown 正文会无损渲染常见 inline 语法：`**` / `__` 粗体、`*` / `_` 斜体、`~~` 删除线、inline code、全部 ASCII 标点转义、平衡括号 inline link、full/collapsed reference link、URI/email autolink 与 HTML entity；代码围栏保持字面内容。普通未闭合的 `<tagless` 也会按文字转义，不会被 HTML parser 吞掉后文。
- 文件名标题与首 H1 的可见语义相同（即使 H1 带粗体等格式）时，首 H1 只作为重复标题删除；两者语义不同时，首 H1 是真实正文标题，保留并降级为 X 的 H2。
- 使用 `--draft-url` 做完整替换时，脚本会在写入新封面、标题和正文前清空，并尝试观测标题、正文、原生表格、正文媒体和旧封面是否归零。`--resume-images-only` 保留现有标题、正文、原生表格和封面，并尝试在写入前确认正文媒体为 0、封面数量及源图与本次 Markdown 匹配。这些写入前 DOM 基线若观测不稳定只记录 warning；同一草稿最终 reload 仍会从本地源文件独立严格核对全部内容。不要在明知旧正文图仍存在时使用该选项再插入完整图片集，否则最终数量或顺序验收会失败。
- 正式运行在任何持久化验证异常时都会写出 `status=partial` 的结果 JSON，包含 `phase`、`error_type`、`error`、`draft_url` 和 `mutation_epoch`，便于区分内容已经落盘但后置验证失败的情况；它仍会退出失败且不会把 partial 称为成功。
- 若仅是 autosave UI/`saveText`、瞬时 pre-reload DOM、runtime key、最终诊断截图或浏览器清理观测失败，而同 URL final reload 的全部核心内容严格通过，结果保持成功并把原因写入 `verification_warnings`；这些 warning 不能替代或降低最终正文、表格、封面和正文图片验收。
- dry-run 会输出 3 至 5 个互不跨越完整临时表格占位符的确定性正文检查点 `content_checkpoints`、规范化正文的 `expected_compact_length` 和 `expected_compact_sha256`；`compact_length_unit` 与 `checkpoint_position_unit` 固定为 `unicode_code_points`，保证 emoji 和扩展汉字在 Python 与浏览器中使用同一长度及位置口径。初次粘贴要求精确长度与 SHA-256 一致，最终回读还要求检查点按顺序命中并可靠剥离原生表格 DOM。
- backtick/tilde fenced code（代码围栏）在清洗、分块、图片/表格抽取和 rich HTML 生成的完整管线中都保持为不可被普通 Markdown 规则触碰的 token，最后才恢复；closing fence 必须使用同一字符、长度不短于 opening 且后面只有空白，backtick opening 的 info 中不能再含 backtick。代码里的 `**`、`*`、`[x](url)`、`![x](url)`、pipe table、尖括号和内部空行保持原样，不会被提取成正文图片或表格；`<img>` 等标签只显示为文字，不会变成真实远程媒体。正文转纯文本使用 HTML parser，不会再用宽泛正则误吞 `x < y > z` 这类普通文字。
- Skill 自身的 preflight 会忽略代码围栏和合法 frontmatter，但阻断围栏外 raw HTML、远程 inline 图片与任何未转义、非 inline 的 reference-style 图片；扫描不依赖 definition 所在位置，因此引用块、列表或尚未解析到 definition 的 full、collapsed、shortcut 写法都会 fail closed，并支持转义、嵌套、跨行 alt/label。只有完整 outer alt 后没有紧邻 `(` 或 `[` 的 `![[...]]` 才按 Obsidian wiki embed 忽略；`![[alt]](path)` 仍是 inline 图片，`![[alt]][ref]` 仍是 reference 图片。即使不经过 Obsidian 插件、直接运行 `--dry-run`，也不会打开 X。
- Markdown 支持 UTF-8 BOM；YAML frontmatter 的开头必须是独立一行 `---`，结尾必须是独立一行 `---` 或 `...`，字段值里的这些子串不会被误当成结束标记。
- 如果缺封面，dry-run 只输出 warning；正式上传会跳过封面上传，并在完成后提醒用户补一张 5:2 封面图。
- Markdown pipe 表格会在 dry-run 输出 `expected_tables` 和每张表的行列；正式上传会通过 X 原生表格块写入，不依赖 HTML table 粘贴，并会读回 X 表格块 Markdown 源码做一致性校验。
- 当前脚本会在 `expected_body_images > 25` 时自动输出 `body_media_limit_exceeded` 并在打开 X 前阻断；25 张正文图即使另有 1 张封面也允许继续。
- 上传脚本需要 Python Playwright 和有效的 X cookie JSON。
- Markdown parser 已经内置在当前 Skill 里，不依赖旧的 `x-article-publisher` Skill。
- cookie 导出脚本只读取本机 Chrome cookies，并把指定输出原子写成 `0600`；规范路径
  `~/.ailu/secrets/x/cookies.json` 的各级目录会拒绝符号链接并收紧为 `0700`。Skill 源码不包含任何 Cookie。
