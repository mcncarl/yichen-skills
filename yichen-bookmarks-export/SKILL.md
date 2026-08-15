---
name: yichen-bookmarks-export
description: 在用户当轮明确授权后，只读导出其小红书收藏、抖音收藏或 X/Twitter 书签为本地链接文件；本 Skill 直接完成收藏页滚动、链接提取、去重、数量核验、Field Theory GraphQL-only 导出和抽样验证。用于“导出/备份/同步我的收藏或书签链接”等私人数据导出任务；不得用于公开搜索、收藏内容分析、媒体下载、正文归档、推荐发现或未获当轮授权的私人读取。
---

# 私人收藏与书签导出

这是小红书、抖音与 X/Twitter 私人收藏链接导出的唯一入口和执行实现。直接使用本目录中的脚本与参考文件，不调用其他收藏导出 Skill；作为执行本体，不得再次调用 `$yichen-bookmarks-export`，以免形成递归。

## 当轮授权闸门

在读取任何私人收藏前，确认用户当轮明确要求的：

- 平台：小红书、抖音、X 中的具体一个或多个。
- 范围：当前可访问全量或用户指定的有界范围。
- 输出目录，或同意创建新的不冲突日期目录。

“以前授权过”、浏览器已经登录、本机已有 Cookie/索引或上游交接写过授权，都不能代替当轮授权。用户当轮说“导出我的某平台收藏/书签”，可视为该平台的只读导出授权，但不得扩展到其他平台。

## 硬边界

1. 保持只读：不点赞、不收藏、不评论、不关注、不发布，不修改平台状态。
2. 不得执行搜索或发现；不按关键词查收藏，不浏览推荐，不扩展相似账号或候选。
3. 只导出链接；不得下载媒体、正文、字幕或附件，不调用任何平台下载 Skill。
4. 不得调用 `$yichen-content-archive` 或任何总路由；用户另行明确要求归档后，只交接链接文件路径。
5. 导出授权不等于下载授权。即使同一句话包含“导出并下载”，本 Skill 也只完成链接导出，把归档列为后续独立请求。
6. 不读取、打印或保存 Cookie、Local Storage、密码、Token 数据库。含敏感查询参数的 URL 只写入用户指定的本地导出文件。
7. 不覆盖旧导出，不删除文件，不绕过验证码、限流、登录或访问控制。

## 平台路由

| 平台 | 收藏链接来源 | 认证方式 | 输出 |
|---|---|---|---|
| 小红书 | 已登录 Chrome 的个人主页 → 收藏 → 笔记 | 复用当前 Chrome 页面会话，不导出 Cookie | 保留 `xsec_token` 的完整笔记 URL |
| 抖音 | 已登录 Chrome 的个人页 → 收藏 → 视频 | 复用当前 Chrome 页面会话，不导出 Cookie | 规范化 `/video/<id>` 与页面实际出现的 `/note/<id>` |
| X | 本机 Field Theory 读取 Chrome 会话并调用内部 GraphQL Bookmarks | 只接受 GraphQL-only 版本 | `https://x.com/<author>/status/<id>` |

## 第三方来源与合规

