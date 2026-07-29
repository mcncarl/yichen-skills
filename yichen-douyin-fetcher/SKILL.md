---
name: yichen-douyin-fetcher
description: |
  抓取抖音单条视频或博主全部公开作品，默认下载至少 1080p 的兼容 H.264 视频，优先从平台字幕生成纯中文口播稿，无字幕时再调用 ASR。使用视频标题创建中文可读目录。触发词：「下载抖音视频」「抓取抖音」「douyin」「批量下载博主视频」「抓取博主全部作品」「生成口播稿」「分析口播稿」。
---

# 抖音视频与中文口播稿

通过 Playwright 拦截抖音页面已签名的接口，串行下载无水印视频，并按“平台字幕 → 独立 ASR Skill”顺序生成中文口播稿。核心脚本不依赖 Codex 专属浏览器接口，可由 Codex、Hermes 或其他能运行本地终端的 Agent 调用。

## 首次安装与自检

把当前 `SKILL.md` 所在目录解析为 `SKILL_DIR`，保留整个 Skill 目录及内部相对路径。首次安装后运行：

```bash
python3 -m pip install -r "$SKILL_DIR/requirements.txt"
python3 "$SKILL_DIR/scripts/doctor.py"
python3 "$SKILL_DIR/scripts/download.py" --help
python3 "$SKILL_DIR/scripts/download_author.py" --help
```

使用仍在安全支持期内的 Python 3.10+。脚本优先使用 Playwright 已安装的 Chromium，并在其缺失时回退到本机 Google Chrome；两者都不可用时再运行 `python3 -m playwright install chromium`。`doctor.py` 只做本机依赖和浏览器启动检查，不访问抖音、不写登录态，也不自动安装系统级 `ffmpeg`。自检失败时先按输出提示补齐依赖，不要继续下载。

## 输出契约

用户可见目录只保留视频和中文口播稿：

```text
抖音_博主_<昵称>_[短UID]/
└── YYYY-MM-DD_<视频标题>_[短视频ID]/
    ├── 视频.mp4
    └── 中文口播稿.txt
```

将抓取清单、断点状态、ASR 音频、缓存和待查询任务保存在 `~/.local/share/yichen-douyin-fetcher/`，不要写入用户内容目录。标题中的文件系统保留字符转换为全角字符，并按 UTF-8 字节安全截断；短视频 ID 用于防止同名冲突。

## 质量规则

- 默认选择分辨率最高、码率最高的兼容 H.264 码流。
- 主候选下载或校验失败时，按质量顺序尝试其他不低于 1080p 的兼容候选及备用地址。
- 短边必须至少 1080、长边必须至少 1920；下载后再用 `ffprobe` 复验分辨率和 H.264 编码。
- 源作品没有 1080p 时，将该作品记录为失败；不得静默降级到 720p/540p。
- 只有 `视频.mp4` 和非空 `中文口播稿.txt` 都存在，才可记录为完成。

## 下载单条视频

```bash
python3 "$SKILL_DIR/scripts/download.py" "<抖音链接>" [输出根目录]
```

默认输出根目录为 `~/Downloads`。只检查详情、不生成用户产物时使用 `--metadata-only`；机器元数据仍写入私有状态目录。

## 扫描博主与批量处理

先只生成机器清单，确认作品数量和容量：

```bash
python3 "$SKILL_DIR/scripts/download_author.py" "<博主主页、作品链接或分享文案>"
```

用户确认清单后，使用脚本打印的同一创作者输出目录按清单续跑。脚本固定清单中的作品 ID，只重新获取这些作品的临时媒体数据，不重新选择作品：

```bash
python3 "$SKILL_DIR/scripts/download_author.py" "<原链接>" --download --resume-only --output-dir "<创作者输出目录>"
```

常用参数：

- `--output-dir <目录>`：正常扫描时指定保存根目录，脚本会在其下创建创作者目录；`--resume-only` 时传入已经打印的创作者目录。
- `--limit 10`：对当前已捕获的主页作品按发布时间排序后固定前 10 条；不代表完整枚举，也不承诺等同于界面置顶顺序。
- `--resume-only`：固定已确认私有清单中的作品 ID，只补取其当前临时媒体数据；必须与 `--download --output-dir` 一起使用。
- `--delay 2`：相邻作品处理间隔秒数。
- `--headed`：打开可见浏览器，供登录或验证码处理。
- `--no-persistent-session`：本次忽略本机持久登录授权策略。
- `--direct`：显式绕过系统代理直连抖音。默认尊重系统代理；只有页面在代理下空白、脚本明确提示，且用户确认允许本次直连后才使用，不得自动追加。

