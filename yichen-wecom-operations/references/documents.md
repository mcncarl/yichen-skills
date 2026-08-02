# 企微文档与智能文档

## 类型路由

| URL | 类型 | 命令 |
|---|---|---|
| `/doc/*` | 普通文档 | `wecom-cli doc create_doc/get_doc_content/edit_doc_content` |
| `/smartpage/*` | 智能文档 | `wecom-cli doc +smartpage_create/smartpage_export_task` |
| `/sheet/*` | 在线表格 | `wecom-cli doc sheet_*` |
| `/smartsheet/*` | 智能表格 | `wecom-cli doc smartsheet_*` |

先运行 `wecom-cli doc --help`，以当前动态返回的工具为准。

## 从 Markdown 创建智能文档

优先运行 `scripts/create_smartpage.py`。脚本默认 dry-run，只有 `--execute` 才写入企微。

### 无本地图片

脚本直接调用：

```bash
wecom-cli doc +smartpage_create '{"title":"标题","pages":[{"page_title":"正文","content_type":1,"page_filepath":"/absolute/report.md"}]}'
```

单个 Markdown 文件不得超过 10MB。

### 含本地图片

官方 `+smartpage_create` 只读取 Markdown 文本，不上传相对路径图片；`data:` 图片会被企微过滤。必须按以下顺序：

1. 创建同名“图片资源”普通文档；
2. 用本机 `+doc_upload_image` helper 把本地图片上传到该文档；
3. 把 Markdown 图片地址改为企微 `https://wdcdn.qpic.cn/...` URL；
4. 用生成的私密上传副本创建最终智能文档；
5. 保存 `0600` 回执，向用户同时披露最终文档与图片资源文档。

不得公开托管证据图片，不得再尝试 `data:`。

## 普通文档覆写

`edit_doc_content` 会替换全部正文。执行前必须先用 `get_doc_content` 回读并确认目标；回读权限不足时不得覆写。

## 智能文档回读

1. `smartpage_export_task` 提交任务；
2. `smartpage_get_export_result` 轮询到 `task_done=true`；
3. 只在回读成功后声称正文已验证。

`851008 partial no authorization` 表示机器人缺少“获取成员文档内容”权限。展示接口要求的帮助文字并停止回读，不得改用浏览器或客户端查看。

## 隐私

- 文档 URL 可作为本次交付链接返回，但不得写入共享记忆。
- docid、图片 CDN 映射和上传副本只写入私密本机目录。
- 不修改源 Markdown；所有路径改写都发生在上传副本中。
