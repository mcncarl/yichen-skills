---
name: x-post-with-video
description: |
  Publish text posts with video to X (Twitter). Supports unlimited text length for X Premium users. Use when user wants to post tweets with video, mentions "post video", "tweet with video", or provides text content and video file path.
---

# X Post with Video

发布带视频的 X 推文（文本 + 视频），支持 X Premium 长推文。

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
  - **支持媒体嵌入**：`![](path.mp4)` 会自动提取并上传视频
- `VIDEO_PATH`：视频文件路径（可选）
  - 如果 POST_TEXT 中包含 `![](path.mp4)`，会自动提取
  - 支持格式：MP4, MOV, WebM
  - 最大文件大小：512MB
  - 最长时长：140秒（2分20秒）对于普通用户
  - X Premium 用户：最长 60 分钟
  - 推荐分辨率：1280x720 或更高
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
```

1.2 验证 VIDEO_PATH
```bash
检查文件是否存在
检查文件格式（MP4/MOV/WebM）
检查文件大小（不超过 512MB）

提示：无法自动检测时长，用户需自行确保：
- 普通用户：不超过 140 秒
- X Premium 用户：不超过 60 分钟
```

1.3 记录执行参数
```
- 推文文本字符数
- 视频文件路径和文件大小
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

**如果 loggedIn=false**，停止并提示更新 Cookie（参考 x-post-with-images）

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
3. 提取 `![](path.mp4)` 视频文件路径
4. 保留段落换行（`\n\n`）
5. 输出 JSON 格式：`{"text": "处理后文本", "media_files": ["path.mp4"]}`

**输出提示**：
```
✅ Markdown 处理完成
- 原始文本：${CHARACTER_COUNT_BEFORE} 字符
- 处理后：${CHARACTER_COUNT_AFTER} 字符
- 提取视频：${VIDEO_COUNT} 个文件
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

#### 2.5 上传视频

```javascript
browser_run_code: |
  async (page) => {
    const fileInput = await page.locator('input[type="file"][accept*="video"]').first();

    // 使用 setInputFiles 直接设置文件
    await fileInput.setInputFiles('${VIDEO_PATH}');

    return {
      uploaded: true,
      path: '${VIDEO_PATH}',
      size: require('fs').statSync('${VIDEO_PATH}').size
    };
  }

browser_wait_for: time=5  # 初始等待5秒让视频开始上传
```

**输出提示**：`✅ 视频已选择：${VIDEO_PATH}（${SIZE_MB} MB）`
**输出提示**：`⏳ 正在上传和处理视频...`

#### 2.6 等待视频处理完成（关键步骤！）

这是视频推文最关键的部分。X 需要处理视频，可能需要 30-180 秒。

```javascript
browser_run_code: |
  async (page) => {
    let processed = false;
    let attempts = 0;
    const maxAttempts = 60;  // 最多等待 180 秒（60 次 * 3 秒）

    for (let i = 0; i < maxAttempts; i++) {
      await page.waitForTimeout(3000);
      attempts = i + 1;

      // 检查是否有"正在上传媒体"文本
      const uploading = await page.getByText('正在上传媒体').count() > 0;

      // 检查发布按钮是否启用
      const tweetButton = await page.locator('[data-testid="tweetButton"]');
      const buttonEnabled = !await tweetButton.isDisabled();

      // 检查是否有错误提示
      const hasError = await page.getByText(/无法上传|上传失败|文件太大|视频太长/).count() > 0;

      if (hasError) {
        const errorText = await page.getByText(/无法上传|上传失败|文件太大|视频太长/).first().textContent();
        return {
          processed: false,
          error: 'Upload failed',
          errorMessage: errorText,
          attempts: attempts
        };
      }

      if (!uploading && buttonEnabled) {
        processed = true;
        break;
      }

      // 每10秒输出进度提示
      if (attempts > 0 && attempts % 10 === 0) {
        console.log(`[x-post-with-video] 视频仍在处理中... (已等待 ${attempts * 3} 秒)`);
      }
    }

    return {
      processed,
      attempts: attempts,
      totalWaitTime: attempts * 3
    };
  }
```

**如果 processed=false**，停止并输出：
```
❌ 视频处理超时或失败

处理时间：${TOTAL_WAIT_TIME} 秒
错误信息：${ERROR_MESSAGE}（如果有）

常见原因：
1. 视频文件过大（超过 512MB）
2. 视频时长超限（普通用户 140 秒，Premium 60 分钟）
3. 网络速度慢
4. X 服务器负载高
5. 视频编码格式不支持

解决方案：
- 压缩视频文件
- 使用 H.264 编码的 MP4 格式
- 检查网络连接
- 稍后重试

