# 故障排除指南

X Article Publisher 常见问题及解决方案。

## MCP 连接问题

### Playwright MCP 工具不可用

**症状**: 报错 `No such tool available` 或 `Not connected`

**解决方案**:

**方案 1：重新连接 MCP（推荐）**
```
执行 /mcp 命令，选择 playwright，选择 Restart
```

**方案 2：清理残留进程后重连**
```bash
# 杀掉所有残留的 playwright 进程
pkill -f "mcp-server-playwright"
pkill -f "@playwright/mcp"

# 然后执行 /mcp 重新连接
```

**配置文件位置**: `~/.claude/mcp_servers.json`

---

## 浏览器错误

### Browser is already in use

**症状**: 报错 `Error: Browser is already in use`

**解决方案**:

**方案 1：先关闭浏览器再重新打开**
```
browser_close
browser_navigate: https://x.com/compose/articles
```

**方案 2：杀掉 Chrome 进程**
```bash
pkill -f "Chrome.*--remote-debugging"
# 然后重新 navigate
```

**方案 3：使用已有标签页，直接导航**
```
browser_tabs action=list  # 查看现有标签
browser_navigate: https://x.com/compose/articles  # 在当前标签导航
```

**最佳实践**：每次开始前先用 `browser_tabs action=list` 检查状态，避免创建多余空白标签。

---

## Cookie 问题

### Cookie 已过期

**症状**: 加载 Cookie 后访问 x.com 仍显示登录页面

**验证方法**:
```javascript
browser_run_code: |
  async (page) => {
    await page.goto('https://x.com');
    const hasAvatar = await page.locator('[data-testid="primaryColumn"] img').count() > 0;
    return { loggedIn: hasAvatar };
  }
```

如果返回 `loggedIn: false`，说明 Cookie 已过期。

**解决方案**:
1. 在浏览器中重新登录 https://x.com
2. 按 F12 打开开发者工具
3. Application → Cookies → https://x.com
4. 复制 `auth_token` 和 `ct0` 的新值
5. 更新 `cookies.json` 文件

**注意**: `auth_token` 通常有效期为几天到几周，需要定期更新。

---

## 图片相关问题

### 图片位置偏移

**症状**: 图片插入位置不正确（特别是点击含链接的段落时）

**原因**: 点击段落时可能误触链接，导致光标位置错误

**解决方案**: 点击后**必须按 End 键**移动光标到行尾

```
# 正确流程
1. browser_click 点击目标段落
2. browser_press_key: End        # 关键步骤！
3. browser_press_key: Meta+v     # 粘贴图片
4. browser_wait_for textGone="正在上传媒体"
```

### 图片路径找不到

**症状**: Markdown 中的相对路径图片找不到（如 `./assets/image.png` 实际在其他位置）

**自动搜索**: `parse_markdown.py` 会自动在以下目录搜索同名文件：
- `~/Downloads`
- `~/Desktop`
- `~/Pictures`

**stderr 输出示例**:
```
[parse_markdown] Image not found at '/path/to/assets/img.png', using '/Users/xxx/Downloads/img.png' instead
```

**JSON 字段说明**:
- `original_path`: Markdown 中指定的路径（解析后的绝对路径）
- `path`: 实际使用的路径（如果自动搜索成功，会不同于 original_path）
- `exists`: `true` 表示找到文件，`false` 表示未找到（上传会失败）

**如果仍然找不到**:
1. 检查 JSON 输出中的 `missing_images` 字段
2. 手动将图片复制到 Markdown 文件同目录的 `assets/` 子目录
3. 或修改 Markdown 中的图片路径为绝对路径

### 图片缺失问题

**症状**: 插入完成后图片数量少于预期（例如预期 10 张，实际只有 9 张）

**原因**:
1. **上传过程中被打断**：在前一张图片还在上传时就插入下一张，导致后续图片插入失败
2. **从后往前插入时的遗漏**：某张图片上传失败，但后续图片继续插入，导致该位置缺失
3. **X 的媒体限制**：某些图片可能因为文件大小超过限制而没有成功上传

**解决方案**:
1. **每张图片插入后等待上传完成**（必须）：
   ```
   browser_press_key: Control+v
   browser_wait_for textGone="正在上传媒体"
   ```

