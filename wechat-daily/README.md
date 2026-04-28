# wechat-daily

微信数字资产沉淀助手 — Claude Code Skill

从微信 Mac 4.x 的本地加密数据库提取聊天记录、朋友圈和收藏夹内容，用 AI 生成日报、复盘、客户跟进和知识库整理素材。

## 功能

- 自动解密微信本地数据库（AES-256-CBC + SQLCipher 4）
- 可配置监控指定群聊、联系人、朋友圈对象和收藏夹整理偏好
- AI 生成精炼日报，按主题分类（工具技巧、行业动态、观点碰撞等）
- 首次触发时展示三大类九种玩法：聊天记录、朋友圈、收藏夹
- 支持指定日期查询

### 三大类九种玩法

聊天记录：
- 微信群聊日报沉淀：沉淀每日群聊精华到 Obsidian 或飞书。
- 大佬对话复盘：分析关键好友对话，优化下一轮沟通策略。
- 重点事项跟进与提醒：从群聊和私聊中梳理待办、会议和截止时间草案。
- 客户管理沉淀：整理重点客户状态、下一步动作和飞书多维表格字段建议。

朋友圈：
- 竞品监督与客户需求抓取：形成朋友圈日报、机会提醒和响应建议。
- 个人 IP 诊断：分析自己的内容主题、发布节奏、互动和印象标签。
- 高价值内容提炼：提取朋友圈中的工具、资源、认知和选题。

收藏夹：
- 收藏夹大扫除到知识库：生成分类体系、摘要、标签和选题库建议。
- 收藏复活提醒：生成每周复活清单、推荐阅读顺序和提醒草案。

详细的首次引导问题模板以 `SKILL.md` 为准。本 Skill 只能在用户首次触发时展示引导，不能在安装瞬间自动弹窗。

## 安装

### 方式一：从 GitHub 安装（推荐）

```bash
npx skills add <your-github-username>/wechat-daily
```

### 方式二：手动安装

将本目录复制到 `~/.claude/skills/wechat-daily/`

## 依赖

- macOS + 微信 Mac 4.x
- Python 3.9+
- pycryptodome（数据库解密）
- zstandard（消息解压）
- frida + frida-tools（仅首次密钥提取时需要）

安装 Python 依赖：

```bash
pip3 install pycryptodome zstandard
```

首次提取密钥时还需安装 frida：

```bash
pip3 install frida frida-tools
```

## 使用

安装后在 Claude Code 中说 **"日报"** 即可触发。

### 首次使用

1. 说"日报"，Skill 会自动进入配置引导
2. 运行密钥提取脚本（需要登录微信；如需朋友圈/收藏，捕获期间手动打开「朋友圈」和「收藏」）
3. 选择要启用的玩法；不确定时默认推荐“微信群聊日报 + 朋友圈日报 + 收藏夹大扫除”
4. 选择要监控的群聊、联系人、朋友圈对象或收藏夹整理偏好
5. 自动生成首份日报或对应玩法的输出草案

### 日常使用

- **"日报"** — 生成昨天 08:00 到今天 08:00 的日报
- **"4月16日的日报"** — 生成指定日期的日报
- **"微信日报 2026-04-16"** — 同上
- **"朋友圈日报"** — 生成朋友圈监督或高价值内容提炼
- **"收藏夹整理"** — 生成收藏夹分类、摘要和标签建议
- **"客户跟进"** — 生成客户状态摘要和下一步动作建议

## 配置文件

### ~/.config/wechat-daily.json（用户配置）

```json
{
  "wxid": "<wxid>",
  "db_base_path": "~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<wxid>/db_storage",
  "monitor_groups": ["群名1", "群名2"],
  "monitor_contacts": [],
  "report_dir": "~/Documents/wechat-daily",
  "time_mode": "8am_to_8am"
}
```

### ~/.config/wechat-keys.json（密钥，自动生成）

```json
{
  "message_0": "hex_key",
  "contact": "hex_key",
  "session": "hex_key",
  "sns": "hex_key",
  "favorite": "hex_key"
}
```

## 安全说明

- 所有数据仅在本地处理，不上传任何服务器
- 密钥存储在本地 `~/.config/` 目录
- frida 仅在首次提取密钥时使用，提取后不再需要
- 建议定期更换密钥（重新运行 extract_keys.py）

## 文件结构

```
wechat-daily/
├── SKILL.md              # Skill 定义（流程、格式规则）
├── README.md             # 本文件
└── scripts/
    ├── extract_keys.py   # frida 密钥提取（首次使用）
    ├── wechat_daily.py   # 主脚本（解密 + 提取 + 原始报告）
    └── list_contacts.py  # 列出群聊/联系人（辅助配置）
```

## 技术原理

微信 Mac 4.x 使用 SQLCipher 4 加密本地数据库：
- AES-256-CBC 分页加密（page_size=4096, reserve=80）
- PBKDF2 密钥派生（256000 轮）
- WeChat 4.1.x 常见为按库独立密钥，`sns.db` 和 `favorite.db` 需要打开对应页面才会触发加载
- 通过 frida hook `CCKeyDerivationPBKDF` 在运行时捕获密钥，再按数据库 salt 匹配
- 部分消息内容使用 ZSTD 压缩

## License

Personal Learning and Non-Commercial Use License. See the repository root `LICENSE`.