重复运行时，只有视频和口播稿都完整才跳过；只有视频时继续获取平台字幕或执行 ASR，不重新下载。使用 `.part` 临时文件并在媒体校验通过后原子替换。

## 中文口播稿

本 Skill 不在用户目录生成字幕、元数据或分析 JSON。按以下顺序生成口播稿：

1. 复用已存在的非空 `中文口播稿.txt`。
2. 优先下载抖音原生中文字幕；原始语言字幕只有检测到中文内容时才使用。在私有状态目录缓存原文，去掉序号和时间戳后写入 `中文口播稿.txt`。
3. 没有可用平台字幕时，调用 `yichen-volc-asr --transcribe-only`；把提取音频、原始结果和缓存保存在私有状态目录，只把纯口播文字写入用户目录。

在交付时读取口播稿，并在对话中按每条视频给出：

- 一句话内容摘要。
- 分段结构：原文、段落摘要、位置（开头/中间/高潮/结尾）、是否爆点、钩子类型（悬念/冲突/数字/情感/其他）。
- 整体叙事结构与开头钩子分析。
- 关键爆点和可复用表达。

批量任务再总结共同选题、常用钩子和结构规律。分析只在对话中呈现，不另建分析文件。

只有回退到 ASR 时才要求：

1. 已安装 `yichen-volc-asr`，或通过 `YICHEN_VOLC_ASR_SCRIPT` 指定脚本。
2. 已从环境变量或私有 runner 注入 TOS 与火山 ASR 配置。
3. 不得把 TOS、ASR Token、Cookie 或 API Key 写入 Skill、命令行、普通记忆或日志。
4. 火山链路会把提取的音频上传至用户配置的 TOS/火山服务；没有用户授权或配置时停止，不得假装已生成口播稿。

缺少 ASR Skill、私有配置或上传授权时，不阻止合格视频下载；没有平台字幕的作品记录为“中文口播稿待转写”，不得记录为完成。配置补齐后重复运行，只补口播稿，不重复下载视频。

平台字幕只有在作品详情接口中出现时，使用同一已授权登录态补取详情；非中文字幕不得伪装成 `中文口播稿.txt`，改走 ASR 回退或记录待转写。

## 登录边界

匿名主页接口可能返回空正文。失败后用 `--headed`，让用户在临时浏览器中登录并刷新当前页面。

如本机存在 `~/.config/yichen-douyin-fetcher/policy.json` 且 `persistent_login_authorized` 为 `true`，脚本自动加载其中的 `storage_state_path`，并在可见登录成功后更新登录态。该授权只属于当前机器，不得随 Skill 分发。没有策略文件时，首次保存可复用 Cookie 前必须解释其持久性并取得明确确认。

只访问受信任的抖音页面域名；向媒体 CDN 发送 Referer 前移除查询参数和片段，不发送 Cookie。媒体响应为 HTML、声明长度不匹配或下载后校验失败时尝试备用地址，所有地址失败才记录失败。

若错误提示系统代理可能导致页面空白，先向用户说明 `--direct` 会绕过当前系统代理；获得明确确认后，才用相同命令追加 `--direct` 重试。不要自动禁用代理，也不要通过轮换代理规避平台限制。

## 依赖

- Python 3.10+
- `requests`、`playwright`
- Playwright Chromium 或本机 Google Chrome
- `ffmpeg`、`ffprobe`
- 独立的 `yichen-volc-asr` Skill 及用户私有配置

## 跨 Agent 安装

- Codex：把完整目录安装到 `$CODEX_HOME/skills/yichen-douyin-fetcher/`，新开任务后再触发。
- HermesAgent：把完整目录安装到 `~/.hermes/skills/social-media/yichen-douyin-fetcher/`。
- 其他 Agent：安装到其 Skill 搜索目录，并确保可调用本地终端。

不要分发 `~/.config/yichen-douyin-fetcher/`、`~/.local/share/yichen-douyin-fetcher/`、视频、口播稿、Cookie、Token 或任何本机生成文件。

## 完成边界

- “全部作品”只指当前账号在网页端可见的公开作品。
- `scan_complete` 为 false 时不得宣称枚举完成。
- 主页扫描因超时、空转或登录超时停止时视为部分枚举并返回非零状态；显式 `--limit` 属于用户要求的有界处理。
- 视频低于 1080p、媒体校验失败、口播稿为空或 ASR 执行失败时记录为失败；仅因 ASR 未配置或未获上传授权时记录为待转写。
- 不下载私密、已删除、地区受限或版权限制内容；遵守平台条款和内容权利。

## 维护验证

修改或发布前运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "$SKILL_DIR/tests" -v
python3 "<skill-creator-dir>/scripts/quick_validate.py" "$SKILL_DIR"
python3 "$SKILL_DIR/scripts/doctor.py"
```