2. **最终验证并补充缺失图片**：参考主文档的"最终验证"部分

3. **失败重试机制**：如果某张图片插入失败，等待 1 秒后重试（最多 3 次）

**预防措施**:
- 每次插入图片后都等待 `textGone="正在上传媒体"` 消失
- 最后验证图片数量是否正确
- 如果数量不对，逐个检查并重新插入

---

## 网络超时问题

### 图片上传超时

**症状**: `browser_wait_for` 超时，"正在上传媒体" 未消失

**自动重试机制**:

```javascript
// 带重试的图片插入
async function insertImageWithRetry(page, afterText, maxRetries = 3) {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      // 定位段落
      const textElements = await page.locator(`text=/${afterText}/`).all();
      // ... 点击、粘贴、等待
      
      // 验证
      const inserted = await verifyImageInserted(page, afterText);
      if (inserted) return { success: true };
      
      // 失败则等待后重试（递增间隔）
      if (attempt < maxRetries) {
        await page.waitForTimeout(attempt * 1000); // 1s, 2s, 3s
      }
    } catch (error) {
      if (attempt === maxRetries) throw error;
      await page.waitForTimeout(attempt * 1000);
    }
  }
  return { success: false };
}
```

**重试策略**:
- 最多 3 次
- 间隔递增：1s → 2s → 4s
- 每次重试前重新获取页面状态

---

## 页面加载问题

### 编辑器未正确打开

**症状**: 导航到 `x.com/compose/articles` 后找不到编辑器元素

**原因**: 页面默认显示草稿列表，需要点击 "Create" 按钮才能打开编辑器

**正确流程**:
```
# 1. 导航到页面
browser_navigate: https://x.com/compose/articles

# 2. 获取页面快照，找到 create 按钮
browser_snapshot

# 3. 点击 create 按钮
browser_click: element="create button", ref=<create_button_ref>

# 4. 现在编辑器应该打开了
```

**注意**: 不要使用 `browser_wait_for text="添加标题"` 等待页面加载，因为这个文本只在点击 create 后才出现，会导致超时。

---

## 格式问题

### 分割线未显示

**症状**: Markdown 中的 `---` 未在 X Articles 中显示为分割线

**原因**: X Articles 忽略 HTML `<hr>` 标签

**解决方案**: 必须通过 Insert > Divider 菜单插入，详见主文档 Step 9

### 表格显示异常

**症状**: Markdown 表格在 X Articles 中格式错乱

**解决方案**: 使用 `table_to_image.py` 将表格转换为 PNG 图片：
```bash
python ~/.claude/skills/x-article-publisher/scripts/table_to_image.py table.md table.png
```

然后在 Markdown 中替换为图片：
```markdown
![Table](table.png)
```

---

## 依赖问题

### Python 依赖缺失

**症状**: 运行脚本时报错 `ModuleNotFoundError`

**解决方案**:

**macOS**:
```bash
pip install Pillow pyobjc-framework-Cocoa
```

**Windows**:
```bash
pip install Pillow pywin32 clip-util
```

**Linux**:
```bash
pip install Pillow
# 注意：Linux 剪贴板功能当前未实现
```

### Mermaid CLI 未安装

**症状**: 转换 Mermaid 图表时报错 `mmdc: command not found`

**解决方案**:
```bash
npm install -g @mermaid-js/mermaid-cli
```

---

## 执行失败恢复

### 操作原子性失败

**症状**: 发布过程中某一步失败，留下半成品文章

**处理策略**:

1. **记录当前状态**（主文档已包含执行报告生成）
2. **尝试继续**: 失败后重试该步骤（最多 3 次）
3. **生成报告**: 告知用户哪些成功、哪些失败

**手动恢复步骤**:
1. 检查 X Articles 草稿箱中的文章状态
2. 根据执行报告，手动插入缺失的图片或分割线
3. 检查格式是否正确
4. 手动发布

---

## 联系与支持

如遇到未列出的问题：

1. 检查主文档的 "Critical Rules" 和 "Best Practices" 章节
2. 查看执行报告中的错误信息
3. 尝试手动执行失败的步骤以定位问题
4. 记录问题详情（错误信息、操作步骤、环境信息）以便排查

