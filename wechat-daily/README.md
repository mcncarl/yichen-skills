# wechat-daily

微信聊天日报生成器 — Claude Code Skill

从微信 Mac 4.x 的本地加密数据库提取聊天记录，用 AI 生成每日精华摘要。

## 功能

- 自动解密微信本地数据库（AES-256-CBC + SQLCipher 4）
- 可配置监控指定群聊和联系人
- AI 生成精炼日报，按主题分类（工具技巧、行业动态、观点碰撞等）
- 支持指定日期查询

## 安装

### 方式一：从 GitHub 安装（推荐）

```bash
npx skills add mcncarl/yichen-skills
```

安装后在 Claude Code 中手动启用 wechat-daily skill。

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
2. 运行密钥提取脚本（需要登录微信）
3. 选择要监控的群聊和联系人
4. 自动生成首份日报

### 日常使用

- **"日报"** — 生成昨天 08:00 到今天 08:00 的日报
- **"4月16日的日报"** — 生成指定日期的日报
- **"微信日报 2026-04-16"** — 同上

## 配置文件

### ~/.config/wechat-daily.json（用户配置）

```json
{
  "wxid": "wxid_xxx",
  "db_base_path": "~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_xxx/db_storage",
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
  "session": "hex_key"
}
```

## 安全与隐私说明

- **所有数据仅在本地处理**，不上传任何服务器
- 密钥存储在本地 `~/.config/` 目录，不包含在本项目中
- frida 仅在首次提取密钥时使用，提取后不再需要
- 本项目不收集、不存储、不上传任何用户聊天数据
- 建议定期更换密钥（重新运行 extract_keys.py）

## 法律合规声明

本项目仅供个人学习和研究使用。使用者需注意：

1. **仅限处理自己的聊天数据**：解密和读取的数据库必须属于使用者本人
2. **不得用于侵犯他人隐私**：未经他人同意，不得提取、传播他人的聊天记录
3. **遵守当地法律法规**：使用 frida 等工具需遵守相关法律，不得用于非法目的
4. **微信用户协议**：本工具涉及的操作可能违反微信用户协议，使用者需自行承担相关风险
5. **数据安全**：生成的日报可能包含敏感信息，请妥善保管，不要公开发布包含他人隐私的内容

## 致谢

本项目在以下开源项目的基础上开发，感谢原作者的贡献：

- **[wx-favorites-report](https://github.com/zhuyansen/wx-favorites-report)** — 微信收藏可视化工具，本项目的 frida hook 密钥提取方法（`CCKeyDerivationPBKDF` 拦截）和 SQLCipher 4 解密逻辑参考了该项目的实现

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
- 通过 frida hook `CCKeyDerivationPBKDF` 在运行时捕获密钥
- 部分消息内容使用 ZSTD 压缩

## License

MIT
