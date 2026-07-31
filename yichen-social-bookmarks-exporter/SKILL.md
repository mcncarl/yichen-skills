---
name: yichen-social-bookmarks-exporter
description: 批量导出小红书、抖音与 X/Twitter 的私人收藏或书签为本地链接文件，支持 Chrome 登录态收藏页滚动去重、Field Theory GraphQL-only 同步、数量核验和按需转入媒体下载。用户要求抓取、导出、同步、备份、迁移或检查小红书收藏、抖音收藏、X 书签时使用；读取私人收藏前必须获得当轮明确授权。
---

# 社交收藏夹导出

把小红书、抖音和 X 的当前可访问收藏导出为一行一个 URL 的本地文件，并给出页面标称数量、实际导出数量、重复数和抽样验证结果。

## 固定边界

1. 把收藏夹视为私人数据。只处理用户在当轮明确指定并授权的平台；一次授权不延伸到其他平台或后续任务。
2. 保持只读：不点赞、不收藏、不评论、不关注、不发布。
3. 不读取或打印 Cookie、Local Storage、密码、Token 数据库。小红书 URL 自带的 `xsec_token` 只能写入用户指定的本地导出文件，不进入普通日志、记忆或公开文档。
4. 不覆盖已有导出文件，除非用户明确允许；不删除临时文件或旧导出。
5. “抓链接”和“下载媒体”分开。只有用户明确要求下载时，才调用现有下载 Skill。

## 路由

| 平台 | 收藏链接来源 | 认证方式 | 输出 |
|---|---|---|---|
| 小红书 | 已登录 Chrome 的个人主页 → 收藏 → 笔记 | 复用当前 Chrome 页面会话，不导出 Cookie | 保留 `xsec_token` 的完整笔记 URL |
| 抖音 | 已登录 Chrome 的 `user/self?showTab=favorite_collection` → 收藏 → 视频 | 复用当前 Chrome 页面会话，不导出 Cookie | 规范化 `/video/<id>` 与页面实际出现的 `/note/<id>` |
| X | 本机 `ft` 读取 Chrome 会话 Cookie并调用内部 GraphQL Bookmarks | Field Theory GraphQL-only | `https://x.com/<author>/status/<id>` |

## 第三方来源与合规

1. X 路线调用外部 [afar1/fieldtheory-cli](https://github.com/afar1/fieldtheory-cli)；上游采用 MIT License，许可证副本见仓库 `licenses/afar1-fieldtheory-cli-LICENSE.txt`。
2. 本 Skill 没有复制或打包 Field Theory 源码、二进制、Cookie、私有 Query ID 或认证数据；这里只通过命令行调用用户另行安装的 `ft`。
3. `graphql-only` 是本 Skill 对兼容版本的安全约束，不是上游官方版本名称。若用户自行修改 Field Theory，必须保留上游版权和 MIT 许可说明，不得把修改版冒充上游官方发布。
4. X 内部 GraphQL、页面 DOM 与平台接口都属于非官方兼容路线，可能变化或触发平台限制。仅处理用户本人有权访问的数据，保持低频，不绕过验证码、访问控制、限流或平台安全措施。
5. 小红书、抖音和 X 的名称及商标归各自权利人所有；本 Skill 与这些平台及 Field Theory 上游均无隶属、授权、背书或合作关系。
6. `chrome:control-chrome` 是宿主 Agent 环境提供的浏览器能力，不由本 Skill 仓库分发。按需调用的其他下载 Skill 需分别遵守其自身许可证和平台规则。

## 执行流程

### 1. 确认范围与输出目录

确认平台、是否增量或全量、只导链接还是还要下载。用户未指定目录时，在当前工作区新建不冲突的日期目录，例如：

```text
<WORKSPACE>/收藏链接导出-YYYY-MM-DD/
```

每个平台单独输出 `.txt`；另给出数量摘要。不要把私人正文或收藏标题写入长期记忆。

### 2. 导出小红书或抖音

先完整读取并遵守 `chrome:control-chrome` Skill，只使用用户当前 Chrome。按 [references/chrome-collections.md](references/chrome-collections.md) 导航并验证选中标签。先解析当前 Skill 的实际安装目录为绝对路径 `<SKILL_DIR>`，再在已初始化的浏览器控制会话中导入：

```js
var bookmarkCollectors = await import("<SKILL_DIR>/scripts/chrome_collectors.mjs");
```

在正确页面调用：

```js
var result = await bookmarkCollectors.collectXiaohongshuBookmarks(tab);
// 或
var result = await bookmarkCollectors.collectDouyinFavorites(tab);
```

只有 `result.completed === true` 才能宣称已滚动到稳定底部。使用 `writeUrlFile()` 写新文件；目标已存在时先向用户确认，不要静默传 `overwrite: true`。

```js
await bookmarkCollectors.writeUrlFile(outputPath, result.urls);
```

小红书必须同时报告 `labelCount` 与实际 `count`。标签数量不等于当前可访问数量；禁止把作者主页 ID 计成笔记 ID。

### 3. 导出 X 书签

确认当前安装仍是 GraphQL-only，并检查状态：

```bash
ft --version
ft status
```

只有用户明确要求同步时才运行：

```bash
ft sync
# 仅在用户明确要求全量回溯时：
ft sync --full
```

不要加 `--classify`。同步完成后分页导出本地索引中的所有 X 链接：

```bash
python3 "<SKILL_DIR>/scripts/export_x_links.py" \
  --output "/absolute/output/x-bookmarks.txt"
```

脚本会拒绝非 `graphql-only` 的 Field Theory 版本，并在目标文件已存在时停止。

### 4. 校验与抽样

对每个文件运行：

```bash
python3 "<SKILL_DIR>/scripts/validate_link_file.py" \
  --platform xiaohongshu "/absolute/output/xiaohongshu.txt"
```

`--platform` 可选 `xiaohongshu`、`douyin`、`x`。必须报告有效条数、空行、重复和非法行；不要在日志中回显含 `xsec_token` 的完整 URL。

从首、中、末各抽一条在同一登录态浏览器中打开，确认没有“已删除、内容不存在、无权查看”等错误。抽样成功不等于所有链接永远有效。

## 下载媒体（仅按需）

- 小红书：交给 `$yichen-content-archive` 的 `xiaohongshu_fetch.py`。先用 `--skip-media` 预检，完整下载时去掉该参数；只有当轮另行授权后才允许 `--use-cookie`。
- 抖音：交给 `$yichen-content-archive` 的 `douyin_download.py`，获得 MP4 与 metadata；先用 `--metadata-only` 预检。
- X：`ft fetch-media` 只下载静态图片；只有用户明确要求后才执行，不承诺下载视频、评论或外链正文。

批量下载采用低并发、断点续跑和失败清单，不因“导出了链接”自动开始下载。

## 失败判断

- 小红书标签数大于导出数：报告差值与稳定到底证据；原因保持未定，不自动归因于脚本漏抓或用户隐藏。
- 抖音列表滚动高度停止增长：连续等待规定轮数后才结束；分别报告 `/video/` 与 `/note/` 数量。
- X 出现 Query ID、401/403、429 或响应结构错误：说明内部 GraphQL 路线失效或被限流，不回退 OAuth、官方付费 API 或手工 Cookie 导出。
- Chrome 未登录：要求用户在当前 Chrome 登录后继续，不切换到另一个浏览器绕过认证。
