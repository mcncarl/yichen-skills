---
name: yichen-social-bookmarks-exporter
description: 已退役的兼容调用名。小红书收藏、抖音收藏与 X/Twitter 书签导出能力已经完整合并到 yichen-bookmarks-export；仅在用户明确点名旧名 yichen-social-bookmarks-exporter 时使用，并立即转交 yichen-bookmarks-export，不再执行本目录中的旧实现。
---

# 已迁移到 yichen-bookmarks-export

收藏导出能力、平台脚本、Chrome 规则、去重校验和交接规范已经合并到：

```text
yichen-bookmarks-export/
```

不要执行本目录保留的旧脚本。完整读取并使用 `$yichen-bookmarks-export`，由它重新确认当轮平台、范围和私人读取授权。

本兼容入口不接受隐式调用，不承担收藏导出执行职责。
