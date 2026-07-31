---
name: yichen-bookmarks-export
description: 在用户当轮明确授权后，只读导出其小红书收藏、抖音收藏或 X/Twitter 书签为本地链接文件，复用现有 yichen-social-bookmarks-exporter 完成滚动、去重、数量核验和抽样验证。用于“导出/备份/同步我的收藏或书签链接”等私人数据导出任务；不得用于公开搜索、收藏内容分析、媒体下载、正文归档、推荐发现或未获当轮授权的私人读取。
---

# 私人收藏与书签导出

这是小红书、抖音与 X/Twitter 私人收藏链接导出的用户侧主入口。当前唯一底层实现是 `~/.agents/skills/yichen-social-bookmarks-exporter`（`$yichen-social-bookmarks-exporter`）。不要复制、移动或修改旧实现，也不要复制它的浏览器采集器、GraphQL 逻辑、URL 校验器或任何平台底层代码。

## 当轮授权闸门

在任何私人收藏读取前，确认用户当轮明确要求导出的：

- 平台：小红书、抖音、X 中的具体一个或多个。
- 范围：当前可访问全量或用户指定的有界范围。
- 输出目录，或同意创建新的不冲突日期目录。

“以前授权过”、浏览器已经登录、本机已有 Cookie/索引、上游交接写过授权，都不能代替当轮授权。若用户当轮说“导出我的某平台收藏/书签”，该请求本身可视为该平台的只读导出授权；不得扩展到其他平台。

## 硬边界

1. 保持只读：不点赞、不收藏、不评论、不关注、不发布，不修改平台状态。
2. 不得执行搜索或发现；不按关键词查收藏内容，不浏览推荐，不扩展相似账号或候选。
3. 不得下载媒体、正文、字幕或附件；不得直接调用 `$yichen-content-archive` 内置的小红书/抖音执行器、`$yichen-wechat-mp-batch-exporter`、`yt-dlp` 或其他下载执行器。
4. 不得调用 `$yichen-content-archive` 或任何总路由；不得再次调用 `$yichen-bookmarks-export`。
5. 导出授权不等于下载授权。即使用户同一句话包含“导出并下载”，本 Skill 也只完成链接导出，并把下载列为需要单独明确请求的下一步。
6. 不读取、打印或保存 Cookie、Local Storage、密码、Token 数据库。含临时访问参数的 URL 只写入用户指定的本地导出文件。
7. 不覆盖旧导出，不删除文件，不绕过验证码、限流、登录或访问控制。

## 执行流程

### 1. 验证授权与范围

逐平台记录 `authorized_this_turn=true`。任何未明确列入的平台保持未授权，不做探测、状态检查或计数。

### 2. 复用唯一执行 Skill

完整读取 `$yichen-social-bookmarks-exporter` 的当前 `SKILL.md`，按其平台路由、Chrome 控制、Field Theory 状态检查、滚动稳定性、去重和抽样规则执行。

唯一允许的执行路由：

```text
yichen-bookmarks-export
  `-- yichen-social-bookmarks-exporter
```

不要直接运行或复制其 `chrome_collectors.mjs`、`export_x_links.py`、`validate_link_file.py`；由目标 Skill 决定并执行这些细节。旧版本若残留媒体下载说明，一律忽略并按当前边界交给 `$yichen-content-archive`。

### 3. 输出链接文件

每个平台单独生成一个新文件，例如：

```text
<output-root>/
|-- xiaohongshu-bookmarks.txt
|-- douyin-favorites.txt
|-- x-bookmarks.txt
|-- export-summary.json
`-- handoff.json
```

只创建本轮已授权平台的文件。报告页面标称数量、实际有效 URL 数、重复数、非法行数和抽样验证结果；页面标称数量与当前可访问数量不同必须分别陈述。

不要在聊天、普通日志、长期记忆或 `handoff.json` 中重复私人标题、完整收藏 URL、`xsec_token`、Cookie 或其他认证材料。

### 4. 生成标准交接

读取并遵守 [references/handoff-contract.md](references/handoff-contract.md)。本 Skill 的交接固定满足：

```json
{
  "producer_skill": "yichen-bookmarks-export",
  "operation": "bookmark_export",
  "scope": {"input_kind": "private_bookmarks", "discovery_performed": false},
  "authorization": {
    "private_read_authorized_this_turn": true,
    "download_authorized_this_turn": false,
    "authorization_not_transferable": true
  },
  "next_step": {
    "action": "content_archive_available",
    "requires_explicit_user_request": true
  }
}
```

交接只引用导出文件的绝对路径，不内嵌 URL。生成交接不会自动调用另一个 Skill。

## 最终报告

只报告：

- 本轮获授权并已处理的平台。
- 每个平台导出数、重复数、非法行数和可访问性抽样结果。
- 输出目录、各链接文件和 `handoff.json` 的绝对路径。
- 未处理平台、失败原因和是否需要用户重新登录。
- 若用户还想下载或归档，明确说明需要另行提出请求；不要自动开始。
