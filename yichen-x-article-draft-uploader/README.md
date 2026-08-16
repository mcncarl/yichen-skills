# x-article-draft-uploader

把 Obsidian 或本地 Markdown 文章上传到 X Articles 草稿的 Codex Skill。

它会自动完成：

- 第一张图作为 X Article 封面
- 封面图推荐按当前 X 界面提示使用 5:2
- 如果文章不是以图片开头，跳过封面区域，继续上传标题、正文和正文图片
- Markdown pipe 表格转成 X 原生表格块
- Markdown 转 rich text 正文
- 正文图片按原文位置插入
- 正文最多 25 个媒体项；封面单独上传，不占正文名额
- 使用独立 Playwright 浏览器，不抢占用户当前 Chrome
- 从本机 Chrome 导出 X cookies 到私有文件，不把 cookies 写进 Skill
- 只保存草稿，不点击最终 `发布`

## 适合场景

- 从 Obsidian 发布长文到 X Articles
- Markdown 里有大量本地图片
- 封面图使用文章最上方的第一张图片，推荐比例 5:2
- Markdown 中包含 10 x 10 以内的 pipe 表格，需要保留为 X 原生表格
- 需要在没有封面图时先上传正文，而不是自动拿正文里的第一张图充当封面
- 旧脚本出现缺图、错位、`MPH_MARKER` 残留
- 用户已经在 Chrome 登录 X，但不希望自动化接管当前浏览器窗口

## 版本与兼容性

- 当前固定版本：`1.0.1`
- Git tag：`x-article-draft-uploader-v1.0.1`
- 已按 Ailu `0.2.0` 的 `x-article-persistence-v1` 结果契约核对
- 固定版本只创建 X Article 草稿，不包含最终发布动作

不要从会继续变化的 `main` 安装生产版本；请使用下面带 tag 的固定地址。

## 安装

Ailu 能从 `~/.agents/skills/x-article-draft-uploader/` 或
`~/.codex/skills/x-article-draft-uploader/` 发现当前 Skill。首次安装到 Codex 时，先确认
目标目录不存在，再从固定 tag 安装：

```bash
(
  skill_target="$HOME/.codex/skills/x-article-draft-uploader"
  if [ -e "$skill_target" ]; then
    echo "目标已存在，请先人工对比旧版本：$skill_target" >&2
    exit 1
  fi
  npx --yes skills@1.5.22 add \
    "https://github.com/mcncarl/yichen-skills/tree/x-article-draft-uploader-v1.0.1/yichen-x-article-draft-uploader" \
    --skill x-article-draft-uploader --global --agent codex --copy --yes
)
```

仓库目录名是 `yichen-x-article-draft-uploader`，Skill 的规范安装名是
`x-article-draft-uploader`。如果手动复制，目标也必须使用规范名：

- Ailu / 通用：`~/.agents/skills/x-article-draft-uploader/`
- Codex：`~/.codex/skills/x-article-draft-uploader/`
- Claude Code：`~/.claude/skills/x-article-draft-uploader/`（Ailu 不从这里自动发现）

已有旧版本时先人工对比并明确决定升级，不要直接覆盖，也不要把新目录嵌套进旧目录。

## 依赖

需要 Python 3.9+。固定版本已锁定经过本地契约测试的 Python 依赖：

```bash
python3 -m pip install -r \
  "$HOME/.codex/skills/x-article-draft-uploader/requirements.txt"
python3 -m playwright install chromium
```

macOS 上还需要 Chrome 已安装，并且当前 Chrome 已登录 X。

## 快速使用

### 1. 准备 X cookies

使用 Ailu 时，优先在设置页选择“从 Chrome 导入”“粘贴 JSON”或“选择 JSON”。
Ailu 会把校验后的 Cookie 原子写入私有路径，不把 Cookie 放进 Vault、日志或 Git。

独立运行 Skill 时，可以显式导出到同一个私有路径：

```bash
python3 "$HOME/.agents/skills/x-article-draft-uploader/scripts/export_x_cookies_from_chrome.py" \
  --output "$HOME/.ailu/secrets/x/cookies.json"
```

脚本只会打印 Cookie 名称，不会打印 Cookie 值；规范目录使用 `0700`，文件使用
`0600`。上传器还会在启动浏览器前检查文件大小、权限、X 域名范围，以及是否包含
`auth_token` 和 `ct0`。macOS 可能弹出 Chrome Safe Storage 的钥匙串授权。

### 2. 先做 dry-run

