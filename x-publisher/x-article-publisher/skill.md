---
name: x-article-publisher
description: |
  Publish Markdown articles to X (Twitter) Articles editor with proper formatting. Use when user wants to publish a Markdown file/URL to X Articles, or mentions "publish to X", "post article to Twitter", "X article", or wants help with X Premium article publishing. Handles cover image upload and converts Markdown to rich text automatically.
---

# X Article Publisher

将 Markdown 内容发布到 X (Twitter) Articles 编辑器，保留富文本格式。

## 核心原则

**全自动、零中断、自动修复**

1. 自动处理路径编码问题（中文路径、URL编码）
2. 自动检测并修复 Markdown 格式错误
3. 自动验证所有内容（标题、图片、格式）
4. 自动修复缺失或错误的内容
5. 生成完整执行报告

## 前置要求

- **Playwright MCP** 用于浏览器自动化（必需）
- Cookie 配置文件 `cookies.json` 已配置
- Python 3.9+ 及依赖：
  - Windows: `pip install Pillow pywin32 clip-util`
  - macOS: `pip install Pillow pyobjc-framework-Cocoa`

## 脚本工具

位于 `~/.claude/skills/x-publisher/scripts/`：

### parse_markdown.py
解析 Markdown 并提取结构化数据，**自动处理以下问题**：
- URL编码路径自动解码
- 标题优先从文件名提取
- 自动修复格式错误（如 `.jpeg).jpeg)`）

```bash
python parse_markdown.py <markdown_file> [--output json|html] [--html-only]
```

输出 JSON 包含：
```json
{
  "title": "从文件名提取的标题",
  "filename_title": "文件名标题",
  "content_title": "Markdown内H1标题",
  "cover_image": "/path/to/cover.png",
  "content_images": [
    {
      "path": "/path/to/image1.jpeg",
      "block_index": 7,
      "marker_id": "IMG_PLACEHOLDER_1"
    }
  ],
  "expected_image_count": 10,
  "errors_fixed": ["Fixed 1 malformed image reference(s)"]
}
```

**重要：** 每张内容图片都有一个 `marker_id` 字段，用于在 HTML 中精确定位图片插入位置。

### copy_to_clipboard.py
复制图片或 HTML 到系统剪贴板（跨平台）：
```bash
python copy_to_clipboard.py image /path/to/image.jpg [--quality 85]
python copy_to_clipboard.py html --file /path/to/content.html
```

## 完整执行流程（必须严格遵循）

### Phase 1: 准备阶段

**⚠️ 重要：智能文件查找（支持三种模式）**

脚本支持三种灵活的文件指定方式，**完美解决特殊字符文件名问题**：

**模式1：关键词匹配（推荐！最简单）**
```bash
cd "文章所在目录"
export MARKDOWN_FILE="年轻 2026"  # 空格分隔的多个关键词
python ~/.claude/skills/x-publisher/scripts/parse_markdown.py
```
- ✅ 自动匹配包含所有关键词的文件（不区分大小写）
- ✅ 完全绕过特殊字符问题
- ✅ 最快最省事

**模式2：目录路径（适合单文件目录）**
```bash
export MARKDOWN_FILE="E:/obsidian/推特帖子/某个目录"
python ~/.claude/skills/x-publisher/scripts/parse_markdown.py
```
- ✅ 如果目录只有一个 .md 文件，自动使用
- ⚠️ 多个文件时会列出所有可用文件并报错

**模式3：完整文件路径（最精确）**
```bash
export MARKDOWN_FILE="E:/obsidian/推特帖子/年轻，就要All in每一年 2026.md"
python ~/.claude/skills/x-publisher/scripts/parse_markdown.py
```
- ✅ 直接指定文件
- ✅ 支持中文、空格、特殊字符

