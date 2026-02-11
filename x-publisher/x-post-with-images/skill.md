---
name: x-post-with-images
description: |
  Publish text posts with up to 4 images to X (Twitter). Supports unlimited text length for X Premium users. Use when user wants to post tweets with images, mentions "post with photos", "tweet with pictures", or provides text content and image paths.
---

# X Post with Images

发布带图片的 X 推文（文本 + 最多4张图片），支持 X Premium 长推文。

## 来源与致谢

本技能的整体思路与部分流程参考了以下项目，并在此基础上做了适配与扩展：

- https://github.com/wshuyi/x-article-publisher-skill
- https://github.com/JimLiu/baoyu-skills

第三方许可与说明见仓库根目录 `THIRD_PARTY_NOTICES.md`。

## 参数

- `POST_TEXT`：推文文本（必需，无字符限制）
  - X Premium 用户支持最多 25,000 字符
  - 普通用户限制 280 字符（由 X 平台强制执行）
  - **支持 Markdown 格式**：`**粗体**`、`*斜体*`、`[链接](url)` 会自动转换
    - 粗体/斜体转为 Unicode 数学字符（视觉效果相同，支持英文和数字）
    - 链接转为 `text (url)` 格式
    - 中文字符保持原样（无Unicode映射）
  - **支持媒体嵌入**：`![](path)` 会自动提取并上传（支持图片和视频）
- `IMAGE_PATHS`：图片路径，逗号分隔（可选，最多4张）
  - 如果 POST_TEXT 中包含 `![](path)`，会自动合并
  - 支持格式：JPG, PNG, GIF, WebP
  - 单张图片最大 5MB
  - 可以使用绝对路径或相对路径
- `--publish`：直接发布推文（可选）
  - 不提供此参数：保存为草稿（默认）
  - 提供此参数：立即发布到 X 平台

## 前置要求

- **Playwright MCP** 用于浏览器自动化（必需）
- Cookie 配置文件 `~/.claude/skills/x-publisher/cookies.json` 已配置
- 如需发布长推文（超过280字符），账号必须是 X Premium

## 执行流程（严格遵循）

### Phase 1: 验证输入参数

1.1 验证 POST_TEXT
```bash
检查 POST_TEXT 是否为空
如果为空，停止并提示用户

注意：不限制字符长度
- X Premium 用户：最多 25,000 字符
- 普通用户：超过 280 字符会被 X 平台拒绝
- 本 skill 不会预先验证账号类型
```

1.2 验证 IMAGE_PATHS（如果提供）
```bash
解析逗号分隔的路径列表
对于每个路径：
  - 检查文件是否存在
  - 检查文件格式（JPG/PNG/GIF/WebP）
  - 检查文件大小（不超过 5MB）

限制图片数量不超过 4 张
如果超过 4 张，停止并提示用户
```

1.3 记录执行参数
```
- 推文文本字符数
- 图片数量和路径列表
```

---

### Phase 2: 浏览器操作

#### 2.1 加载 Cookie（完全复用 x-article-publisher 机制）

```javascript
browser_run_code: |
  async (page) => {
    const fs = require('fs');
    const cookiesPath = 'C:\\Users\\HP\\.claude\\skills\\x-publisher\\cookies.json';
    const cookiesJson = fs.readFileSync(cookiesPath, 'utf-8');
    const cookies = JSON.parse(cookiesJson).cookies;

    for (const cookie of cookies) {
      await page.context().addCookies([cookie]);
    }

    return {
      loaded: cookies.length,
      cookiesPath
    };
  }
```

**输出提示**：`✅ 已加载 ${loaded} 个 Cookie`

#### 2.2 验证登录状态（完全复用 x-article-publisher 机制）

```javascript
browser_navigate: https://x.com
browser_wait_for: time=2

browser_run_code: |
  async (page) => {
    const loggedIn = await page.locator('[data-testid="primaryColumn"]').count() > 0;

    if (!loggedIn) {
      return {
        loggedIn: false,
        error: '未登录 - 请更新 cookies.json 文件'
      };
    }

    return { loggedIn: true };
  }
```