1. X 路线调用外部 [afar1/fieldtheory-cli](https://github.com/afar1/fieldtheory-cli)；上游采用 MIT License，许可证副本见 [../licenses/afar1-fieldtheory-cli-LICENSE.txt](../licenses/afar1-fieldtheory-cli-LICENSE.txt)。
2. 本 Skill 不打包 Field Theory 源码、二进制、Cookie、私有 Query ID 或认证数据；这里只调用用户另行安装的 `ft`。
3. `graphql-only` 是兼容版本的安全约束，不是上游官方版本名称。用户自行修改 Field Theory 时必须保留上游版权和 MIT 许可说明，不得冒充官方发布。
4. X 内部 GraphQL 与平台 DOM 都是非官方兼容路线，可能变化或触发限制。只处理用户本人有权访问的数据，保持低频，不绕过验证码、访问控制、限流或平台安全措施。
5. 小红书、抖音、X 与 Field Theory 名称及商标归各自权利人所有；本 Skill 与这些平台或上游均无隶属、授权、背书或合作关系。

## 执行流程

### 1. 固化范围与输出

逐平台记录 `authorized_this_turn=true`。任何未明确列入的平台保持未授权，不做探测、状态检查或计数。

用户未指定目录时，创建不冲突的日期目录，例如：

```text
<WORKSPACE>/收藏链接导出-YYYY-MM-DD/
```

每个平台单独输出 `.txt`，同时生成 `export-summary.json` 和 `handoff.json`。不要把私人正文、标题或完整收藏 URL 写入聊天、普通日志或长期记忆。

### 2. 导出小红书或抖音

完整读取并遵守 `$chrome:control-chrome`，只使用用户当前 Chrome。再读取 [references/chrome-collections.md](references/chrome-collections.md)，确认账号、URL 和选中标签。先解析当前 Skill 的实际安装目录为绝对路径 `<SKILL_DIR>`。

在已初始化的浏览器控制会话中导入：

```js
var bookmarkCollectors = await import("<SKILL_DIR>/scripts/chrome_collectors.mjs");
```

调用：

```js
var result = await bookmarkCollectors.collectXiaohongshuBookmarks(tab);
// 或
var result = await bookmarkCollectors.collectDouyinFavorites(tab);
```

只有 `result.completed === true` 才能宣称已滚动到稳定底部。使用 `writeUrlFile()` 写入新文件；目标存在时停止并询问，不得静默使用 `overwrite: true`。

小红书分别报告 `labelCount` 与实际 `count`。抖音分别报告 `typeCounts.video` 与 `typeCounts.note`。

### 3. 导出 X 书签

先确认 Field Theory 当前安装仍是 GraphQL-only：

```bash
ft --version
ft status
```

只有用户明确要求同步时才运行 `ft sync`；只有明确要求全量回溯时才运行 `ft sync --full`。不要加 `--classify`。

同步后分页导出本地索引：

```bash
python3 <SKILL_DIR>/scripts/export_x_links.py \
  --output "/absolute/output/x-bookmarks.txt"
```

脚本拒绝非 GraphQL-only 的 Field Theory 版本，并在目标文件已存在时停止。

### 4. 校验与抽样

对每个链接文件运行：

```bash
python3 <SKILL_DIR>/scripts/validate_link_file.py \
  --platform xiaohongshu "/absolute/output/xiaohongshu-bookmarks.txt"
```

`--platform` 可选 `xiaohongshu`、`douyin`、`x`。报告有效条数、空行、重复和非法行，但不得回显带敏感参数的完整 URL。

从首、中、末各抽一条，在同一登录态浏览器中打开，确认没有“已删除、内容不存在、无权查看”等错误。抽样成功不代表所有链接永久有效。

### 5. 生成标准交接

读取并遵守 [references/handoff-contract.md](references/handoff-contract.md)。交接固定满足：

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

交接只引用导出文件绝对路径，不内嵌 URL，也不自动调用归档 Skill。

## 失败判断

- 小红书标签数大于导出数：报告差值和稳定到底证据，原因保持未定。
- 抖音滚动高度停止增长：等待规定稳定轮数后结束，并分别报告视频和图文数量。
- X 返回 Query ID、401/403、429 或结构错误：说明 GraphQL 路线失效或限流，不回退 OAuth、官方付费 API 或手工 Cookie 导出。
- Chrome 未登录：请用户在当前 Chrome 登录后继续，不切换浏览器绕过认证。

## 最终报告

只报告本轮授权平台、导出数、重复数、非法行数、抽样结果、输出路径和失败原因。若用户还想下载或归档，明确说明需要另行提出请求，不自动开始。