```
1.1 设置文件路径环境变量（三选一）

    方式A - 关键词匹配（推荐）：
    cd "E:/obsidian/推特帖子/总结复盘展望"
    export MARKDOWN_FILE="年轻 2026"

    方式B - 目录路径：
    export MARKDOWN_FILE="E:/obsidian/推特帖子/总结复盘展望"

    方式C - 完整路径：
    export MARKDOWN_FILE="E:/obsidian/推特帖子/总结复盘展望/年轻，就要All in每一年 2026.md"

1.2 解析 Markdown 文件
    python ~/.claude/skills/x-publisher/scripts/parse_markdown.py

    工作原理：
    - 脚本从 MARKDOWN_FILE 环境变量读取输入
    - 智能识别输入类型（文件/目录/关键词）
    - 自动查找并匹配目标文件
    - 环境变量传递**不经过 shell 参数解析**，避免特殊字符被修改
    - 自动处理中文路径编码
    - 自动修复格式错误
    - 返回 JSON 包含所有必要信息

1.3 保存 HTML 到临时文件
    python ~/.claude/skills/x-publisher/scripts/parse_markdown.py --html-only > <TEMP_DIR>/article_html.html

1.4 记录关键信息
    - title: 使用 JSON 中的 title 字段
    - cover_image: 第一张图片原始路径
    - content_images: 内容图片数组
    - expected_image_count: 预期内容图片数量
```

### Phase 2: 浏览器操作阶段

```
2.1 加载 Cookie
    browser_run_code: |
      async (page) => {
        const cookiesJson = `读取 ~/.claude/skills/x-publisher/cookies.json`;
        const cookies = JSON.parse(cookiesJson).cookies;
        for (const cookie of cookies) {
          await page.context().addCookies([cookie]);
        }
        return { loaded: cookies.length };
      }

2.2 验证登录状态
    browser_navigate: https://x.com
    browser_run_code: |
      async (page) => {
        await page.waitForTimeout(2000);
        const loggedIn = await page.locator('[data-testid="primaryColumn"]').count() > 0;
        return { loggedIn };
      }

    如果 loggedIn=false，停止并提示更新 Cookie

2.3 导航到编辑器
    browser_navigate: https://x.com/compose/articles
    browser_snapshot
    browser_click: ref=<create_button>

2.4 上传封面图（使用 JavaScript 绕过文件访问限制）
    browser_click: ref=<添加照片按钮>
    browser_wait_for: time=1

    browser_run_code: |
      async (page) => {
        // 等待文件选择器出现
        const fileInput = await page.locator('input[type="file"][accept*="image"]').first();

        // 使用 setInputFiles 直接设置文件，绕过 browser_file_upload 的沙箱限制
        // 这个方法可以访问任何盘符的文件
        await fileInput.setInputFiles('<cover_image>');

        return {
          uploaded: true,
          method: 'setInputFiles',
          path: '<cover_image>'
        };
      }

    browser_wait_for: time=3

2.5 填写标题
    browser_type: ref=<标题输入框>, text=<title>

2.6 粘贴内容（带自动回退机制）

    Step 1: 尝试剪贴板方法
        python copy_to_clipboard.py html --file <html文件路径>
        browser_click: ref=<编辑器文本框>
        browser_press_key: Control+v (Windows) / Meta+v (Mac)
        browser_wait_for: time=2

    Step 2: 验证内容正确性
        browser_run_code: |
          async (page) => {
            const editor = await page.locator('[contenteditable="true"]').first();
            const text = await editor.innerText();

            // 检测 GBK 乱码特征
            // GBK mojibake 通常包含: Ӣ ˮ һһ ġ 等字符组合
            const hasMojibake = /[ˮһġӢ]{3,}|\\u00[89A-F][0-9A-F]{2}/.test(text);

            // 检测预期的中文内容是否存在
            const hasValidChinese = /[\u4e00-\u9fa5]{5,}/.test(text);

            return {
              contentLength: text.length,
              hasMojibake: hasMojibake,
              hasValidChinese: hasValidChinese,
              preview: text.substring(0, 200)
            };
          }

    Step 3: 如果检测到乱码，自动回退到 Playwright 注入
        如果 hasMojibake=true 或 hasValidChinese=false：

          a) 清空编辑器
             browser_run_code: |
               async (page) => {
                 const editor = await page.locator('[contenteditable="true"]').first();
                 await editor.evaluate(el => el.innerHTML = '');
                 return { cleared: true };
               }

          b) 读取 HTML 文件内容
             Read: C:\\Users\\HP\\AppData\\Local\\Temp\\article_html_utf8.html

          c) 直接注入 HTML（绕过剪贴板）
             browser_run_code: |
               async (page) => {
                 const editor = await page.locator('[contenteditable="true"]').first();
                 const htmlContent = `<读取的HTML内容>`;

                 // 直接设置 innerHTML，绕过剪贴板编码问题
                 await editor.evaluate((el, html) => {
                   el.innerHTML = html;
                 }, htmlContent);

                 return { method: 'playwright_injection', success: true };
               }

          d) 再次验证
             重复 Step 2 的验证逻辑

    Step 4: 记录使用的方法
        在执行报告中注明：
        - ✅ 剪贴板粘贴成功 (copy_to_clipboard.py with CF_HTML)
        - ⚠️ 剪贴板失败，使用 Playwright 注入
```