**如果 loggedIn=false**，停止执行并输出：
```
❌ 登录验证失败
请按以下步骤更新 Cookie：
1. 在浏览器中访问 https://x.com 并登录
2. F12 → Application → Cookies → https://x.com
3. 复制 auth_token 和 ct0 的值
4. 更新 ~/.claude\skills\x-publisher\cookies.json

详细指南请参考 x-article-publisher 的 troubleshooting.md
```

**输出提示**：`✅ 登录验证成功`

#### 2.3 导航到撰写页面

```javascript
browser_navigate: https://x.com/compose/post
browser_wait_for: time=2
```

**输出提示**：`✅ 已打开推文撰写页面`

#### 2.4 处理 Markdown 文本并提取媒体

**Step 1：调用处理脚本**

使用新的 Markdown 处理脚本处理推文文本并提取媒体文件：

```python
# 调用 process_tweet_markdown.py 处理文本
python "~/.claude\skills\x-publisher\scripts\process_tweet_markdown.py"
```

脚本会：
1. 转换 `**粗体**` 为 Unicode 粗体字符（仅英文和数字）
2. 转换 `*斜体*` 为 Unicode 斜体字符
3. 提取 `![](path)` 媒体文件路径
4. 保留段落换行（`\n\n`）
5. 输出 JSON 格式：`{"text": "处理后文本", "media_files": ["path1", "path2"]}`

**输出提示**：
```
✅ Markdown 处理完成
- 原始文本：${CHARACTER_COUNT_BEFORE} 字符
- 处理后：${CHARACTER_COUNT_AFTER} 字符
- 提取媒体：${MEDIA_COUNT} 个文件
- 格式转换：粗体/斜体已转为 Unicode 字符
```

**Step 2：填入推文文本**

```javascript
browser_run_code: |
  async (page) => {
    const textBox = await page.locator('[data-testid="tweetTextarea_0"]').first();
    await textBox.click();

    // 直接填充处理后的文本（保留换行符）
    await textBox.fill('${PROCESSED_TEXT}');

    return {
      method: 'fill',
      textLength: '${PROCESSED_TEXT}'.length,
      preservedNewlines: true
    };
  }
```

**输出提示**：`✅ 已填入推文文本（${textLength} 字符，保留段落格式）`

#### 2.5 上传媒体（图片/视频）

**合并媒体路径**（来自 Markdown 提取 + IMAGE_PATHS 参数）

**如果有媒体文件**，对于每个文件按顺序执行：

```javascript
browser_run_code: |
  async (page) => {
    const fs = require('fs');
    const path = '${MEDIA_PATH}';

    // 检查文件是否存在
    if (!fs.existsSync(path)) {
      return {
        error: '文件不存在',
        path: path
      };
    }

    // 根据文件扩展名判断类型
    const ext = path.split('.').pop().toLowerCase();
    const isVideo = ['mp4', 'mov', 'webm', 'avi'].includes(ext);
    const isImage = ['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(ext);

    if (!isVideo && !isImage) {
      return {
        error: '不支持的文件格式',
        path: path,
        extension: ext
      };
    }

    // 选择对应的文件上传框
    const selector = isVideo
      ? 'input[type="file"][accept*="video"]'
      : 'input[type="file"][accept*="image"]';

    const fileInput = await page.locator(selector).first();
    await fileInput.setInputFiles(path);

    return {
      uploaded: true,
      path: path,
      type: isVideo ? 'video' : 'image',
      size: fs.statSync(path).size
    };
  }

browser_wait_for: time=3  # 图片等待3秒，视频等待5秒
```

**输出提示**：
- 图片：`✅ 图片 ${index}/${total} 上传成功：${filename}`
- 视频：`✅ 视频上传成功：${filename}（${size_mb} MB）`

**特别注意**：
- 如果上传视频，需要等待视频处理完成（类似 x-post-with-video 的处理逻辑）
- X平台会在后台处理视频，发布按钮会在处理完成后启用
- 视频 + 图片混合上传时，X平台最多支持1个视频或4张图片（不能混合）

