# yichen-skills

[English](./README.md) | 中文

一个面向内容创作者的技能仓库，帮助你用 Claude Code / Codex 打通”沉淀知识 + X 文章草稿上传 + 微信数字资产 + 本地解析”的完整流程。

## 这个仓库能做什么

1. 把 Claude Code 对话沉淀为结构化 Obsidian 笔记（`summary`）
2. 把 Obsidian/Markdown 长文上传为 X Articles 草稿（`x-article-draft-uploader`）
3. 从微信聊天、朋友圈、收藏夹沉淀 AI 数字资产（`wechat-local-vault`）
4. Mac 微信双开，第二个微信带蓝色图标（`mac-wechat-dual-open`）
5. 抓取抖音和小红书对标视频/笔记（`douyin-fetcher`、`xiaohongshu-fetch`）
6. 用火山 ASR 做转写、字幕和口播粗剪（`volc-asr`）
7. 诊断对标视频和口播稿内容（`yichen-video-content`、`dbs-content`）
8. 把粗剪成片交给剪映/CapCut 做最后精修（`jianying-editor`）

## 包含的技能

### 1) `summary`
- 用途：提炼当前对话精华并保存到 Obsidian
- 常见触发词：`/summary`、保存对话、导出精华
- 关键能力：
  - 自动过滤低价值过渡内容
  - 输出结构化笔记（背景、核心内容、解决方案、关键要点、相关）
  - 适合长期知识沉淀

### 2) `x-article-draft-uploader`
把 Obsidian/Markdown 长文上传到 X Articles 草稿：
- 第一张图片自动作为 X Article 封面
- Markdown 转成 X 编辑器可识别的 rich text
- 正文图片按原文位置插入
- 使用独立 Playwright 浏览器，不抢占用户当前 Chrome
- 通过临时导出的 cookies 复用 Chrome 登录态
- 只保存草稿，不点击最终 `发布`

完整说明见 [x-article-draft-uploader/README.md](./x-article-draft-uploader/README.md)。