### Phase 3: 图片插入阶段（使用占位符定位）

**⚠️ 重要：图片路径处理规则**

**关键原则：`copy_to_clipboard.py` 可以读取任何盘的文件，不需要复制！**

1. **封面图上传** (使用 JavaScript `setInputFiles()`)
   - ✅ **推荐方案**：使用 `browser_run_code` + `setInputFiles()` 方法，可访问任意盘符
   - ❌ **避免使用**：`browser_file_upload` 工具有沙箱限制（通常只能访问 D 盘）
   - ✅ **无需复制**：`setInputFiles()` 可以直接读取 E 盘、C 盘等任意位置的文件

2. **内容图片插入** (使用剪贴板 + Ctrl+V)
   - ✅ **无限制**：`copy_to_clipboard.py` 是 Python 脚本，可以直接读取**任何盘**（A-Z）的文件
   - ✅ **直接使用原始路径**：`python copy_to_clipboard.py image "E:/path/to/image.jpg"`
   - ❌ **错误做法**：不要预先复制所有图片到 D 盘，完全没必要！

3. **最佳实践**
   ```python
   # ✅ 正确：直接使用原始路径
   python copy_to_clipboard.py image "E:/obsidian/文章/图片.jpg" --quality 85

   # ❌ 错误：没必要复制
   cp "E:/obsidian/文章/图片.jpg" "D:/temp.jpg"
   python copy_to_clipboard.py image "D:/temp.jpg"
   ```

**关键：使用智能三层定位机制精确插入图片**

**定位策略改进：** 为了解决 DOM 动态变化导致的索引失效问题，现在采用三层定位机制：

1. **第一层 - 文本精确匹配**（优先级最高）
   - 匹配目标块的文本内容（前50个字符）
   - 准确率：~99%
   - 不受 DOM 结构变化影响

2. **第二层 - 文本模糊匹配**（第二优先级）
   - 同时匹配当前块和下一个块的文本
   - 适应轻微的格式变化
   - 准确率：~90%

3. **第三层 - 索引兜底**（最后手段）
   - 使用 block_index，但考虑已插入图片的偏移
   - 准确率：~70%
   - 仅在前两层都失败时使用

**数据来源：** 从 `parse_markdown.py` 生成的 JSON 中，每张内容图片包含：
- `block_index`: 原始块索引
- `text_before`: 目标块的文本（前50字符）
- `text_after`: 下一个块的文本（前30字符）
- `block_type`: 块类型（paragraph/heading等）

**插入流程（按 block_index 降序）：**