```bash
python3 "$HOME/.agents/skills/x-article-draft-uploader/scripts/upload_markdown_to_x_article.py" \
  "/absolute/path/to/article.md" \
  --cookies-json "$HOME/.ailu/secrets/x/cookies.json" \
  --dry-run
```

dry-run 会检查：

- 文章标题
- 可选封面图，推荐比例 5:2
- Markdown pipe 表格数量和行列数
- 第一个有效内容是否是图片；如果不是，只作为缺封面提醒，不阻断上传
- 所有图片文件是否真实存在
- 正文图片数量
- 正文图片是否超过 25；超过时在打开 X 前阻断，封面不计入这 25 个名额
- 每张正文图的插入锚点
- 用于最终验收的正文结尾短句

如果 `preflight.errors` 非空，脚本会中断。此时不会打开 X，也不会创建草稿。

如果文章第一个有效内容不是图片，脚本会继续上传无封面草稿。不要自动挑正文图、不要自动插入封面图；上传完成后提醒用户补一张 5:2 封面图。

如果 dry-run 报 `table_too_large`，先拆表、改成图片，或改写成正文段落；当前 X 表格尺寸选择器实测最大为 `10 x 10`。

如果报缺图、弱锚点或图片数量不一致，先修 Markdown 或图片文件，再重新 dry-run。不要跳过 dry-run 直接上传。

如果报 `body_media_limit_exceeded`，说明正文图片超过 25。先合并连续截图或拆分文章，再重新 dry-run；`1 张封面 + 25 张正文图` 是允许的，不要把封面误算进正文名额。

### 3. 上传为新的 X Article 草稿

```bash
python3 "$HOME/.agents/skills/x-article-draft-uploader/scripts/upload_markdown_to_x_article.py" \
  "/absolute/path/to/article.md" \
  --cookies-json "$HOME/.ailu/secrets/x/cookies.json"
```

输出文件：

- `~/.ailu/runs/x-article-draft-uploader/draft-url.txt`：草稿 URL
- `~/.ailu/runs/x-article-draft-uploader/result.json`：校验结果
- `~/.ailu/runs/x-article-draft-uploader/final.png`：最终截图

默认产物目录会拒绝符号链接并收紧为 `0700`；三个已有目标也必须是普通文件。

## 工作原理

1. 解析 Markdown，识别标题、可选封面图和正文图片。
2. 做 preflight：检查图片文件、正文图片数量、25 张正文媒体上限、图片锚点和最终结尾验收文本；封面单独计算，缺少置顶封面只记录 warning。
3. 从每张图片前一行提取 anchor，用于定位插图位置。代码围栏、分隔线、列表编号和过短文本不会被当成稳定锚点。
4. 新开独立 Playwright Chromium 会话，并加载已校验的私有 cookies。
5. 在 X Articles 新建草稿。
6. 如果有置顶封面图，上传封面并点击 X 的 `应用`；没有封面时跳过这一步，让封面区域保持空白。
7. 粘贴 rich HTML 正文。
8. 将 Markdown 表格占位符替换为 X 原生表格块：插入表格块、打开铅笔编辑器、写入原始 Markdown 表格并更新，然后再打开铅笔编辑器读回 Markdown 源码做一致性校验。
9. 从后往前插入正文图片，避免前面的插入动作影响后面定位。每次粘贴必须找到目标位置并让媒体数精确增加 1；粘贴后的瞬时 DOM identity、anchor 或 runtime key 如果不稳定，只记录 warning，不提前把已经放上的图片判成失败。
10. 等待 X autosave。autosave UI 文案没捕获到时不直接失败，继续交给同一草稿的最终刷新验收。
11. 刷新同一个草稿，独立校验标题、正文精确长度与 SHA-256、无 `MPH_MARKER`、无 `X_TABLE_MARKER`、表格精确数量与矩阵/Markdown 回读，以及全部图片的本地源图身份、数量、occurrence、DOM 顺序和语义锚点。图片用 dHash、8 x 8 RGB/亮度样本、源图唯一最近关系和宽高比严格验收；X 重编码超过严格指纹半径时使用有界多信号共识，不会靠整体放宽单个阈值猜图。
12. 如果本次无封面，完成后提醒用户：你这篇文章忘补封面图了，是否需要我帮你补一张 5:2 封面图？

## 失败后的处理

不要在失败后立刻重跑。每次正式上传都会新建一篇 X Article 草稿，盲目重跑会在草稿箱里制造重复半成品。

先看这三个文件：

- `~/.ailu/runs/x-article-draft-uploader/draft-url.txt`：如果已经有 URL，说明 X 里可能留下了一个半成品草稿。
- `~/.ailu/runs/x-article-draft-uploader/result.json`：判断是标题、正文、结尾、媒体数还是保存状态失败。
- `~/.ailu/runs/x-article-draft-uploader/final.png`：确认页面上真实看到的内容。

