# x-article-draft-uploader

把 Obsidian 或本地 Markdown 文章上传到 X Articles 草稿的 Codex Skill。

它会自动完成：

- 第一张图作为 X Article 封面
- 如果文章不是以图片开头，默认中断并提醒先加封面图
- Markdown 转 rich text 正文
- 正文图片按原文位置插入
- 使用独立 Playwright 浏览器，不抢占用户当前 Chrome
- 从本机 Chrome 临时导出 X cookies，不把 cookies 写进 Skill
- 只保存草稿，不点击最终 `发布`

## 适合场景

- 从 Obsidian 发布长文到 X Articles
- Markdown 里有大量本地图片
- 封面必须使用文章最上方的第一张图片
- 需要在没有封面图时先提醒用户，而不是自动拿正文里的第一张图充当封面
- 旧脚本出现缺图、错位、`MPH_MARKER` 残留
- 用户已经在 Chrome 登录 X，但不希望自动化接管当前浏览器窗口

## 安装

把本目录复制到 Codex 或 Claude Code 的 skills 目录：

```bash
cp -R x-article-draft-uploader ~/.codex/skills/
```

常见路径：

- Codex: `~/.codex/skills/`
- Claude Code: `~/.claude/skills/`
- Agents: `~/.agents/skills/`

## 依赖

需要 Python 3.9+，并安装：

```bash
pip3 install playwright pycryptodome
python3 -m playwright install chromium
```

macOS 上还需要 Chrome 已安装，并且当前 Chrome 已登录 X。

## 快速使用

### 1. 导出当前 X cookies

```bash
python3 ~/.codex/skills/x-article-draft-uploader/scripts/export_x_cookies_from_chrome.py \
  --output /tmp/x_current_cookies.json
```

脚本只会打印 cookie 名称，不会打印 cookie 值。

### 2. 先做 dry-run

```bash
python3 ~/.codex/skills/x-article-draft-uploader/scripts/upload_markdown_to_x_article.py \
  "/absolute/path/to/article.md" \
  --cookies-json /tmp/x_current_cookies.json \
  --dry-run
```

dry-run 会检查：

- 文章标题
- 第一张封面图
- 第一个有效内容是否是图片
- 正文图片数量
- 每张正文图的插入锚点

如果文章第一个有效内容不是图片，脚本会中断并提示先加封面图。此时不会打开 X，也不会创建草稿。

如果用户明确拒绝添加封面图，但仍然要继续上传无封面草稿，可以使用：

```bash
python3 ~/.codex/skills/x-article-draft-uploader/scripts/upload_markdown_to_x_article.py \
  "/absolute/path/to/article.md" \
  --cookies-json /tmp/x_current_cookies.json \
  --allow-no-cover
```

使用 `--allow-no-cover` 后，脚本会跳过封面上传，并把文章里的所有图片都按正文图片插入。

### 3. 上传为新的 X Article 草稿

```bash
python3 ~/.codex/skills/x-article-draft-uploader/scripts/upload_markdown_to_x_article.py \
  "/absolute/path/to/article.md" \
  --cookies-json /tmp/x_current_cookies.json
```

输出文件：

- `/tmp/x_article_upload_url.txt`：草稿 URL
- `/tmp/x_article_upload_result.json`：校验结果
- `/tmp/x_article_final_uploaded.png`：最终截图

## 工作原理

1. 解析 Markdown，识别标题、封面候选图和正文图片。
2. 检查文章第一个有效内容是否是图片；不是图片时默认中断上传并提醒用户加封面图。
3. 从每张图片前一行提取 anchor，用于定位插图位置。
4. 新开独立 Playwright Chromium 会话，并加载临时 cookies。
5. 在 X Articles 新建草稿。
6. 上传封面并点击 X 的 `应用`；使用 `--allow-no-cover` 时跳过这步。
7. 粘贴 rich HTML 正文。
8. 从后往前插入正文图片，避免前面的插入动作影响后面定位。
9. 等待 X autosave。
10. 校验标题、正文开头/结尾、无 `MPH_MARKER`、媒体数等于 `封面数 + 正文图数量`。

## 隐私与安全

- Skill 不包含任何真实 cookies、token、账号密码或 API key。
- cookies 只在运行时导出到 `/tmp/x_current_cookies.json`。
- 用完后可以删除临时 cookies：

```bash
rm -f /tmp/x_current_cookies.json
```

- 不要把 `/tmp/x_current_cookies.json` 或任何真实 cookies 提交到 Git。
- 脚本默认只创建草稿，不会公开发布文章。

## 常见问题

### X 跳到登录页怎么办？

说明 cookies 过期了，重新运行：

```bash
python3 ~/.codex/skills/x-article-draft-uploader/scripts/export_x_cookies_from_chrome.py \
  --output /tmp/x_current_cookies.json
```

如果仍然失败，先手动在 Chrome 登录 X。

### 封面上传后页面被遮住怎么办？

X 会弹出媒体编辑层。必须点击 `应用`，否则编辑器会被 mask 挡住，封面也不会真正保存。脚本已经内置这个动作。

### 文章不是以图片开头怎么办？

默认先停下来提醒用户加封面图。只有用户明确说“不加封面也继续”，才使用 `--allow-no-cover`。这时 X Article 会没有封面，文章里的图片全部作为正文图片处理。

### 为什么正文图片要倒序插入？

因为 X 编辑器是动态内容。先插前面的图片会改变后面内容的位置。倒序插入更稳定。

### 是否会接管我的 Chrome？

不会。脚本只读取本机 Chrome 保存的 X 登录态，然后在独立 Playwright 浏览器中执行上传。

## 文件结构

```text
x-article-draft-uploader/
├── SKILL.md
├── README.md
├── agents/
│   └── openai.yaml
└── scripts/
    ├── export_x_cookies_from_chrome.py
    ├── parse_markdown.py
    └── upload_markdown_to_x_article.py
```

## License

Personal Learning and Non-Commercial Use License. See the repository root `LICENSE`.

部分 Markdown 解析流程参考并迁移自 `wshuyi/x-article-publisher-skill`，详见仓库根目录 `THIRD_PARTY_NOTICES.md`。