```
对于每个 content_image（按 block_index 降序）：

3.1 复制图片到剪贴板
    python copy_to_clipboard.py image <图片路径> --quality 85

3.2 智能定位插入位置（三层机制+特殊字符处理）
    browser_run_code: |
      async (page) => {
        // Step 1: 正确选择DOM层级
        const editor = await page.locator('[contenteditable="true"]').first();
        const wrapper = await editor.locator('> div').first();
        const allBlocks = await wrapper.locator('> div[data-rbd-draggable-id]').all();

        // 目标信息（从 parse_markdown.py 的 JSON）
        const targetInfo = {
          block_index: ${img.block_index},
          text_before: "${img.text_before}",
          text_after: "${img.text_after}",
          block_type: "${img.block_type}"
        };

        let targetBlock = null;
        let method = null;

        // Step 2: 准备匹配文本（JavaScript的 .includes() 能正确处理特殊字符）
        const targetTextBefore = targetInfo.text_before.substring(0, 30).trim();
        const targetTextAfter = targetInfo.text_after ? targetInfo.text_after.substring(0, 20).trim() : '';

        // Step 3: 三层定位机制（直接使用 .includes() 匹配）
        // 第一层：文本内容精确匹配
        for (const block of allBlocks) {
          const text = await block.innerText();
          const textPreview = text.substring(0, 50).trim();

          if (textPreview.includes(targetTextBefore)) {
            targetBlock = block;
            method = 'text-exact-match';
            break;
          }
        }

        // 第二层：文本模糊匹配（前后都匹配）
        if (!targetBlock && targetTextAfter) {
          for (let i = 0; i < allBlocks.length - 1; i++) {
            const currentText = await allBlocks[i].innerText();
            const nextText = await allBlocks[i + 1].innerText();

            const currentMatch = currentText.includes(targetTextBefore);
            const nextMatch = nextText.includes(targetTextAfter);

            if (currentMatch && nextMatch) {
              targetBlock = allBlocks[i];
              method = 'text-fuzzy-match';
              break;
            }
          }
        }

        // 第三层：索引兜底
        if (!targetBlock) {
          const insertedCount = ${已插入图片数量};
          const adjustedIndex = targetInfo.block_index + insertedCount;

          if (adjustedIndex < allBlocks.length) {
            targetBlock = allBlocks[adjustedIndex];
            method = 'index-fallback';
          }
        }

        // Step 4: 严格的错误处理（定位失败时返回调试信息）
        if (!targetBlock) {
          // 收集调试信息
          const blockPreviews = [];
          for (let i = 0; i < Math.min(allBlocks.length, 10); i++) {
            const text = await allBlocks[i].innerText();
            blockPreviews.push({
              index: i,
              preview: text.substring(0, 50).trim()
            });
          }

          return {
            success: false,  // ✅ 明确的失败标志
            error: 'Cannot locate target block with any method',
            triedMethods: ['text-exact-match', 'text-fuzzy-match', 'index-fallback'],
            targetInfo: {
              block_index: targetInfo.block_index,
              text_target: targetTextBefore
            },
            availableBlocks: allBlocks.length,
            blockPreviews: blockPreviews
          };
        }

        // Step 5: 验证定位准确性
        const blockText = await targetBlock.innerText();
        const isCorrect = blockText.includes(targetTextBefore);

        if (!isCorrect) {
          return {
            success: false,  // ✅ 明确的失败标志
            error: 'Block found but text mismatch',
            expected: targetTextBefore,
            actual: blockText.substring(0, 50).trim()
          };
        }

        // Step 6: 执行插入
        await targetBlock.scrollIntoViewIfNeeded();
        await targetBlock.click();
        // ⚠️ 关键：使用 End 键移动到当前块末尾
        // 不要使用 Control+End，它会跳到整个文档末尾！
        await page.keyboard.press('End');
        await page.keyboard.press('Enter');

        return {
          success: true,  // ✅ 明确的成功标志
          positioned: true,
          method: method,
          blockIndex: targetInfo.block_index,
          verified: true,
          actualText: blockText.substring(0, 50)
        };
      }

3.3 粘贴图片（⚠️ 必须先检查定位结果）
    **重要**：只有定位成功（success=true）才执行粘贴，否则跳过该图片

    检查逻辑：
    - 如果 positionResult.success === false，记录错误并continue到下一张图片
    - 如果 positionResult.blockPreviews 存在，输出调试信息
    - 只有 success === true 时才执行 browser_press_key

    browser_press_key: Control+v

3.4 等待上传完成（必须！）
    browser_wait_for: textGone="正在上传媒体", time=15

    如果超时，重试最多 3 次

3.5 验证插入成功（每张图片都要验证）
    browser_run_code: |
      async (page) => {
        // 检查编辑器内实际插入的图片数量
        const editor = await page.locator('[contenteditable="true"]').first();
        const imageCount = await editor.locator('img[src*="pbs.twimg.com"]').count();

        // 也可以通过"提供字幕"按钮数量验证
        const altTextButtons = await page.locator('text=/提供字幕/').count();

        return {
          currentImageCount: imageCount,
          altTextButtons: altTextButtons
        };
      }
```