如果只是最终验收误报，先修验收逻辑或做只读核验，不要重新上传。需要删除重复草稿时，先向用户确认，再动手。

## 隐私与安全

- Skill 不包含任何真实 cookies、token、账号密码或 API key。
- Ailu 只在 `~/.ailu/secrets/x/cookies.json` 保存经过校验的 X Cookie；目录为
  `0700`、文件为 `0600`。
- 不要把 Cookie JSON、浏览器数据库、诊断截图、草稿 URL 或任何真实账号数据提交到 Git。
- 如果用户选择其他 Cookie 路径，该文件的保管与清理仍由用户负责。
- 脚本默认只创建草稿，不会公开发布文章。

## 常见问题

### X 跳到登录页怎么办？

说明 cookies 过期了，重新运行：

```bash
python3 "$HOME/.agents/skills/x-article-draft-uploader/scripts/export_x_cookies_from_chrome.py" \
  --output "$HOME/.ailu/secrets/x/cookies.json"
```

如果仍然失败，先手动在 Chrome 登录 X。

### 封面上传后页面被遮住怎么办？

X 会弹出媒体编辑层。必须点击 `应用`，否则编辑器会被 mask 挡住，封面也不会真正保存。脚本已经内置这个动作。

### 文章不是以图片开头怎么办？

直接上传无封面草稿。不要把正文里的第一张图挪去当封面；上传完成后提醒用户补一张 5:2 封面图。

### Markdown 表格会怎么上传？

脚本不会直接粘贴 HTML `<table>`，因为 X 会把它压成普通文本。脚本会先在正文里放临时 `X_TABLE_MARKER_*`，再用 X 的 `插入 -> 表格` 创建原生表格块，打开铅笔编辑器写入原始 Markdown 表格，最后校验没有占位符残留，并读回 X 表格块 Markdown 源码确认与本地一致。

当前只自动处理 `10 x 10` 以内的表格。更大的表格先拆分、截图，或改写成正文段落。

### dry-run 报 weak_image_anchor 怎么办？

在对应图片前补一行唯一、清楚的说明文字，例如 `PDF 文件验收截图：`。不要依赖 ` ``` `、`---`、列表编号、短词或重复段落作为图片定位锚点。

### dry-run 报 missing_body_image 怎么办？

说明 Markdown 引用的本地图片路径找不到。先修路径、移动图片或替换成存在的图片，再重新 dry-run。不要让脚本跑到 X 里才发现图片不存在。

### 草稿箱里出现重复草稿怎么办？

这是正式上传失败后反复重跑造成的。先确定最终可用草稿 URL，再询问用户是否删除半成品；不要擅自删除 X 草稿。

### 为什么正文图片要倒序插入？

因为 X 编辑器是动态内容。先插前面的图片会改变后面内容的位置。倒序插入更稳定。

### 是否会接管我的 Chrome？

不会。脚本只读取本机 Chrome 保存的 X 登录态，然后在独立 Playwright 浏览器中执行上传。

## 文件结构

```text
x-article-draft-uploader/
├── SKILL.md
├── README.md
├── LICENSE
├── VERSION
├── requirements.txt
├── agents/
│   └── openai.yaml
├── examples/
│   └── smoke-test.md
├── scripts/
│   ├── export_x_cookies_from_chrome.py
│   ├── parse_markdown.py
│   └── upload_markdown_to_x_article.py
└── tests/
    ├── anchor_normalization_vectors.json
    ├── test_cookie_exporter.py
    └── test_local_contracts.py
```

## License

本 Skill 仅允许个人学习、研究和非商业个人工作流使用。客户交付、付费产品或服务、
公司内部部署、市场打包、课程打包及其他商业用途，必须事先取得作者明确的书面授权。

如需申请商业授权，请添加微信 `yichen365ai`，并在验证信息中备注 `商业授权`。
仅发送好友申请或咨询不代表已经获得授权；收到明确书面授权后方可商用。

完整条款见本目录的 [`LICENSE`](LICENSE)。该限制只适用于
`x-article-draft-uploader` Skill，不改变 Ailu 核心的 AGPL-3.0-or-later 许可；
第三方材料继续适用各自许可证和仓库根目录的 `THIRD_PARTY_NOTICES.md`。

部分 Markdown 解析流程参考并迁移自 `wshuyi/x-article-publisher-skill`，详见仓库根目录 `THIRD_PARTY_NOTICES.md`。
