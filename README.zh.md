# yichen-skills

[English](./README.md) | 中文

一个面向内容创作者的技能仓库，帮助你用 Claude Code 打通“沉淀知识 + 发布内容”的完整流程。

## 这个仓库能做什么

1. 把 Claude Code 对话沉淀为结构化 Obsidian 笔记（`summary`）
2. 把 Obsidian/Markdown 内容发布到 X（`x-publisher`）
3. 提供对 Windows 用户非常友好的 X Articles 上传流程，并具备极高正确率

## 包含的技能

### 1) `summary`
- 用途：提炼当前对话精华并保存到 Obsidian
- 常见触发词：`/summary`、保存对话、导出精华
- 关键能力：
  - 自动过滤低价值过渡内容
  - 输出结构化笔记（背景、核心内容、解决方案、关键要点、相关）
  - 适合长期知识沉淀

### 2) `x-publisher`
聚焦“长文发布”的发布套件，包含：
- `x-article-publisher`：发布长文到 X Articles
- `scripts/`：Markdown 解析和剪贴板处理等通用工具

专门针对 Windows 体验做了优化，路径兼容性强，上传推特文章有极高正确率。

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
│  └─ （仅保留长文发布能力）
├─ README.md
├─ README.zh.md
├─ THIRD_PARTY_NOTICES.md
├─ LICENSE
└─ .gitignore
```

## 环境要求

- Claude Code / Codex CLI（支持加载本地 skills）
- Playwright MCP（`x-publisher` 必需）
- Python 3.9+
- 依赖：
  - Windows: `pip install Pillow pywin32 clip-util`
  - macOS: `pip install Pillow pyobjc-framework-Cocoa`

## 安装方式

把仓库内容复制到本地 skills 目录：

- 常见 Claude 路径：`~/.claude/skills/`
- 常见 Agents 路径：`~/.agents/skills/`
- 如果你有自定义技能目录，也可以使用自定义路径

建议保持目录名不变：
- `summary`
- `x-publisher`

## 3 分钟快速上手

### A）启用 `summary`

1. 确保 `summary/skill.md` 在已加载的 skills 路径里
2. 新开会话后输入 `/summary`
3. 确认输出写入 Obsidian 目录（示例路径通常是 `E:/obsidian/...`）

### B）启用 `x-publisher`

1. 先配置 Cookie（见下节）
2. 确认 Playwright MCP 已连接
3. 按场景调用：
   - 发布长文：触发 `x-article-publisher`

## Cookie 配置（必需）

本仓库不包含真实凭据，只提供模板。

1. 复制模板：
   - `x-publisher/cookies.template.json` -> `x-publisher/cookies.json`
   - `x-publisher/x-article-publisher/cookies.template.json` -> `x-publisher/x-article-publisher/cookies.json`
2. 填入你自己的 `auth_token` 和 `ct0`
3. 不要把真实 `cookies.json` 提交到 Git 仓库

`.gitignore` 已默认忽略 `**/cookies.json`。

## 安全说明

- 不包含真实 token/cookie
- 历史缓存类目录默认不追踪
- 个人绝对路径已替换为通用写法

如果你曾在公开仓库暴露过 Cookie，请立即轮换。

## 常见问题

### 为什么 skill 没触发？
- 检查 skill 是否放在“当前真实加载路径”
- 重启会话再试
- 检查 `skill.md` 里的 frontmatter（`name` / `description`）

### 为什么发布到 X 失败？
- 优先检查 Cookie 是否过期
- 检查 Playwright MCP 是否连通
- 检查 Markdown/图片路径是否存在

### Obsidian 路径可以改吗？
- 可以，直接改 skill 里的示例路径
- `E:/obsidian/...` 只是示例

## 二次分发建议

如果你要 Fork 或二次分发，建议至少保留：
- `README.md`
- `README.zh.md`
- `LICENSE`
- `.gitignore`
- `THIRD_PARTY_NOTICES.md`
- 两个 `cookies.template.json`

并明确提醒用户不要上传真实凭据。

## 致谢

本仓库的 X 发布流程与工程实践，参考了以下项目：

- `wshuyi/x-article-publisher-skill`
  - 仓库：<https://github.com/wshuyi/x-article-publisher-skill>
  - 文档：<https://github.com/wshuyi/x-article-publisher-skill/blob/main/README_CN.md>
  - 许可：MIT

详细说明见 `THIRD_PARTY_NOTICES.md`。

## 合规边界

- 本项目与 X（Twitter）官方无隶属、背书或合作关系。
- 使用者需自行遵守 X 平台条款、自动化政策及当地法律法规。
- 请勿把真实账号凭据（如 `cookies.json`）上传到公开仓库。

## License

MIT