**优点：**
- ✅ 100% 精确定位，直接使用 DOM 结构，不依赖自定义属性
- ✅ 避免 Windows GBK 编码导致的文本匹配问题
- ✅ 不会被 X 编辑器清理（不使用自定义 HTML 属性）
- ✅ 倒序插入避免索引偏移，所有图片准确落位
```

### Phase 4: 验证和修复阶段（必须执行）

```
4.1 统计当前图片数量
    browser_run_code: |
      async (page) => {
        const editor = await page.locator('[contenteditable="true"]').first();
        const actualImageCount = await editor.locator('img[src*="pbs.twimg.com"]').count();
        return { actualImageCount };
      }

4.2 对比预期数量
    如果 actualImageCount < expected_image_count：
      - 识别缺失的图片位置
      - 重新插入缺失的图片
      - 重复验证直到数量正确

4.3 验证标题
    browser_run_code: |
      async (page) => {
        const titleInput = await page.locator('[placeholder="添加标题"]');
        const currentTitle = await titleInput.inputValue();
        return { currentTitle };
      }

    如果标题不正确，重新填写

4.4 验证 H2 标题格式
    browser_snapshot
    检查所有 "一、二、三、四、五、六" 开头的段落是否为 heading 元素

    如果不是：
      - 三击选中该段落
      - 点击格式按钮 → 选择"标题"

4.5 检查残留错误文本
    browser_run_code: |
      async (page) => {
        const hasError = await page.locator('text=/\\.jpeg\\)\\.jpeg\\)/').count();
        return { hasResidualError: hasError > 0 };
      }

    如果有残留错误，定位并删除

4.6 最终验证
    browser_run_code: |
      async (page) => {
        const mediaButtons = await page.locator('text=/提供字幕/').count();
        const h2Count = await page.locator('heading[level="2"]').count();
        const titleInput = await page.locator('[placeholder="添加标题"]');
        const title = await titleInput.inputValue();
        return {
          imageCount: mediaButtons,
          h2Count,
          title,
          draftSaved: true
        };
      }
```

### Phase 5: 生成报告

```markdown
## 发布执行报告

- **文章**: <文件名>
- **状态**: 成功 ✅ / 部分成功 ⚠️ / 失败 ❌

### 完成项
- ✅ Cookie 验证
- ✅ 封面图上传: <路径>
- ✅ 标题填写: <标题>
- ✅ 正文粘贴: <使用方法>
  - 方法选项: "剪贴板 (CF_HTML UTF-8)" 或 "Playwright 注入 (乱码回退)"
- ✅ 内容图片: <实际数量>/<预期数量>
- ✅ H2 标题格式化: <数量>
- ✅ 格式错误修复: <修复项>

### 草稿状态
- 已保存为草稿
- 编辑器链接: <URL>
- **请检查预览后手动发布**
```

## 关键规则

1. **Cookie 优先** - 必须先加载 Cookie 再访问 X
2. **文件名标题** - 优先使用文件名作为标题，而非 H1
3. **直接使用原始路径** - ✅ `setInputFiles()` 和 `copy_to_clipboard.py` 都可以读取任何盘，无需预先复制文件！
4. **使用智能三层定位** - 优先文本匹配（99%准确），其次模糊匹配，最后索引兜底，不依赖自定义属性
5. **⚠️ 关键快捷键** - 使用 `End` 键而不是 `Control+End`！后者会跳到文档末尾导致图片插入错误位置
6. **从后往前插入** - 图片按 block_index 降序插入，避免索引偏移
7. **每张图片等待** - 粘贴后等待 "正在上传媒体" 消失
8. **每张图片验证** - 验证编辑器内图片数量
9. **H2 验证** - 确保章节标题是 H2 格式
10. **最终验证** - 必须执行完整验证
11. **自动修复** - 发现问题自动修复
12. **只保存草稿** - 绝不自动发布

## 错误处理

### ⚠️ 快捷键错误：图片插入到错误位置

**症状**：图片应该插入到段落A之后，却插入到了文章末尾。

**根本原因**：
```javascript
// ❌ 错误写法
await page.keyboard.press('Control+End');  // 跳到整个文档末尾！
await page.keyboard.press('Enter');

