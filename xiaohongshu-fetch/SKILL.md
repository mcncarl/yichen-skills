---
name: xiaohongshu-fetch
description: 抓取小红书笔记（视频/图文）并按指令沉淀到飞书多维表格。视频笔记→视频对标库（含ASR转写+LLM分段）；图文笔记→社媒爆款选题库（默认）或指定表格。触发：沉淀/入库/保存+小红书链接，或直接发送小红书链接+说明意图。
---

# 小红书抓取与沉淀

## 一键抓取脚本（优先使用）

先用本地脚本完成抓取，不需要手动 curl 和解析页面：

```bash
python3 xiaohongshu-fetch/scripts/fetch.py "<小红书笔记链接>" [输出目录]
```

**默认输出目录：** `~/Downloads/xhs_<note_id>`

**输出文件：**
- `xhs_<note_id>.html`：网页快照
- `xhs_<note_id>.metadata.json`：标题、正文、作者、发布时间、互动数据、标签、章节、媒体地址等元数据
- 视频笔记：`xhs_<note_id>.mp4`、`xhs_<note_id>.<字幕语言>.srt`、`xhs_<note_id>.transcript.txt`
- 图文笔记：`images/` 下保存图片

**快速检查链接能不能解析：**

```bash
python3 xiaohongshu-fetch/scripts/fetch.py "<小红书笔记链接>" [输出目录] --skip-media
```

脚本会优先解析网页里的 `window.__INITIAL_STATE__`，自动处理 `undefined`、`video.mediaV2` / `video.consumer.mediaV2`、视频 `masterUrl/backupUrls`、字幕和图片地址。重复运行时，已存在的大视频/字幕/图片会自动跳过。只有脚本失败时，再进入下面的手工抓取/沉淀流程。

## 两条链路

用户发送小红书链接后，根据笔记类型和用户意图，走不同路径：

```
用户发链接
    │
    ├── 用户说"沉淀"或"入库"
    │       │
    │       ├── 视频笔记 → 视频对标库（AppToken/TableID 从私有配置读取）
    │       │       ① 下载视频 → ② volc-asr 转写 → ③ LLM分段 → ④ 写入bitable → ⑤ 按用户许可清理临时文件
    │       │
    │       └── 图文笔记 → 社媒爆款选题库（AppToken/TableID 从私有配置读取）
    │               若用户指定其他目标 → 按指定去沉淀
    │
    └── 用户只发链接不提沉淀
            抓取元数据+图片，输出结构化摘要，不写入bitable
```

---

## 配置读取

不要把 Cookie、AppToken、TableID 或飞书链接硬编码进 AGENTS、skill、普通记忆或日志。

执行写入前，从用户指定的私有配置文件或环境变量读取目标表配置。推荐环境变量名：

| 用途 | AppToken 环境变量 | TableID 环境变量 |
|------|-------------------|------------------|
| 视频对标库 | `XHS_VIDEO_BENCHMARK_APP_TOKEN` | `XHS_VIDEO_BENCHMARK_TABLE_ID` |
| 社媒爆款选题库 | `XHS_SOCIAL_TOPIC_APP_TOKEN` | `XHS_SOCIAL_TOPIC_TABLE_ID` |
| 学习库 | `XHS_LEARNING_APP_TOKEN` | `XHS_LEARNING_TABLE_ID` |

如果当前环境没有配置，先说明缺少哪一项，不要从历史消息或普通记忆里猜。

---

## 链路一：视频笔记 → 视频对标库

**目标 bitable：** 视频对标库。AppToken 和 TableID 从私有配置或环境变量读取，不在 skill 中硬编码。

### Step 1：抓取页面，提取视频直链和元数据

优先使用「一键抓取脚本」。手动处理时再参考本节。

参考「核心方法」提取：
- title、desc、user.nickname、time、interactInfo
- `video.media.stream.h264[0].masterUrl`（视频直链）

### Step 2：下载视频

从 Step 1 已拿到 `video.media.stream.h264[0].masterUrl`，直接 curl 下载：

```bash
curl -L -o "/tmp/video.mp4" "<视频直链>"
```

下载路径：`/tmp/video.mp4`

### Step 3：调用 volc-asr 转写（关键步骤）

**必须调用本地或云端已安装的 volc-asr skill，转写脚本位于：**

- 仓库内：`python3 volc-asr/scripts/transcribe.py '<视频文件路径>'`
- 已安装 skill：`python3 <skills-dir>/volc-asr/scripts/transcribe.py '<视频文件路径>'`

执行前确保环境变量已配置：
```bash
export TOS_ACCESS_KEY="..."
export TOS_SECRET_KEY="..."
export TOS_BUCKET="..."
export VOLC_ASR_TRIAL_APP_ID="..."
export VOLC_ASR_TRIAL_TOKEN="..."
```

不要把真实 AppToken、TableID、Cookie、TOS 密钥或 ASR Token 写进 skill、仓库或普通日志。

### Step 4：LLM 读取转写结果并切分段落

转写完成后，LLM 读取 `.txt` 文件，按以下格式输出 JSON：

```json
{
  "segments": [
    {
      "content": "段落原文",
      "summary": "一句话摘要",
      "position": "开头|中间|高潮|结尾",
      "viral_hook": true,
      "hook_type": "悬念|冲突|数字|情感|null"
    }
  ],
  "structure_analysis": "整体结构一句话描述",
  "opening_analysis": "开头分析",
  "viral_points": ["爆点1", "爆点2"]
}
```