#### 2.6 保存到草稿箱（默认行为）

```javascript
browser_run_code: |
  async (page) => {
    // 查找草稿按钮（用户演示时验证的选择器）
    const draftButton = await page.locator('[data-testid="unsentButton"]');
    const exists = await draftButton.count() > 0;

    if (!exists) {
      return {
        error: '未找到草稿按钮',
        savedToDraft: false,
        hint: '可能原因：页面未完全加载或 X 界面已变更。请截图后手动保存。'
      };
    }

    // 点击草稿按钮
    await draftButton.click();

    return {
      clicked: true,
      button: 'unsentButton'
    };
  }

browser_wait_for: time=2

# 等待确认对话框出现并点击"保存"
browser_run_code: |
  async (page) => {
    // 等待确认对话框
    const saveButton = await page.locator('[data-testid="confirmationSheetConfirm"]');
    const dialogExists = await saveButton.count() > 0;

    if (dialogExists) {
      await saveButton.click();
      await page.waitForTimeout(2000);
    }

    // 验证是否跳转回首页或草稿列表页
    const url = page.url();

    if (!url.includes('/compose/post') || url.includes('/drafts')) {
      return {
        draftSaved: true,
        location: url,
        message: '草稿已成功保存'
      };
    }

    return {
      draftSaved: 'unknown',
      currentUrl: url,
      message: '草稿保存状态未确认，请手动检查'
    };
  }
```

**输出提示**：
```
✅ 推文已保存到草稿箱

推文详情：
- 文本：${POST_TEXT_PREVIEW}（${TEXT_LENGTH} 字符）
- 图片数量：${IMAGE_COUNT} 张
- 格式：${如果有格式}含粗体/斜体/链接${否则}纯文本${结束}

草稿位置：https://x.com/compose/post/unsent/drafts
查看方法：访问 X → 点击"发帖"按钮 → 选择"草稿"

如需立即发布，请重新运行并添加 --publish 参数
```

#### 2.7 发布推文（仅当提供 --publish 参数时）

**参数检查**：

```bash
# 检查是否提供 --publish 参数
if [[ "$*" =~ --publish ]]; then
    echo "PUBLISH_MODE"
else
    echo "SKIP_PUBLISH"
    # 跳过 Phase 2.7，流程结束
    exit 0
fi
```

**如果 PUBLISH_MODE，执行以下发布逻辑**：

```javascript
browser_run_code: |
  async (page) => {
    const tweetButton = await page.locator('[data-testid="tweetButton"]');

    // 检查按钮是否启用
    const isEnabled = !await tweetButton.isDisabled();
    if (!isEnabled) {
      return {
        error: '发布按钮被禁用',
        published: false,
        reason: '可能原因：文本为空、图片上传中、或文本超过限制（非 Premium 用户）'
      };
    }

    await tweetButton.click();

    return { published: true };
  }

browser_wait_for: time=3

# 验证发布成功并获取推文 URL
browser_run_code: |
  async (page) => {
    await page.waitForTimeout(2000);  // 等待跳转完成
    const url = page.url();

    // 检查是否跳转到推文详情页
    if (url.includes('/status/')) {
      const match = url.match(/\/status\/(\d+)/);
      const tweetId = match ? match[1] : null;

      return {
        publishSuccess: true,
        tweetUrl: url,
        tweetId: tweetId,
        location: 'status'
      };
    }

    // 跳转到首页（也表示发布成功）
    if (url.includes('/home')) {
      return {
        publishSuccess: true,
        tweetUrl: null,
        location: 'home',
        message: '推文已发布，但跳转到首页，无法直接获取推文链接'
      };
    }

    // 其他情况视为失败
    return {
      publishSuccess: false,
      currentUrl: url,
      message: '发布状态未知，请手动检查'
    };
  }
```

**如果发布成功**：
```
✅ 推文发布成功！

${如果有 tweetUrl}
推文链接：${tweetUrl}
推文 ID：${tweetId}
${否则}
推文已发布到首页，请在 https://x.com/home 查看
${结束}
```