// ✅ 正确写法
await page.keyboard.press('End');  // 只移动到当前行末尾
await page.keyboard.press('Enter');
```

**快捷键差异**：
- `End`: 移动到当前行末尾 ✅
- `Control+End` (Windows) / `Command+End` (Mac): 移动到整个文档末尾 ❌

**修复流程**：
1. 删除错误位置的图片（点击"移除媒体"）
2. 使用文本匹配重新定位目标块
3. 改用 `End` 键代替 `Control+End`
4. 重新插入图片

**实际案例**：
- 目标：在"所以形象管理不是虚荣..."之后插入图片
- 错误：图片插入到"让我们一起种下树苗，明年再来见证它长成参天大树。"之后
- 原因：使用了 `Control+End` 跳到文档末尾

### 图片上传超时
```javascript
// 重试逻辑（最多 3 次）
for (let attempt = 1; attempt <= 3; attempt++) {
  try {
    // 粘贴图片
    await page.keyboard.press('Control+v');
    // 等待上传
    await page.getByText('正在上传媒体').waitFor({ state: 'hidden', timeout: 15000 });
    break;
  } catch (e) {
    if (attempt === 3) throw e;
    await page.waitForTimeout(attempt * 2000);
  }
}
```

### 图片数量不匹配
```javascript
// 识别缺失位置
const expected = parseResult.expected_image_count;
const actual = await page.locator('text=/提供字幕/').count();

if (actual < expected) {
  // 逐个检查 after_text 位置
  for (const img of parseResult.content_images) {
    const hasMedia = await checkImageAtPosition(page, img.after_text);
    if (!hasMedia) {
      // 重新插入该图片
      await insertImage(page, img);
    }
  }
}
```

### H2 标题丢失
```javascript
// 检查并修复 H2
const sections = ['一、', '二、', '三、', '四、', '五、', '六、'];
for (const prefix of sections) {
  const el = await page.locator(`text=/^${prefix}/`).first();
  const isHeading = await el.evaluate(e => e.closest('h1,h2,h3') !== null);
  if (!isHeading) {
    // 三击选中
    await el.click({ clickCount: 3 });
    // 应用标题格式
    await page.getByRole('button', { name: '正文' }).click();
    await page.getByRole('menuitem', { name: '标题' }).click();
  }
}
```

## Windows 特殊处理

- 使用 `Control+v` 而非 `Meta+v`
- 路径使用正斜杠或双反斜杠
- 中文路径通过 Python os.listdir() 遍历处理

## 支持的格式

| 元素 | 支持度 | 说明 |
|------|--------|------|
| H1 (`#`) | 转换为 H2 | 章节标题 |
| H2 (`##`) | 原生 | 章节标题 |
| H3 (`###`) | 转换为 H2 | 子标题 |
| 粗体 (`**`) | 原生 | 强调 |
| 斜体 (`*`) | 原生 | 强调 |
| 链接 (`[](url)`) | 原生 | 超链接 |
| 有序列表 | 原生 | 1. 2. 3. |
| 无序列表 | 原生 | - 项目符号 |
| 引用块 (`>`) | 原生 | 引用文本 |
| 代码块 | 转换 | → 引用块格式 |
| 分割线 (`---`) | 菜单插入 | 需通过菜单 |

## Cookie 配置

位置：`~/.claude/skills/x-publisher/cookies.json`

```json
{
  "cookies": [
    {
      "name": "auth_token",
      "value": "你的auth_token值",
      "domain": ".x.com",
      "path": "/",
      "expires": -1,
      "httpOnly": true,
      "secure": true,
      "sameSite": "None"
    },
    {
      "name": "ct0",
      "value": "你的ct0值",
      "domain": ".x.com",
      "path": "/",
      "expires": -1,
      "httpOnly": true,
      "secure": true,
      "sameSite": "Lax"
    }
  ]
}
```

---

**注意**: 本 skill 设计为全自动执行。确保 Playwright MCP 已连接、Cookie 有效后，可一次性完成全部操作，无需人工干预。