### Step 5：写入视频对标库 bitable

**字段对照：**

| bitable 字段 | 值来源 |
|-------------|--------|
| 来源链接 | 原始笔记 URL |
| 平台 | 小红书 |
| 作者 | user.nickname |
| 发布日期 | time（时间戳→日期格式） |
| 播放量 | interactInfo 查看量（有则填） |
| 点赞数 | interactInfo likedCount |
| 收藏数 | interactInfo.collectedCount |
| 评论数 | interactInfo.commentCount |
| 转发数 | interactInfo.shareCount |
| 正文口播稿 | 所有段落 content 按顺序拼接 |
| 口播稿分析 | structure_analysis + opening_analysis + viral_points 汇总 |
| 内容类型 | 根据正文判断：知识干货/口播种草/故事叙事/观点输出/测评对比/教程分享/热点追评/其他 |

写入 API：
```
POST https://open.feishu.cn/open-apis/bitable/v1/apps/{VIDEO_BENCHMARK_APP_TOKEN}/tables/{VIDEO_BENCHMARK_TABLE_ID}/records
```

### Step 6：清理临时文件

完成转写并写入 bitable 后，说明临时视频和转写文本的位置，询问用户是否清理。只有得到明确允许后才清理，并优先移动到垃圾篓；不要直接 `rm -f`。

---

## 链路二：图文笔记 → 社媒爆款选题库（默认）

**目标 bitable：** 社媒爆款选题库。AppToken 和 TableID 从私有配置或环境变量读取，不在 skill 中硬编码。

### Step 1：抓取页面，提取元数据

优先使用「一键抓取脚本」。手动处理时再参考本节。

参考「核心方法」提取：title、desc、tagList、user.nickname、time、interactInfo

### Step 2：对每张图片做 OCR/描述

对 imageList 每张图：
- 发给 LLM 做图内文字识别 + 内容摘要
- 合并输出：逐页摘要 + 全文还原版

### Step 3：写入社媒爆款选题库 bitable

**字段对照：**

| bitable 字段 | 值来源 |
|-------------|--------|
| 社媒爆款选题库 | 标题（主字段） |
| 标题 | title |
| 来源链接 | 原始笔记 URL |
| 平台 | 小红书 |
| 作者 | user.nickname |
| 日期 | time |
| 一句话摘要 | LLM 根据 desc + 图片内容生成 |
| 文章结构 | LLM 分析图文结构 |
| 启发点 | LLM 提炼核心启发 |
| 内容类型 | 根据正文判断 |
| 标签 | tagList 取前5个 |

写入 API：
```
POST https://open.feishu.cn/open-apis/bitable/v1/apps/{SOCIAL_TOPIC_APP_TOKEN}/tables/{SOCIAL_TOPIC_TABLE_ID}/records
```

---

## 链路二（备选）：用户指定沉淀目标

用户说"沉淀到 XXX 库"或"入库到 XXX"→ 按用户指定的 bitable 创建记录。

---

## 平台识别

| 域名 | 平台 |
|------|------|
| xiaohongshu.com | 小红书 |
| douyin.com | 抖音 |
| bilibili.com | B站 |
| weibo.com | 微博 |
| mp.weixin.qq.com | 公众号 |
| zhihu.com | 知乎 |
| youtube.com | YouTube |

---

## 核心抓取方法

### URL 和认证上下文

- URL 格式：`https://www.xiaohongshu.com/explore/{note_id}?xsec_token=...&xsec_source=pc_user`
- 访问 HTML 时通常需要带有效登录态 Cookie 和 `xsec_token`
- 登录态 Cookie 属于敏感凭证，不要写入 AGENTS、普通记忆、公开文档或日志

### 方法 A：读网页 meta
```bash
curl -L -A 'Mozilla/5.0' '<笔记URL>'
```
提取：og:title、description、og:image、og:video

### 方法 B：解析 `window.__INITIAL_STATE__`（主力）
重点路径：`root.note.noteDetailMap.<note_id>.note` 或 `note.noteDetailMap.<note_id>.note`
优先查：title、desc、type、tagList、user.nickname、interactInfo、video.media.stream、imageList
视频直链优先查：`video.media.stream.h264[0].masterUrl`

---

## 判断规则

- `type == "video"` → 视频笔记，走链路一
- `type == "normal"` 或 `imageList` 有内容 → 图文笔记，走链路二
- `interactInfo` 全为空 → 可能是非公开笔记，标注"互动数据未公开"

---

## 失败处理

- 小红书风控屏蔽 → 换 User-Agent 或加延迟重试
- 页面能打开但脚本提示没有 `INITIAL_STATE` → 重新复制带 `xsec_token` 的完整链接；必要时在浏览器登录后再复制链接
- 视频直链 404 → 尝试 backupUrls
- 视频直链过期 → 重新运行一键抓取脚本刷新 `metadata.json` 和直链
- 没有字幕 → 下载视频后调用 `volc-asr` 转写
- volc-asr 调用失败 → 记录错误，提示用户可手动转写后用"正文口播稿"字段
- bitable write 失败 → 打印完整错误响应，提示检查 token 和表权限

---

## 一句工作流

**视频笔记：抓页面 → curl下载视频直链 → volc-asr转写 → LLM分段 → 写视频对标库 → 按用户许可清理临时文件**
**图文笔记：抓页面 → 图片OCR → LLM摘要 → 写社媒选题库（默认）或指定表格**