**如果发布失败**：
```
❌ 推文发布失败
原因：${ERROR_REASON}

常见问题：
1. 文本超过280字符且账号不是 X Premium
2. 图片还在上传中
3. 网络问题
4. X 平台临时限制

请检查浏览器中的错误提示
```

---

### Phase 3: 生成执行报告

```markdown
## 推文发布执行报告

### 推文详情
- **文本内容**：${POST_TEXT_PREVIEW}
- **字符数**：${CHARACTER_COUNT}
- **图片数量**：${IMAGE_COUNT} / 4

### 完成项
- ✅ Cookie 验证：已加载 ${COOKIE_COUNT} 个 Cookie
- ✅ 登录状态：已验证
- ✅ 推文文本：已填入（${CHARACTER_COUNT} 字符）
${如果有图片}
- ✅ 图片上传：${IMAGE_COUNT} 张
  ${逐个列出图片路径}
${结束}

### 推文状态
${如果使用 --submit}
  ${如果发布成功}
  - ✅ 已发布
  - 推文链接：${TWEET_URL}
  ${否则}
  - ❌ 发布失败
  - 错误原因：${ERROR_REASON}
  ${结束}
${否则}
  - 📝 草稿预览中（未发布）
  - 请检查预览后使用 --submit 参数发布
${结束}

### 注意事项
${如果 CHARACTER_COUNT > 280}
⚠️ 推文文本超过 280 字符
- 当前字符数：${CHARACTER_COUNT}
- 如果账号是 X Premium：可正常发布（最多支持 25,000 字符）
- 如果是普通账号：发布会被 X 平台拒绝
${结束}
```

---

## 关键规则

1. **Cookie 优先** - 必须先加载 Cookie 再访问 X
2. **图片顺序** - 按提供的顺序上传图片
3. **等待上传** - 每张图片上传后等待 3 秒
4. **默认预览** - 不使用 --submit 时仅预览不发布
5. **验证发布** - 发布后检查 URL 确认成功
6. **长推文支持** - 不限制文本长度，由 X 平台根据账号类型处理

## DOM 选择器参考

```javascript
// 推文文本框
'[data-testid="tweetTextarea_0"]'

// 图片上传 input
'input[type="file"][accept*="image"]'

// 已上传的图片容器
'[data-testid="attachments"] img'

// 发布按钮
'[data-testid="tweetButton"]'

// 登录验证
'[data-testid="primaryColumn"]'
```

## 错误处理

### 图片上传失败

**症状**：图片选择后未显示在预览区域

**原因**：
- 文件格式不支持
- 文件大小超过 5MB
- 文件路径包含特殊字符

**解决方案**：
1. 检查文件格式（仅支持 JPG, PNG, GIF, WebP）
2. 压缩图片到 5MB 以下：
   ```bash
   # Windows
   使用 Paint 或 IrfanView 压缩图片

   # 命令行（如果安装了 ImageMagick）
   magick convert input.jpg -quality 85 -resize 2048x2048> output.jpg
   ```
3. 使用绝对路径或复制文件到无特殊字符的路径

### 推文按钮禁用

**症状**：点击发布时提示 "发布按钮被禁用"

**原因**：
- 文本和图片都为空
- 图片还在上传中
- 文本超过 280 字符且账号不是 X Premium
- 网络问题导致页面状态异常

**解决方案**：
1. 确保至少有文本或图片
2. 等待所有图片上传完成
3. 检查账号是否为 X Premium（如果文本超过 280 字符）
4. 刷新页面重试

### Cookie 过期

**症状**：登录验证失败

**解决方案**：参考 x-article-publisher 的 troubleshooting.md 更新 Cookie

### 长推文被拒绝

**症状**：文本超过 280 字符，发布按钮禁用或显示错误

**原因**：账号不是 X Premium

**解决方案**：
1. 将文本截短到 280 字符以内
2. 或升级账号到 X Premium
3. 或使用 x-article-publisher 发布为长文章

