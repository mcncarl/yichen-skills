# yichen-skills

[English](./README.md) | 中文

一个面向内容创作者的技能仓库，帮助你用 Claude Code / Codex 打通“沉淀知识 + X 内容切片 + X 文章草稿上传 + 微信数字资产 + 本地解析”的完整流程。

## 关于作者

作者：**逸尘**

- 微信号：`yichen365ai`
- 添加时请在验证信息中备注：`GitHub`

## 个人使用与商业授权

本仓库仅限个人学习和非商业个人工作流使用。凡涉及客户交付、付费产品或服务、公司内部部署、市场打包、课程打包及其他商业用途，均须事先取得作者明确的书面授权。

如需申请商业授权，请添加微信 `yichen365ai`，并在验证信息中备注 `商业授权`。仅发送好友申请或咨询不代表已经获得授权；收到作者明确的书面授权后，方可商用。

## 这个仓库能做什么

1. 把 Claude Code 对话沉淀为结构化 Obsidian 笔记（`yichen-summary`）
2. 把 Obsidian/Markdown 长文上传为 X Articles 草稿（`yichen-x-article-draft-uploader`）
3. Mac 微信双开，第二个微信带蓝色图标（`yichen-mac-wechat-dual-open`）
4. 从微信聊天、朋友圈、收藏夹沉淀 AI 数字资产（`yichen-wechat-local-vault`）
5. 抓取已知抖音链接的对标视频（`yichen-content-archive`）
6. 抓取已知小红书链接的对标笔记（`yichen-content-archive`）
7. 用火山 ASR 做转写、字幕和口播粗剪（`yichen-volc-asr`）
8. 诊断对标视频口播稿（`yichen-video-content`）
9. 通过 ChatGPT 官网完成可验证调研（`yichen-chatgpt-web-research`）
10. 把粗剪成片交给剪映/CapCut 做最后精修（`yichen-jianying-editor`）
11. 安装和维护 Markdown/Obsidian-first 的 Codex 记忆系统（`yichen-agent-memory`）
12. 批量导出公众号历史文章、原创列表、正文，以及可选阅读量/评论数据（`yichen-wechat-mp-batch-exporter`）
13. 只读解析并导出本机企业微信 5.x 数据库快照，不操控客户端（`yichen-wecom-local-vault`）
14. 在 GPT 主导的 Codex 对话中调用 Grok 原生搜索 X 或提供第二意见，不切换主模型（`yichen-grok-consult`）
15. 通过已退役别名兼容旧的收藏导出调用（`yichen-social-bookmarks-exporter`）
16. 用一个安全优先的总入口编排跨阶段互联网研究（`yichen-web-research`）
17. 把公共网页和平台搜索统一成可核验候选（`yichen-unified-search`）
18. 只读取、下载和归档已知或已确认链接（`yichen-content-archive`）
19. 在当轮授权闸门后直接执行私人收藏导出（`yichen-bookmarks-export`）
20. 在 Step 与豆包/火山 ASR 之间安全路由并避免重复提交（`yichen-asr`）
21. 通过企业微信官方 CLI 创建授权文档并管理待办、会议和日程，不操控客户端（`yichen-wecom-operations`）
22. 把一条公开 X Post 或 Thread 链接转成经过验收的 3:4 图片切片与成片，完整嵌入原生视频并在有源音轨时保留原声（`yichen-x-slicer`）
23. 在 Windows 上生成只读、经过完整性校验的微信 4.x 本地快照，不依赖 `wx-cli`，不注入、不 Hook、不控制进程（`yichen-wechat-windows-vault`）

## 包含的技能

### 1) `yichen-summary`
- 用途：提炼当前对话精华并保存到 Obsidian
- 常见触发词：`/yichen-summary`、保存对话、导出精华
- 关键能力：
  - 自动过滤低价值过渡内容
  - 输出结构化笔记（背景、核心内容、解决方案、关键要点、相关）
  - 适合长期知识沉淀

### 2) `yichen-x-article-draft-uploader`
把 Obsidian/Markdown 长文上传到 X Articles 草稿：
- 文章开头有图片时作为可选 5:2 封面；没有时保持草稿封面为空
- Markdown 转成 X 编辑器可识别的 rich text
- 将受支持的 pipe 表格转换成 X 原生表格块
- 最多 25 个正文媒体按原文位置插入
- 使用独立 Playwright 浏览器，不抢占用户当前 Chrome
- 把 Chrome 登录态导入私有 Cookie 文件，不写入仓库
- 刷新同一草稿，核验正文、表格、媒体身份、数量、顺序和位置
- 只保存草稿，绝不点击最终 `发布`

完整说明见 [yichen-x-article-draft-uploader/README.md](./yichen-x-article-draft-uploader/README.md)。

