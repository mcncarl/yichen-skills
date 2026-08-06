# X 内容路由

## 判定顺序

1. 从公开 FxTwitter Thread 接口读取 focal status 与 thread nodes。
2. 先验证是否存在长度大于 1 的同作者直接回复链。
3. 有有效链时判定为 Thread；链中任一节点含 Quote 时判定为带 Quote 的 Thread。
4. 无有效链时，focal 含 Quote 才判定为 Quote Post；否则判定为普通 Post。

不能先看到 Quote 就直接结束 Thread 判定。

## Thread 边界

每条边同时满足：

- 子节点作者 ID 与根节点作者 ID 相同。
- 子节点 `replying_to.status` 等于上一节点 ID。
- 子节点时间晚于上一节点。
- 根节点不是对外部账号的普通回复。

排除其他作者回复、旁支回复、评论和搜索结果。若同一节点出现多个同作者直接子分支，报告 `ambiguous_self_reply_branch` 并停止生成，不自行拼接。

## Quote 处理

- 永远不递归读取 `node.quote` 的正文、作者、指标或媒体。
- 仅删除指向当前 `node.quote.id` 的 X status URL；保留其他普通网址。
- 直链覆盖 `x.com`、`twitter.com`、`mobile.twitter.com` 以及 `/i/web/status/<id>` 变体；`t.co` 仅在帖子顶层 URL entity 明确展开到该 Quote ID 时删除。无法解析的短链必须停止，不能猜测。
- 删除 Quote 专用 URL 后，若节点正文为空且没有节点自身媒体，标记 `quote_only` 并跳过。
- 媒体只读取节点顶层 `node.media`。视频的 `thumbnail_url` 只用于 PNG/ZIP 的静态预览；默认成片还必须选择并下载节点自身安全 MP4，在该媒体页内完整播放视觉内容，不能用封面代替原生视频。该 MP4 有有效源音轨时，只在对应视频页按源画面时间轴保留原声；没有源音轨时，该页对应区间静音。不得读取 Quote 视频或 Quote 音频。

## 验收

- 输出 status ID 必须全部属于验证后的同作者直接回复链。
- `ignored_quote_ids` 必须覆盖所有被选节点或被检查节点的 Quote ID。
- `quote_only` 节点输出帧数必须为零。
- 归一化后的所有正文帧按顺序拼接，必须等于选中节点清理 Quote URL 后的正文。
- 任何 Quote 文本与 Quote 媒体哈希不得进入输出。
- 路由审计只保存 Quote 媒体 ID 与来源 URL 的 SHA-256；输出媒体必须与两者零碰撞。
