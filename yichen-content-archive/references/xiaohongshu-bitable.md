# 小红书素材沉淀到飞书多维表格

只有用户当轮明确说“沉淀”“入库”或指定目标多维表格时才读取本参考。普通“读取、下载、归档、保存到本地”不会触发外部写入。

## 安全闸门

- 先用 `xiaohongshu_fetch.py` 获取本地 HTML、metadata 和用户要求的媒体；默认匿名，当前目标获当轮明确授权后才可 `--use-cookie`。
- 写入前确认目标表、字段映射和用户要求的记录范围。不得从历史消息猜 AppToken、TableID 或目标表。
- Cookie、AppToken、TableID 和 ASR 凭证只通过私有配置或子进程环境变量注入，不写入 Skill、仓库、普通日志或长期记忆。
- 本地私有配置可用时，只检查并注入 `xiaohongshu` profile；不得打印完整 secrets 文件。
- 写入飞书是外部状态变更，只创建用户明确要求的记录，不顺带建表、改字段、覆盖旧记录或批量扩展其他链接。
- 临时媒体、转写和 OCR 产物默认保留。只有用户明确允许删除后，才移动到系统废纸篓；不得直接永久删除。

本机使用共享私有配置 runner 时，只允许以下调用形状：

```bash
$HOME/.config/agent-secrets/agent_secrets.py check --profile xiaohongshu
$HOME/.config/agent-secrets/agent_secrets.py run --profile xiaohongshu -- <command>
```

## 视频笔记

1. 从 `xhs_<note_id>.metadata.json` 读取标题、正文、作者、发布时间、互动数据、标签与媒体路径。
2. 有平台字幕时优先使用已下载的 SRT/`transcript.txt`；没有字幕且用户确实要求口播稿时，交给已安装的统一 ASR Skill 处理，提交前遵守它的费用与防重复规则。
3. 按段输出 `content`、`summary`、`position`、`viral_hook`、`hook_type`，并生成 `structure_analysis`、`opening_analysis`、`viral_points`。
4. 写入用户明确指定的视频对标库。常见字段映射：

| 目标字段 | 来源 |
|---|---|
| 来源链接 | 原始笔记 URL |
| 平台 | 小红书 |
| 作者 | `author` |
| 发布日期 | `time` 转换后的日期 |
| 点赞/收藏/评论/转发 | `interact_info` 对应字段；缺失时留空 |
| 正文口播稿 | 所有分段正文按顺序拼接 |
| 口播稿分析 | 结构、开头与爆点分析汇总 |
| 内容类型 | 根据正文判断并标明是模型分类 |

## 图文笔记

1. 从 metadata 读取标题、正文、作者、时间、标签和本地图片路径。
2. 仅在用户要求时对图片做 OCR/视觉分析，保留逐图结果和合并正文；无法识别的内容明确留空。
3. 写入用户明确指定的选题库或其他表格。常见字段映射：

| 目标字段 | 来源 |
|---|---|
| 主字段/标题 | `title` |
| 来源链接 | 原始笔记 URL |
| 平台 | 小红书 |
| 作者/日期 | `author` / `time` |
| 一句话摘要 | `desc` 与图片内容的模型摘要 |
| 文章结构/启发点 | 模型分析，明确是生成内容 |
| 标签 | `tags` 中用户目标表允许的部分 |

## 失败处理

- `INITIAL_STATE` 不完整但 meta 可用：保留 `extraction_source=meta_fallback`，不得把单封面或摘要冒充完整笔记。
- 匿名失败：先报告具体缺口；只有当前目标获当轮授权后才注入 `XHS_COOKIE` 并加 `--use-cookie`。
- 视频无字幕：只有用户要求转写时才调用 ASR；失败时保留原视频与错误原因，不跨服务商静默重提。
- 飞书写入失败：报告状态码、错误码和缺失权限，不输出凭证值，不重复创建可能已经成功的记录。