### 3) `yichen-mac-wechat-dual-open`
Mac 微信双开——无需第三方工具，一条命令搞定：
- 复制微信、改 Bundle Identifier、本地重签名
- 第二个微信图标自动改为蓝色，视觉上一眼区分
- 同时处理外层和内嵌图标文件、Finder 自定义图标和缓存刷新
- 命令行工作流：`create` → `recolor-icon` → `launch`
- 常见触发词："微信双开"、"WeChat dual open"
- 依赖：macOS 12+、微信（`/Applications/WeChat.app`）、Python 3.10+、Pillow
- 限制：微信更新后需要重新运行（用 `repair`）；推送通知可能不稳定
- 方法来源：[@koffuxu](https://x.com/koffuxu/status/2043110831584690427) 的公开教程

### 4) `yichen-wechat-local-vault`
微信数字资产沉淀助手（macOS 专属）：
- 解密微信 Mac 4.x 本地 SQLCipher 数据库（AES-256-CBC）
- 提取聊天记录、朋友圈（`sns.db`）和收藏夹（`favorite.db`）
- 生成群聊解析、朋友圈解析、收藏夹整理、客户跟进和大佬对话复盘草案
- 首次引导展示三大类九种玩法：聊天记录、朋友圈、收藏夹
- 可配置监控指定群聊、联系人、朋友圈对象和收藏夹整理偏好
- 首次使用通过 frida 引导密钥提取
- 常见触发词：”微信解析”、”微信全量”、”微信增量”、”导出聊天”、”朋友圈解析”、”收藏夹整理”、”客户跟进”、”yichen-wechat-local-vault”
- 依赖：macOS、微信 Mac 4.x、Python 3.9+、`pycryptodome`、`zstandard`
- 详细文档见 [yichen-wechat-local-vault/README.md](./yichen-wechat-local-vault/README.md)

### 5–6) 已融合进 `yichen-content-archive` 的社交平台抓取器
原先独立的抖音和小红书抓取器现在只保留一个事实源：
- `douyin_download.py` 通过 Playwright 拦截读取元数据或下载已知抖音视频
- `xiaohongshu_fetch.py` 默认匿名读取已知笔记，再按要求下载视频、字幕或图片
- 旧产物不会被覆盖，目标冲突时自动使用新的 `-run-N` 路径
- 小红书 Cookie 必须取得当前任务明确授权，可选飞书沉淀也只在用户明确要求时执行

### 7) `yichen-volc-asr`
本地音视频转写和口播粗剪：
- 火山 ASR 和 TOS 配置全部通过环境变量读取
- 输出转写稿、SRT 字幕、ASR 缓存和可选粗剪 MP4
- 清理临时文件前必须得到用户明确允许

### 8) `yichen-video-content`
对标视频内容拆解：
- 对口播稿逐句标注作用
- 输出可模仿结构和改进建议

### 9) `yichen-chatgpt-web-research`
通过用户已登录的 ChatGPT 官网账号执行调研：
- 使用真实 ChatGPT 网页，不走 OpenAI API，也不切到另一个账号
- 优先使用 Chrome 扩展控制，必要时才用可视化 Computer Use 兜底
- 等待完整答案和唯一校验标记后再提取
- 把原始输出和可读报告保存到当前工作区的 `reports/` 目录
- 公开版已去掉个人路径、Chrome 配置名、cookie、token 和浏览器存储信息

隐私边界和工作流见 [yichen-chatgpt-web-research/README.md](./yichen-chatgpt-web-research/README.md)。

### 10) `yichen-jianying-editor`
剪映/CapCut 桌面端精修助手：
- 检查素材、导入粗剪、放入时间线
- 处理字幕、画面精修、导出和项目记录
- 自动粗剪逻辑交给 `yichen-volc-asr`

### 11) `yichen-agent-memory`
安装和维护公开版 Agent Memory Vault 系统：
- 从公开模板创建本地 Markdown/Obsidian-first 记忆库
- Markdown 是事实源，SQLite/FTS 是快速索引
- 可选接入 Zvec 语义检索，用来找“意思相近但措辞不同”的记忆
- 引导写入前对账、任务结束 closeout、定期 audit 和公开模板脱敏更新
- 常见触发词：“安装 Codex 记忆系统”、“搭建记忆库”、“运行 memory closeout”、“audit 我的 Codex 记忆”
- 模板仓库：[mcncarl/agent-memory-vault](https://github.com/mcncarl/agent-memory-vault)

### 12) `yichen-wechat-mp-batch-exporter`
批量导出微信公众号文章：
- 把已知 `mp.weixin.qq.com` 文章链接下载成 Markdown/JSON/text/HTML
- 通过 `wechat-article-exporter` 做公众号搜索和历史列表同步
- 明确区分 `publish_groups`、`expanded_url_items` 和 `original_articles`
- 在有新鲜、用户自有凭证时，可规划导出阅读量、点赞、转发、评论和评论回复
- 扫码登录、凭证捕获、证书信任、代理修改和任何微信桌面端动作都必须先得到用户确认
- 不操控微信 UI，也不把真实凭据写入仓库

安装和隐私边界见 [yichen-wechat-mp-batch-exporter/README.md](./yichen-wechat-mp-batch-exporter/README.md)。

### 13) `yichen-wecom-local-vault`
只读解析、查询和导出 macOS 企业微信 5.x 桌面端数据库：
- 生成私密、带时间戳的明文快照，绝不写回企业微信容器
- 支持联系人、会话、聊天记录、搜索与 Markdown/JSON 导出
- raw key、快照和聊天导出都不进入 Git
- 不操控原始企业微信，也不发送消息

### 14) `yichen-grok-consult`
让 GPT 在不切换主模型的情况下调用 Grok：
- 通过官方 Grok Build CLI 原生搜索公开 X 帖子
- 检查隔离 Grok 会话是否真实完成 `XSearch`
- 提取 status URL，并确定性还原 Snowflake 编号中的发布时间
- 让 Grok 远离当前项目，关闭本地文件、Shell、MCP、记忆和子代理权限
- 可选通过本机 OpenCodex 提供独立回答、审稿和反方挑战

安装、隐私边界和校验限制见 [plugins/yichen-grok-consult/README.zh.md](./plugins/yichen-grok-consult/README.zh.md)。

### 15) `yichen-social-bookmarks-exporter`

为已有显式调用保留的兼容入口。当前维护实现已完整迁移到 `yichen-bookmarks-export`；兼容入口不会再执行目录中保留的旧脚本。

### 16) `yichen-web-research`

跨搜索、候选确认、归档和按需转写的研究总路由：

- 单阶段任务直接交给对应子 Skill
- 搜索结果不会自动进入下载
- 新增证据门控的横纵研究模式，包含有界工作流、主张—来源账本、矛盾检查和保留缺口披露
- 将 AI 最新发现、普通/垂直网页搜索、平台原生发现、显式站点 Map 和原文核验分配给不同后端，不静默互相替代
- 强制社交平台只读、目标级授权和禁止操控微信 UI
- 自带可移植、只读的后端体检脚本；检查可选适配器就绪状态时不输出密钥值、不读取凭据文件内容，也不发起付费探针

完整家族、可选后端和配置说明见 [yichen-web-research/README.md](./yichen-web-research/README.md)。

### 17) `yichen-unified-search`

公共网页与平台适配器的纯搜索编排：

- 覆盖 AI HOT、AnySearch、GitHub、微信公众号公共搜索、微博、小红书、抖音、今日头条、知乎、X、B站、YouTube 和小宇宙
- AI HOT 只处理具有时效性的 AI 动态发现，AnySearch 处理普通/批量/垂直网页搜索，Firecrawl 只处理显式的有界站点 Map 或对当前已签名 AnySearch 候选的显式核验
- 提供有界的知乎 CLI 搜索/热榜、微博匿名优先公开搜索，以及通过 Data API 或公开 `yt-dlp` 回退完成的 YouTube 关键词/频道发现；不下载媒体
- X Quick 对每个查询独立执行；X Research 支持有界的多查询分阶段搜索、确定性去重、来源保留、时间窗检查和最多一轮缺口补搜
- 输出带来源、覆盖范围和限制说明的标准候选
- 浏览器会话复用仅限文档明确列出的有界公开只读路线；访问私域数据或执行写操作仍需当前任务明确授权

#### 搜索词与第三方数据流

搜索文本会发送给当前路由选中的后端。不要在搜索词中放入密码、Cookie、个人数据、商业机密或私有 URL。
当当前服务要求 API 或 OAuth 凭据时，凭据只会按该服务协议发送给该服务；适配器不会把凭据值放入候选输出，也不会将其持久化到本仓库。

| 路线 | 离开本机进程的数据 | 接收方与边界 |
|---|---|---|
| AI HOT | AI 动态发现词以及可选分类/日期条件 | AI HOT 公开 API；AI 生成摘要只是发现线索，不是已核验证据 |
| AnySearch | 普通、批量或垂直查询及参数；只在显式核验时发送已选当前候选 URL | AnySearch；短期候选回执及其签名材料只留在本机 |
| GitHub | 仓库搜索词；已配置时，`gh` 可使用其 GitHub API 凭据 | 仅 GitHub；命令强制 `--visibility public`，查询只作为位置参数，不返回私有仓库 |
| Firecrawl | 显式提供的公开站点 Map 种子 URL 或已选且已签名 AnySearch 候选 URL，以及协议 `Authorization` header 中的 Firecrawl API 凭据 | 仅 Firecrawl；不发送浏览器 Cookie、页面 actions 或自定义页面 header。适配器不输出、不持久化凭据。Scrape 设置 `storeInCache=false`；Map 不作缓存控制声明，两条路线都不承诺零数据保留 |
| 知乎 | 关键词查询或显式热榜请求；另行安装的运行时可从 Keychain 状态认证 | 通过另行安装的知乎 Open Platform CLI 兼容运行时发给知乎；本仓库不包含、也不独立核验该运行时、其凭据或私人账号命令 |
| 微博 | 公开关键词查询 | 先发给 `m.weibo.cn` 并使用仅驻留内存的临时匿名访客会话；只有访问门失败才允许一次有界 OpenCLI 回退并复用现有浏览器会话。Cookie 值不进入适配器命令、结果或日志 |
| YouTube | 关键词/频道标识以及公开搜索条件；配置 API Key 时，Key 会位于 Data API 请求 URL 中 | YouTube Data API 或 `yt-dlp` 访问的 YouTube 公开界面；适配器不输出、不持久化 Key，不下载媒体 |
| X Quick / Research | 为当前有界搜索生成的每个查询；Grok CLI 使用其账号 OAuth 凭据与 xAI 通信 | 通过官方 Grok CLI 的原生 `x_search` 发给 xAI；只有 Grok 明确额度耗尽时才允许匿名 FxTwitter，OpenCLI/xreach 默认禁用，只能在当前任务明确授权后开启 |
| 小红书/抖音公开搜索 | 请求的公开搜索词 | 通过有界只读 OpenCLI 复用浏览器会话发给对应平台；该授权不延伸到私人收藏或写操作 |

### 18) `yichen-content-archive`

已知链接与精确容器处理：

- 读取并归档已确认的网页、小红书、抖音、公众号、YouTube、B站和小宇宙目标
- 内置唯一维护的抖音/小红书已知链接抓取器；小红书沉淀飞书仍需用户明确要求
- 搜索与开放式发现不进入归档层
- 使用不冲突输出目录、续跑检查点和显式覆盖保护

### 19) `yichen-bookmarks-export`

当前维护的私人收藏导出实现：

- 每个平台和范围都要求当前任务明确授权
- 内置小红书/抖音 Chrome 采集器和 X 本地索引导出器
- 只导出链接，不把授权自动转移到下载
- 交接文件只引用本地文件，不内嵌私人 URL

安装、依赖和隐私边界见 [yichen-bookmarks-export/README.md](./yichen-bookmarks-export/README.md)。

### 20) `yichen-asr`

统一 ASR 路由：

- 纯文本默认走兼容 Step 执行器，时间戳/SRT 默认走 `yichen-volc-asr`
- App ID 与 Token 只从环境变量读取
- 已经提交到某服务商的任务不会静默改投另一家

### 21) `yichen-wecom-operations`

通过官方 `@wecom/cli` 操作用户有权管理的企业微信云资源：

- 创建普通文档和基于 Markdown 的智能文档
- 只有完成权限检查和精确目标确认后才读取或覆写文档
- 创建和管理待办；会议、日程只在当前企业开放对应授权时使用
- 绝不操控企业微信客户端，也不发送消息
- Git 中不保存凭证、内部 ID、回执、源文件或客户数据
- 本地图片上传属于可选的外部 helper 能力，本仓库不分发该扩展

安装、权限边界和本地图片限制见 [yichen-wecom-operations/README.md](./yichen-wecom-operations/README.md)。

### 22) `yichen-x-slicer` — 逸尘 X 切片

把一条公开 X status 链接直接做成可发布素材：

- 默认生成经过验收的 1080×1440 图片组、仅含最终 PNG 的压缩包，以及 H.264 视频
- 默认使用“落日琥珀版”，并内置 11 套视觉模板
- 普通 Post 只保留主贴；Thread 只保留经过验证的同作者连续内容；引用贴与无关回复均排除
- 正文页和图片页保持静止，新增运动只发生在四帧换页转场中；原贴带原生视频时在媒体区域完整播放，不用封面冒充
- 通过 FxTwitter 匿名读取公开内容，不使用 X 登录态或 Cookie
- 不生成 TTS、配音、BGM 或音乐；选中原生视频有源音轨时，原声与对应视频页保持同步，无源音轨区间保持静音，全片没有任何源音轨时不生成音频流

可直接运行 `npx skills add mcncarl/yichen-skills --skill yichen-x-slicer` 安装。

### 23) `yichen-wechat-windows-vault`

Mac 微信本地 Vault 的独立 Windows 对应版本：

- 仅在当前任务得到明确同意后使用 Windows 只读进程检查
- 只有同时通过 SQLCipher HMAC 与 SQLite 文件头校验的数据库 key 才会被接受
- key 使用当前 Windows 用户的 DPAPI 加密，快照保存在 `%LOCALAPPDATA%` 私有目录
- 把 DB/WAL/SHM 作为稳定文件集复制，校验 WAL 帧与提交，并运行 SQLite 完整性检查
- 支持全量/增量不可变快照，以及与 Mac 版一致的联系人、会话、历史、搜索、导出、收藏夹和朋友圈查询
- 不依赖 `wx-cli`、Frida、注入、Hook、驱动、微信 UI 自动化或进程控制 API

同意边界、安装、架构和验证证据见 [yichen-wechat-windows-vault/README.md](./yichen-wechat-windows-vault/README.md)。

## 目录结构

```text
yichen-skills/
├─ yichen-summary/
│  └─ SKILL.md
├─ yichen-x-article-draft-uploader/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  └─ scripts/
│     ├─ export_x_cookies_from_chrome.py
│     ├─ parse_markdown.py
│     └─ upload_markdown_to_x_article.py
├─ yichen-wechat-local-vault/
│  ├─ SKILL.md
│  ├─ README.md
│  └─ scripts/
│     ├─ decrypt_all_dbs.py
│     ├─ export_chat.py
│     ├─ extract_keys.py
│     ├─ list_contacts.py
│     ├─ search_sns.py
│     └─ wechat_digest.py
├─ yichen-wechat-windows-vault/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ requirements.txt
│  ├─ scripts/
│  └─ tests/
├─ yichen-mac-wechat-dual-open/
│  ├─ SKILL.md
│  ├─ scripts/
│  │  └─ wechat_dual_open.py
│  └─ references/
│     └─ reliability-and-risks.md
├─ yichen-volc-asr/
│  ├─ SKILL.md
│  └─ scripts/
│     └─ transcribe.py
├─ yichen-video-content/
│  ├─ SKILL.md
│  └─ references/
│     └─ title-formulas.md
├─ yichen-chatgpt-web-research/
│  ├─ SKILL.md
│  ├─ README.md
│  └─ agents/
├─ yichen-jianying-editor/
│  └─ SKILL.md
├─ yichen-agent-memory/
│  ├─ SKILL.md
│  └─ agents/
├─ yichen-wechat-mp-batch-exporter/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  ├─ references/
│  └─ scripts/
├─ yichen-wecom-local-vault/
│  ├─ SKILL.md
│  ├─ agents/
│  ├─ references/
│  └─ scripts/
├─ yichen-social-bookmarks-exporter/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  ├─ references/
│  └─ scripts/
├─ yichen-web-research/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  ├─ scripts/
│  └─ tests/
├─ yichen-unified-search/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  ├─ references/
│  ├─ scripts/
│  └─ tests/
├─ yichen-content-archive/
│  ├─ SKILL.md
│  ├─ agents/
│  ├─ references/
│  ├─ scripts/
│  └─ tests/
├─ yichen-bookmarks-export/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  ├─ references/
│  ├─ scripts/
│  └─ tests/
├─ yichen-asr/
│  ├─ SKILL.md
│  ├─ agents/
│  ├─ references/
│  ├─ scripts/
│  └─ tests/
├─ yichen-wecom-operations/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  ├─ references/
│  └─ scripts/
├─ yichen-x-slicer/
│  ├─ SKILL.md
│  ├─ agents/
│  ├─ assets/
│  ├─ references/
│  └─ scripts/
├─ .agents/plugins/
│  └─ marketplace.json
├─ plugins/yichen-grok-consult/
│  ├─ .codex-plugin/plugin.json
│  ├─ .mcp.json
│  ├─ README.md
│  ├─ README.zh.md
│  ├─ mcp/server.mjs
│  ├─ mcp/authenticated-fallback-policy.mjs
│  ├─ mcp/authenticated-fallback-policy.test.mjs
│  └─ skills/yichen-grok-consult/
├─ README.md
├─ README.zh.md
├─ THIRD_PARTY_NOTICES.md
├─ LICENSE
└─ .gitignore
```

## 环境要求

- Claude Code / Codex CLI（支持加载本地 skills）
- Python Playwright（`yichen-x-article-draft-uploader` 必需）
- Python 3.9+
- 依赖：
  - X 文章草稿：`pip install playwright pycryptodome && python3 -m playwright install chromium`
  - 微信本地解析：`pip install pycryptodome zstandard`
  - 微信双开：`pip install Pillow`
  - 内容归档（抖音）：`pip install playwright requests && python3 -m playwright install chromium`
  - 内容归档（小红书）：`pip install requests`
  - 火山 ASR 粗剪：`pip install requests`，并安装本机 `ffmpeg` / `ffprobe`
  - ChatGPT 官网调研：Chrome 已登录 ChatGPT，且当前 Agent 环境支持 Chrome/Computer Use 能力
  - 公众号批量导出：已知 URL 正文下载只需 Python 3 标准库；历史列表、阅读量和评论需要额外配置 `wechat-article-exporter` / `wxdown-service`
  - 企业微信本地解析：`pycryptodome`；只有明确授权抓取本机 raw key 时才需要 `frida`
  - Grok Consult：Node.js 18+、官方 Grok Build CLI 和有效的 `grok login`；非搜索咨询工具可选依赖本机 OpenCodex
  - 社交收藏夹导出：小红书/抖音需要 Agent 环境支持 `chrome:control-chrome`；X 路线可选依赖版本标识包含 `graphql-only` 的 Field Theory `ft` CLI
  - Web Research 家族：五个家族目录必须一起安装。Unified Search 适配器使用 Python 标准库及可选 `idna`；其他家族成员仍需上文列出的依赖。可选路线需要另行安装其服务/运行时，例如 AnySearch、Firecrawl、知乎 Open Platform CLI 兼容运行时、OpenCLI、Grok 官方 CLI、`xreach`、`gh`、`yt-dlp`、`bili` 或 `ffmpeg`
  - YouTube 统一搜索可使用另行配置的 YouTube Data API 凭据，也可回退到公开 `yt-dlp` 列表；永不下载媒体
  - 微博统一搜索默认从匿名路线开始；文档明确的访问门回退需要 OpenCLI 和已登录的现有 Chrome 会话
  - 逸尘 X 切片：Node.js 18+、Playwright、本机 Chrome、`ffmpeg` 和 `ffprobe`

## 安装方式

把仓库内容复制到本地 skills 目录：

- 常见 Claude 路径：`~/.claude/skills/`
- 常见 Agents 路径：`~/.agents/skills/`
- 如果你有自定义技能目录，也可以使用自定义路径

建议保持目录名不变：
- `yichen-summary`
- `yichen-x-article-draft-uploader`
- `yichen-wechat-local-vault`
- `yichen-mac-wechat-dual-open`
- `yichen-volc-asr`
- `yichen-video-content`
- `yichen-chatgpt-web-research`
- `yichen-jianying-editor`
- `yichen-agent-memory`
- `yichen-wechat-mp-batch-exporter`
- `yichen-wecom-local-vault`
- `yichen-social-bookmarks-exporter`
- `yichen-web-research`
- `yichen-unified-search`
- `yichen-content-archive`
- `yichen-bookmarks-export`
- `yichen-asr`
- `yichen-wecom-operations`
- `yichen-x-slicer`

`yichen-grok-consult` 是 Codex 插件，不是只复制目录即可工作的普通 Skill。请通过本仓库的 marketplace 安装：

```bash
codex plugin marketplace add mcncarl/yichen-skills --ref main
codex plugin add yichen-grok-consult@yichen-skills
```

## 3 分钟快速上手

### A）启用 `yichen-summary`

1. 确保 `yichen-summary/SKILL.md` 在已加载的 skills 路径里
2. 新开会话后输入 `/yichen-summary`
3. 确认输出写入 Obsidian 目录（示例路径通常是 `<OBSIDIAN_VAULT>/...`）

### B）启用 `yichen-x-article-draft-uploader`

1. 按 Skill README 的防覆盖命令安装固定 tag `x-article-draft-uploader-v1.0.1`
2. 从 Skill 的 `requirements.txt` 安装精确 Python 依赖，再执行 `python3 -m playwright install chromium`
3. 确认 Chrome 已经登录 X；Ailu 用户可在设置页选择从 Chrome 导入、粘贴 JSON 或选择 JSON
4. 直接说“把这篇 Markdown 上传到 X Articles 草稿”，或手动运行脚本
5. Skill 会新建并核验草稿，不会正式发布
6. 固定版本安装命令和验收方法见 [yichen-x-article-draft-uploader/README.md](./yichen-x-article-draft-uploader/README.md)

### C）启用 `yichen-mac-wechat-dual-open`

1. 安装 Python 依赖：`pip3 install Pillow`
2. 在 Claude Code 中说"帮我微信双开"或 "WeChat dual open"
3. 脚本会自动创建第二个微信（`~/Applications/WeChat-2.app`）并改蓝色图标
4. 详细命令见 `yichen-mac-wechat-dual-open/SKILL.md`

### D）启用 `yichen-wechat-local-vault`

1. 安装 Python 依赖：`pip3 install pycryptodome zstandard`
2. 在 Claude Code 或 Codex 中说"微信解析"、"导出聊天"或"收藏夹整理"
3. 首次运行会引导你完成密钥提取，并从九种玩法里选择当前要启用的工作流
4. 如果不确定，默认从"聊天记录解析 + 朋友圈解析 + 收藏夹整理"开始
5. 后续使用自动生成对应的解析报告或草案
6. 详细说明见 [yichen-wechat-local-vault/README.md](./yichen-wechat-local-vault/README.md)

### E）启用自媒体视频工作流

1. 安装 Playwright、requests 和 ffmpeg
2. 用 `yichen-content-archive` 保存已知抖音或小红书对标素材
3. 用 `yichen-volc-asr` 做转写、字幕或口播粗剪
4. 用 `yichen-video-content` 诊断对标稿
5. 用 `yichen-jianying-editor` 做剪映/CapCut 导入、字幕、精修和导出

### F）启用 `yichen-chatgpt-web-research`

1. 确认 Chrome 已登录目标 ChatGPT 账号
2. 如果任务要求 Pro 路线，保持可见页面能确认账号或模型状态
3. 直接提出官网调研任务，例如：“用 ChatGPT 官网调研 Anthropic，并保存 Markdown 报告”
4. Skill 会等待完整答案、校验标记，并保存原始版和可读版报告

### G）启用 `yichen-agent-memory`

1. 确保 `yichen-agent-memory/SKILL.md` 在已加载的 skills 路径里
2. 对 Codex 说“安装 Codex 记忆系统”或“搭建本地 Codex 记忆库”
3. Skill 会使用 [mcncarl/agent-memory-vault](https://github.com/mcncarl/agent-memory-vault) 创建一个本地私有 vault
4. 安装后用 `codex_memory_search.py`、`codex_memory_closeout.py`、`codex_memory_audit.py` 分别做搜索、任务结束整理和定期体检

### H）启用 `yichen-wechat-mp-batch-exporter`

1. 确保 `yichen-wechat-mp-batch-exporter/SKILL.md` 在已加载的 skills 路径里
2. 如果只是下载已知文章链接，直接要求下载 Markdown 即可
3. 如果要抓公众号历史列表，配置 `WECHAT_ARTICLE_EXPORTER_DIR`，或使用 `wechat-article-exporter` 支持的公开 exporter 路线
4. 如果要抓阅读量和评论，配置 `WXDOWN_SERVICE_DIR`，并在启动任何本地凭证辅助服务前确认凭证捕获流程
5. 涉及指标、评论、代理、证书或微信桌面端动作前，先看 [yichen-wechat-mp-batch-exporter/README.md](./yichen-wechat-mp-batch-exporter/README.md)

### I）启用 `yichen-wecom-local-vault`

1. 确保 `yichen-wecom-local-vault/SKILL.md` 在已加载的 skills 路径里
2. 安装 `pycryptodome`；只有在明确授权本机捕获 raw key 时才安装 `frida`
3. 直接要求检查或导出本机企业微信数据；流程不会操控原始客户端

### J）启用 `yichen-grok-consult`

1. 安装官方 Grok Build CLI，并执行 `grok login`
2. 添加 `mcncarl/yichen-skills` marketplace，再安装 `yichen-grok-consult`
3. 新建 Codex 任务
4. 让 GPT 调用 Grok 搜索公开 X 帖子，或要求 Grok 提供第二意见
5. 配置代理或 OpenCodex 前先看 [plugins/yichen-grok-consult/README.zh.md](./plugins/yichen-grok-consult/README.zh.md)

### K）启用 `yichen-bookmarks-export`

1. 确保 `yichen-bookmarks-export/SKILL.md` 在已加载的 skills 路径里
2. 小红书或抖音导出前，在当前 Chrome 登录目标账号并打开收藏页
3. X 导出前，确认另行安装的 `ft --version` 包含 `graphql-only`
4. 明确指定本轮授权的平台、导出范围和输出目录
5. Skill 只导出链接并做核验，不会自动下载媒体或修改收藏状态

### L）启用 Web Research 家族

1. 一起安装 `yichen-web-research`、`yichen-unified-search`、`yichen-content-archive`、`yichen-bookmarks-export` 和 `yichen-asr`
2. 如果使用 Skills CLI 从本仓库安装这五个 Skill，运行：

```bash
npx skills add mcncarl/yichen-skills --skill yichen-web-research
npx skills add mcncarl/yichen-skills --skill yichen-unified-search
npx skills add mcncarl/yichen-skills --skill yichen-content-archive
npx skills add mcncarl/yichen-skills --skill yichen-bookmarks-export
npx skills add mcncarl/yichen-skills --skill yichen-asr
```

3. 只安装并登录目标路线实际需要的第三方后端；它们的可执行文件和凭据均不包含在本仓库中
4. 运行 `python3 yichen-web-research/scripts/validate_family.py`
5. 多阶段任务从 `$yichen-web-research` 开始；纯搜索、已知链接归档、收藏导出或本地 ASR 可直接调用对应子 Skill
6. 启用付费或账号会话路线前，先阅读上方查询/数据流表和 [yichen-web-research/README.md](./yichen-web-research/README.md)

## 支持这个项目

如果这些 Skills 对你有帮助，可以通过下面的微信赞赏码自愿请我喝杯咖啡。

<p align="center">
  <img src="./assets/wechat-reward-code.jpg" width="280" alt="逸尘的微信赞赏码">
</p>

赞赏完全自愿，不构成付费服务、技术支持、功能交付或响应时效承诺。

## X Cookie 处理

本仓库不包含真实凭据，也不再提供需要手动填写的 cookie 模板。

`yichen-x-article-draft-uploader` 可从本机 Chrome 导出 X Cookie 到私有的 Playwright JSON。Ailu 用户通常应直接使用设置页里的三种导入方式：

```bash
python3 ~/.agents/skills/x-article-draft-uploader/scripts/export_x_cookies_from_chrome.py \
  --output ~/.ailu/secrets/x/cookies.json
```

规范目录权限为 `0700`，文件权限为 `0600`。Cookie 文件仍是敏感文件：不要提交到 Git、上传到 issue，或附进诊断包。`.gitignore` 已默认忽略 Cookie JSON。

## 安全说明

- 不包含真实 token/cookie
- 历史缓存类目录默认不追踪
- 个人绝对路径已替换为通用写法
- 第三方 AppID、AppToken、TableID、bucket 名和 ASR token 必须通过环境变量或私有配置提供
- 公众号 exporter auth-key、凭证文件、扫码登录秘密、捕获 cookies 和下载的文章归档必须只保存在本地
- `yichen-grok-consult` 不包含固定代理或凭证；但查询和结果仍会发送给 xAI，并保存在隔离的本机会话目录
- Web Research 家族不包含个人绝对路径、App ID、Token、固定钥匙串项或私人代理值；账号路线仍必须显式启用
- Unified Search 只会按上方数据流表，把查询发送给当前路由选中的第三方后端。本地签名材料、浏览器 Cookie 值和第三方凭据不包含在仓库文件或标准候选输出中
- 微博匿名访客会话只存在于适配器内存。使用文档明确的 OpenCLI 回退时，由 OpenCLI 管理浏览器会话，适配器不接受也不打印 Cookie 值
- Firecrawl Scrape 设置 `storeInCache=false`；Map 不作缓存控制声明，两者都不得被解读或宣传为零数据保留承诺
- `yichen-wecom-operations` 不包含 Bot ID、Secret、内部用户/资源 ID、回执、源文档或客户数据；权限范围由当前企业动态决定

如果你曾在公开仓库暴露过 Cookie，请立即轮换。

## 常见问题

### 为什么 skill 没触发？
- 检查 skill 是否放在“当前真实加载路径”
- 重启会话再试
- 检查 `SKILL.md` 里的 frontmatter（`name` / `description`）

### 为什么上传 X Articles 草稿失败？
- 检查 Chrome 是否仍然登录 X
- 重新导出临时 cookies
- 检查 Python Playwright 是否安装
- 检查 Markdown/图片路径是否存在

### Obsidian 路径可以改吗？
- 可以，直接改 skill 里的示例路径
- `<OBSIDIAN_VAULT>/...` 只是示例

## 二次分发建议

本仓库仅用于个人学习和非商业个人工作流使用。未经作者明确书面许可，不得用于商业服务、客户交付、付费产品、公司内部工具包、市场分发包、课程资料或任何营利目的。如需申请商业授权，请添加微信 `yichen365ai`，并在验证信息中备注 `商业授权`。

如果你为了个人学习而 Fork，至少保留：
- `README.md`
- `README.zh.md`
- `LICENSE`
- `.gitignore`
- `THIRD_PARTY_NOTICES.md`
- `yichen-x-article-draft-uploader/README.md`

不要把本仓库重新打包或重新发布为公开 Skill 套件。并明确提醒用户不要上传真实凭据或隐私数据。

## 致谢

本仓库的 X Articles 草稿上传流程和 Markdown 解析思路，参考了以下项目：

- `wshuyi/x-article-publisher-skill`
  - 仓库：<https://github.com/wshuyi/x-article-publisher-skill>
  - 文档：<https://github.com/wshuyi/x-article-publisher-skill/blob/main/README_CN.md>
  - 许可：MIT

`yichen-wechat-local-vault` 的微信数据库解密方法参考了以下项目：

- `zhuyansen/wx-favorites-report`
  - 仓库：<https://github.com/zhuyansen/wx-favorites-report>
  - 作者：zhuyansen
  - 许可：MIT
  - 具体参考：frida hook `CCKeyDerivationPBKDF` 密钥提取方法和 SQLCipher 4 分页解密逻辑

`yichen-mac-wechat-dual-open` 的微信双开方法参考了：

- [@koffuxu](https://x.com/koffuxu) — 原始教程 (2026-04)：[Mac 微信双开最完美方案](https://x.com/koffuxu/status/2043110831584690427)
- [@MinLiBuilds](https://x.com/MinLiBuilds) — 独立验证 (2026-04)

`yichen-grok-consult` 的隔离 Grok Build 搜索设计参考了：

- [`sudoHG/codex-grok-search`](https://github.com/sudoHG/codex-grok-search) — MIT 许可的公开参考；本仓库未复制其源码

`yichen-bookmarks-export` 的 X 书签路线调用：

- [`afar1/fieldtheory-cli`](https://github.com/afar1/fieldtheory-cli) — MIT 许可的可选外部运行时；本仓库未打包 Field Theory 源码或二进制
- 所要求的 `graphql-only` 标识指用户自行维护的修改版，不是上游官方发布名称；该修改版未在本仓库分发

`yichen-wecom-operations` 调用用户另行安装的企业微信官方 CLI：

- [`WeComTeam/wecom-cli`](https://github.com/WecomTeam/wecom-cli) — MIT 许可的外部运行时；本仓库不打包上游源码、二进制、Bot 凭证或租户数据
- 本地图片上传需要用户另行提供、暴露 `doc +doc_upload_image` 的可选 helper；该本地扩展未在本仓库分发，也不表述为上游官方能力

`yichen-unified-search` 的 YouTube 搜索/筛选实现部分派生自：

- Joe Sun 的 [`joeseesun/yt-search-download`](https://github.com/joeseesun/yt-search-download) — MIT 许可；上游 copyright 和完整许可文本保留在 `licenses/joeseesun-yt-search-download-LICENSE.txt`
- 本仓库只改编公开搜索/筛选行为；本地适配器输出标准发现候选，不包含上游的下载、字幕或媒体提取工作流

知乎路线调用另行安装的知乎 Open Platform CLI 兼容运行时；本仓库不独立核验其厂商来源：

- 本仓库不分发知乎 CLI 源码或二进制，也不为该外部可执行文件授权
- 用户安装或使用前，必须识别该运行时的分发方，并查阅当前版本的许可和服务条款

详细说明见 `THIRD_PARTY_NOTICES.md`。

## 合规边界

- 本项目与 AI HOT、AnySearch、Firecrawl、知乎、微博、YouTube、Google、X、xAI、OpenAI、微信、腾讯、小红书、抖音或 Field Theory 上游无隶属、背书或合作关系。
- 本仓库仅限个人学习和非商业个人工作流使用。
- 未经作者书面许可，禁止商用、客户交付、转售、付费分发、市场打包、课程打包或公司内部部署。
- 使用者需自行遵守 X 平台条款、自动化政策及当地法律法规。
- 收藏导出只可用于用户本人有权访问的数据；不得绕过访问控制、验证码、限流或平台安全措施。
- 搜索词和已选公开 URL 会发送给上文所述的当前路由第三方服务。使用者需自行遵守这些服务的最新条款、隐私政策、额度和数据保留规则；绝不要把搜索框当成传递秘密或私有数据的渠道。
- 搜索卡片、AI 生成摘要、指标和已打开页面仍属候选证据；相关主张必须在合适的原始来源中核验。
- X 内部 GraphQL 和平台 DOM 抓取均为非官方兼容路线，可能变化或触发平台限制。
- `yichen-wechat-local-vault` 仅限个人使用——仅可解密和读取本人的聊天数据，不得用于侵犯他人隐私。
- `yichen-wecom-local-vault` 仅限 owner 授权的本地数据；绝不上传 key、明文快照或聊天导出。
- `yichen-wecom-operations` 仅限 owner 授权的机器人资源；不得发送消息、操控客户端、绕过企业未开放的授权，也不得提交内部 ID、回执、源文档或客户数据。
- 请勿把真实账号凭据（如 `cookies.json`、`wechat-keys.json`）上传到公开仓库。
- 请勿上传真实聊天记录、微信数据库、客户数据、私人笔记、API key、本机路径或其他个人隐私数据。

## License

Personal Learning and Non-Commercial Use License。见 [LICENSE](./LICENSE)。
