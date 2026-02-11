# yichen-skills

一个面向内容创作者的技能仓库，核心目标是：

1. 把 Claude Code 对话自动沉淀到 Obsidian（`summary`）
2. 把 Obsidian/Markdown 内容高效发布到 X（`x-publisher`）

## 仓库包含什么

### 1) `summary`
- 用途：提炼当前对话精华并保存到 Obsidian
- 触发词示例：`/summary`、保存对话、导出精华、沉淀到 Obsidian
- 关键能力：
  - 自动过滤无效对话
  - 输出结构化笔记（背景、核心内容、解决方案、关键要点、相关）
  - 适合做长期知识库沉淀

### 2) `x-publisher`
完整发布套件，包含：
- `x-article-publisher`：发布长文到 X Articles
- `x-post-with-images`：发布图文推文
- `x-post-with-video`：发布视频推文
- `x-quote-tweet`：引用推文发布
- `scripts/`：解析 Markdown、剪贴板复制等通用脚本

## 目录结构

```text
yichen-skills/
├─ summary/
│  └─ skill.md
├─ x-publisher/
│  ├─ cookies.template.json
│  ├─ scripts/
│  ├─ x-article-publisher/
│  │  ├─ cookies.template.json
│  │  ├─ skill.md
│  │  ├─ scripts/
│  │  └─ references/
│  ├─ x-post-with-images/
│  ├─ x-post-with-video/
│  └─ x-quote-tweet/
├─ README.md
├─ LICENSE
└─ .gitignore
```

## 环境要求

- Claude Code / Codex CLI（可加载本地 skills）
- Playwright MCP（`x-publisher` 需要浏览器自动化）
- Python 3.9+
- 依赖（按你的系统安装）：
  - Windows: `pip install Pillow pywin32 clip-util`
  - macOS: `pip install Pillow pyobjc-framework-Cocoa`

## 安装方式

把这个仓库内容复制到你的 skills 目录（根据你本机实际环境）：

- 常见 Claude 路径：`~/.claude/skills/`
- 常见 Agents 路径：`~/.agents/skills/`
- 若你有自定义技能目录，也可放在你的自定义路径

建议保持目录名不变：
- `summary`
- `x-publisher`

## 3 分钟快速上手

### A. 启用 `summary`

1. 确保 `summary/skill.md` 在你的技能目录里
2. 新开会话后输入：`/summary`
3. 确认生成的内容写入你的 Obsidian 目录（示例路径通常是 `E:/obsidian/...`）

### B. 启用 `x-publisher`

1. 先配置 Cookie（见下一个章节）
2. 确保 Playwright MCP 已连通
3. 在会话中按场景调用：
   - 发布长文：触发 `x-article-publisher`
   - 发图文：触发 `x-post-with-images`
   - 发视频：触发 `x-post-with-video`
   - 引用推文：触发 `x-quote-tweet`

## Cookie 配置（必须）

本仓库不包含任何真实凭据，只提供模板。

1. 复制模板文件：
   - `x-publisher/cookies.template.json` -> `x-publisher/cookies.json`
   - `x-publisher/x-article-publisher/cookies.template.json` -> `x-publisher/x-article-publisher/cookies.json`
2. 把你自己的 `auth_token`、`ct0` 填进去
3. 不要把真实 `cookies.json` 提交到任何 Git 仓库

`.gitignore` 已默认忽略 `**/cookies.json`。

## 安全说明

- 已移除真实 token/cookie
- 已移除历史快照和缓存目录（如 `.versions`、`__pycache__`）的提交追踪
- 已替换个人绝对路径示例为通用写法

如果你曾经把真实 Cookie 暴露到公开仓库，请立即轮换（刷新）Cookie。

## 常见问题

### 1) 为什么我触发不到 skill？
- 检查 skill 目录是否放在当前工具实际加载的路径
- 重启会话后再触发
- 检查 `skill.md` frontmatter 的 `name/description` 是否完整

### 2) 为什么 x 发布失败？
- 优先检查 Cookie 是否过期
- 检查 Playwright MCP 是否连接正常
- 检查本地 Markdown/图片路径是否存在

### 3) 我能改成自己的 Obsidian 路径吗？
- 可以，直接修改 skill 里的示例路径即可
- 示例里的 `E:/obsidian/...` 仅用于演示

## 给二次分发者的建议

如果你要 Fork 或二次分享，建议保留以下文件：

- `README.md`
- `LICENSE`
- `.gitignore`
- 两个 `cookies.template.json`

并且在你自己的文档里再次强调：
- 只上传模板，绝不上传真实 Cookie

## License

MIT