详见 references/troubleshooting.md
```

**如果 processed=true**：
```
✅ 视频处理完成
处理时间：${TOTAL_WAIT_TIME} 秒
```

#### 2.7 保存到草稿箱（默认行为）

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
- 视频：${VIDEO_FILENAME}（${FILE_SIZE_MB} MB）
- 处理时间：${PROCESSING_TIME} 秒
- 格式：${如果有格式}含粗体/斜体/链接${否则}纯文本${结束}

草稿位置：https://x.com/compose/post/unsent/drafts
查看方法：访问 X → 点击"发帖"按钮 → 选择"草稿"

如需立即发布，请重新运行并添加 --publish 参数
```

#### 2.8 发布推文（仅当提供 --publish 参数时）

**参数检查**：

```bash
# 检查是否提供 --publish 参数
if [[ "$*" =~ --publish ]]; then
    echo "PUBLISH_MODE"
else
    echo "SKIP_PUBLISH"
    # 跳过 Phase 2.8，流程结束
    exit 0
fi
```

**如果 PUBLISH_MODE，执行以下发布逻辑**：

```javascript
browser_run_code: |
  async (page) => {
    const tweetButton = await page.locator('[data-testid="tweetButton"]');

    const isEnabled = !await tweetButton.isDisabled();
    if (!isEnabled) {
      return {
        error: '发布按钮被禁用',
        published: false,
        reason: '可能原因：文本为空、视频处理中、或文本超过限制（非 Premium 用户）'
      };
    }

    await tweetButton.click();

    return { published: true };
  }

browser_wait_for: time=5  # 视频推文发布可能需要更长时间

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
✅ 视频推文发布成功！

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
2. 视频还在处理中
3. 网络问题
4. X 平台临时限制

请检查浏览器中的错误提示
```

---

### Phase 3: 生成执行报告

```markdown
## 视频推文执行报告

### 推文详情
- **文本内容**：${POST_TEXT_PREVIEW}
- **字符数**：${CHARACTER_COUNT}
- **视频文件**：${VIDEO_FILENAME}
- **文件大小**：${FILE_SIZE_MB} MB
- **处理时间**：${PROCESSING_TIME} 秒

### 完成项
- ✅ Cookie 验证：已加载 ${COOKIE_COUNT} 个 Cookie
- ✅ 登录状态：已验证
- ✅ 推文文本：已填入（${CHARACTER_COUNT} 字符）
- ✅ 视频上传：成功
- ✅ 视频处理：完成（${PROCESSING_TIME} 秒）

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
- 如果账号是 X Premium：可正常发布
- 如果是普通账号：发布会被 X 平台拒绝
${结束}

${如果 PROCESSING_TIME > 120}
⚠️ 视频处理时间较长（${PROCESSING_TIME} 秒）
- 这通常表示视频文件较大或网络较慢
- 建议压缩视频以加快处理速度
${结束}
```

---

## 关键规则

1. **Cookie 优先** - 必须先加载 Cookie
2. **等待处理** - 视频处理最多等待 180 秒
3. **进度监控** - 每10秒输出处理进度
4. **错误检测** - 自动检测上传失败并终止
5. **默认预览** - 不使用 --submit 时仅预览不发布
6. **长推文支持** - 不限制文本长度，由 X 平台根据账号类型处理

## DOM 选择器参考

```javascript
// 推文文本框
'[data-testid="tweetTextarea_0"]'

// 视频上传 input
'input[type="file"][accept*="video"]'

// 上传进度提示
'text=/正在上传媒体/'

// 发布按钮
'[data-testid="tweetButton"]'

// 错误提示
'text=/无法上传|上传失败|文件太大|视频太长/'
```

## 视频要求

### 文件格式
- **推荐**：MP4 (H.264 编码 + AAC 音频)
- **支持**：MOV, WebM
- **不支持**：AVI, MKV, FLV

### 文件大小
- **最大**：512MB
- **推荐**：< 100MB（处理更快）

### 视频时长
- **普通用户**：最长 140 秒（2 分 20 秒）
- **X Premium**：最长 60 分钟

### 分辨率
- **最小**：32 x 32 像素
- **最大**：1920 x 1200 像素（或 1200 x 1920 纵向）
- **推荐**：1280 x 720 (720p) 或 1920 x 1080 (1080p)

### 帧率
- **最大**：40 FPS
- **推荐**：30 FPS

### 比特率
- **最大**：25 Mbps
- **推荐**：5-10 Mbps

## 视频压缩建议

如果视频文件过大或处理超时，使用以下命令压缩：

### Windows（使用 FFmpeg）
```bash
ffmpeg -i input.mp4 -vcodec h264 -acodec aac -b:v 1M output.mp4
```

### 降低分辨率到 720p
```bash
ffmpeg -i input.mp4 -vf scale=1280:720 -b:v 1M output.mp4
```

### 截取前 140 秒
```bash
ffmpeg -i input.mp4 -t 140 -c copy output.mp4
```

### 降低帧率到 30 FPS
```bash
ffmpeg -i input.mp4 -r 30 -b:v 1M output.mp4
```

## 错误处理

详见 `references/troubleshooting.md`