### 3) `mac-wechat-dual-open`
Mac 微信双开——无需第三方工具，一条命令搞定：
- 复制微信、改 Bundle Identifier、本地重签名
- 第二个微信图标自动改为蓝色，视觉上一眼区分
- 同时处理外层和内嵌图标文件、Finder 自定义图标和缓存刷新
- 命令行工作流：`create` → `recolor-icon` → `launch`
- 常见触发词："微信双开"、"WeChat dual open"
- 依赖：macOS 12+、微信（`/Applications/WeChat.app`）、Python 3.10+、Pillow
- 限制：微信更新后需要重新运行（用 `repair`）；推送通知可能不稳定
- 方法来源：[@koffuxu](https://x.com/koffuxu/status/2043110831584690427) 的公开教程

### 4) `wechat-local-vault`
微信数字资产沉淀助手（macOS 专属）：
- 解密微信 Mac 4.x 本地 SQLCipher 数据库（AES-256-CBC）
- 提取聊天记录、朋友圈（`sns.db`）和收藏夹（`favorite.db`）
- 生成群聊解析、朋友圈解析、收藏夹整理、客户跟进和大佬对话复盘草案
- 首次引导展示三大类九种玩法：聊天记录、朋友圈、收藏夹
- 可配置监控指定群聊、联系人、朋友圈对象和收藏夹整理偏好
- 首次使用通过 frida 引导密钥提取
- 常见触发词：”微信解析”、”微信全量”、”微信增量”、”导出聊天”、”朋友圈解析”、”收藏夹整理”、”客户跟进”、”wechat-local-vault”
- 依赖：macOS、微信 Mac 4.x、Python 3.9+、`pycryptodome`、`zstandard`
- 详细文档见 [wechat-local-vault/README.md](./wechat-local-vault/README.md)

### 5) `douyin-fetcher`
抓取抖音视频元数据并下载 MP4：
- 支持 `/video/<id>` 链接和部分弹窗类链接
- 下载视频旁边生成精简 `.metadata.json`
- 支持 `--metadata-only`，只验证链接不下载视频

### 6) `xiaohongshu-fetch`
抓取小红书视频/图文笔记到本地：
- 解析 `window.__INITIAL_STATE__`
- 尽量下载视频、字幕、图片和元数据
- 不把 Cookie、飞书 AppToken/TableID、目标表 ID 写进仓库

### 7) `volc-asr`
本地音视频转写和口播粗剪：
- 火山 ASR 和 TOS 配置全部通过环境变量读取
- 输出转写稿、SRT 字幕、ASR 缓存和可选粗剪 MP4
- 清理临时文件前必须得到用户明确允许

### 8) `yichen-video-content`
对标视频内容拆解：
- 对口播稿逐句标注作用
- 输出可模仿结构和改进建议

### 9) `dbs-content`
内容创作诊断：
- 检查选题、形式、表达和平台是否匹配
- 给修改方向，不替代创作者自己的写作

### 10) `jianying-editor`
剪映/CapCut 桌面端精修助手：
- 检查素材、导入粗剪、放入时间线
- 处理字幕、画面精修、导出和项目记录
- 自动粗剪逻辑交给 `volc-asr`

## 目录结构

```text
yichen-skills/
├─ summary/
│  └─ SKILL.md
├─ x-article-draft-uploader/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  └─ scripts/
│     ├─ export_x_cookies_from_chrome.py
│     ├─ parse_markdown.py
│     └─ upload_markdown_to_x_article.py
├─ wechat-local-vault/
│  ├─ SKILL.md
│  ├─ README.md
│  └─ scripts/
│     ├─ decrypt_all_dbs.py
│     ├─ export_chat.py
│     ├─ extract_keys.py
│     ├─ list_contacts.py
│     ├─ search_sns.py
│     └─ wechat_digest.py
├─ mac-wechat-dual-open/
│  ├─ SKILL.md
│  ├─ scripts/
│  │  └─ wechat_dual_open.py
│  └─ references/
│     └─ reliability-and-risks.md
├─ douyin-fetcher/
│  ├─ SKILL.md
│  └─ scripts/
│     └─ download.py
├─ xiaohongshu-fetch/
│  ├─ SKILL.md
│  └─ scripts/
│     └─ fetch.py
├─ volc-asr/
│  ├─ SKILL.md
│  └─ scripts/
│     └─ transcribe.py
├─ yichen-video-content/
│  ├─ SKILL.md
│  └─ references/
│     └─ title-formulas.md
├─ dbs-content/
│  └─ SKILL.md
├─ jianying-editor/
│  └─ SKILL.md
├─ README.md
├─ README.zh.md
├─ THIRD_PARTY_NOTICES.md
├─ LICENSE
└─ .gitignore
```

## 环境要求

- Claude Code / Codex CLI（支持加载本地 skills）
- Python Playwright（`x-article-draft-uploader` 必需）
- Python 3.9+
- 依赖：
  - X 文章草稿：`pip install playwright pycryptodome && python3 -m playwright install chromium`
  - 微信本地解析：`pip install pycryptodome zstandard`
  - 微信双开：`pip install Pillow`
  - 抖音抓取：`pip install playwright requests && python3 -m playwright install chromium`
  - 小红书抓取：`pip install requests`
  - 火山 ASR 粗剪：`pip install requests`，并安装本机 `ffmpeg` / `ffprobe`

## 安装方式

把仓库内容复制到本地 skills 目录：

- 常见 Claude 路径：`~/.claude/skills/`
- 常见 Agents 路径：`~/.agents/skills/`
- 如果你有自定义技能目录，也可以使用自定义路径

建议保持目录名不变：
- `summary`
- `x-article-draft-uploader`
- `wechat-local-vault`
- `mac-wechat-dual-open`
- `douyin-fetcher`
- `xiaohongshu-fetch`
- `volc-asr`
- `yichen-video-content`
- `dbs-content`
- `jianying-editor`

## 3 分钟快速上手

### A）启用 `summary`

1. 确保 `summary/SKILL.md` 在已加载的 skills 路径里
2. 新开会话后输入 `/summary`
3. 确认输出写入 Obsidian 目录（示例路径通常是 `<OBSIDIAN_VAULT>/...`）

### B）启用 `x-article-draft-uploader`

1. 安装 Python Playwright：`pip3 install playwright pycryptodome && python3 -m playwright install chromium`
2. 确认 Chrome 已经登录 X
3. 直接说“把这篇 Markdown 上传到 X Articles 草稿”，或手动运行脚本
4. Skill 会新建干净草稿，第一张图作为封面，正文图片按原文位置插入
5. 详细命令见 [x-article-draft-uploader/README.md](./x-article-draft-uploader/README.md)

### C）启用 `mac-wechat-dual-open`

1. 安装 Python 依赖：`pip3 install Pillow`
2. 在 Claude Code 中说"帮我微信双开"或 "WeChat dual open"
3. 脚本会自动创建第二个微信（`~/Applications/WeChat-2.app`）并改蓝色图标
4. 详细命令见 `mac-wechat-dual-open/SKILL.md`

### D）启用 `wechat-local-vault`

1. 安装 Python 依赖：`pip3 install pycryptodome zstandard`
2. 在 Claude Code 或 Codex 中说"微信解析"、"导出聊天"或"收藏夹整理"
3. 首次运行会引导你完成密钥提取，并从九种玩法里选择当前要启用的工作流
4. 如果不确定，默认从"聊天记录解析 + 朋友圈解析 + 收藏夹整理"开始
5. 后续使用自动生成对应的解析报告或草案
6. 详细说明见 [wechat-local-vault/README.md](./wechat-local-vault/README.md)

### E）启用自媒体视频工作流

1. 安装 Playwright、requests 和 ffmpeg
2. 用 `douyin-fetcher` 或 `xiaohongshu-fetch` 保存对标素材
3. 用 `volc-asr` 做转写、字幕或口播粗剪
4. 用 `yichen-video-content` 和 `dbs-content` 诊断对标稿和自己的初稿
5. 用 `jianying-editor` 做剪映/CapCut 导入、字幕、精修和导出

## X Cookie 处理

本仓库不包含真实凭据，也不再提供需要手动填写的 cookie 模板。

`x-article-draft-uploader` 会从本机 Chrome 临时导出 X cookies 到 Playwright 可用的 JSON 文件：

```bash
python3 ~/.codex/skills/x-article-draft-uploader/scripts/export_x_cookies_from_chrome.py --output /tmp/x_current_cookies.json
```

这个临时文件是敏感文件，用完可以删除：

```bash
rm -f /tmp/x_current_cookies.json
```

`.gitignore` 已默认忽略 `**/cookies.json`。

## 安全说明

- 不包含真实 token/cookie
- 历史缓存类目录默认不追踪
- 个人绝对路径已替换为通用写法
- 第三方 AppID、AppToken、TableID、bucket 名和 ASR token 必须通过环境变量或私有配置提供

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

本仓库仅用于个人学习和非商业个人工作流使用。未经作者明确书面许可，不得用于商业服务、客户交付、付费产品、公司内部工具包、市场分发包、课程资料或任何营利目的。

如果你为了个人学习而 Fork，至少保留：
- `README.md`
- `README.zh.md`
- `LICENSE`
- `.gitignore`
- `THIRD_PARTY_NOTICES.md`
- `x-article-draft-uploader/README.md`

不要把本仓库重新打包或重新发布为公开 Skill 套件。并明确提醒用户不要上传真实凭据或隐私数据。

## 致谢

本仓库的 X Articles 草稿上传流程和 Markdown 解析思路，参考了以下项目：

- `wshuyi/x-article-publisher-skill`
  - 仓库：<https://github.com/wshuyi/x-article-publisher-skill>
  - 文档：<https://github.com/wshuyi/x-article-publisher-skill/blob/main/README_CN.md>
  - 许可：MIT

`wechat-local-vault` 的微信数据库解密方法参考了以下项目：

- `zhuyansen/wx-favorites-report`
  - 仓库：<https://github.com/zhuyansen/wx-favorites-report>
  - 作者：zhuyansen
  - 许可：MIT
  - 具体参考：frida hook `CCKeyDerivationPBKDF` 密钥提取方法和 SQLCipher 4 分页解密逻辑

`mac-wechat-dual-open` 的微信双开方法参考了：

- [@koffuxu](https://x.com/koffuxu) — 原始教程 (2026-04)：[Mac 微信双开最完美方案](https://x.com/koffuxu/status/2043110831584690427)
- [@MinLiBuilds](https://x.com/MinLiBuilds) — 独立验证 (2026-04)

详细说明见 `THIRD_PARTY_NOTICES.md`。

## 合规边界

- 本项目与 X（Twitter）、微信（腾讯）官方无隶属、背书或合作关系。
- 本仓库仅限个人学习和非商业个人工作流使用。
- 未经作者书面许可，禁止商用、客户交付、转售、付费分发、市场打包、课程打包或公司内部部署。
- 使用者需自行遵守 X 平台条款、自动化政策及当地法律法规。
- `wechat-local-vault` 仅限个人使用——仅可解密和读取本人的聊天数据，不得用于侵犯他人隐私。
- 请勿把真实账号凭据（如 `cookies.json`、`wechat-keys.json`）上传到公开仓库。
- 请勿上传真实聊天记录、微信数据库、客户数据、私人笔记、API key、本机路径或其他个人隐私数据。

## License

Personal Learning and Non-Commercial Use License。见 [LICENSE](./LICENSE)。
