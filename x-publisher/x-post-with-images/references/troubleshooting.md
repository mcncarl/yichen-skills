# x-post-with-images 故障排除

## 常见问题

### 1. 图片上传失败

**症状**：图片选择后未显示在预览区域

**原因**：
- 文件格式不支持
- 文件大小超过 5MB
- 文件路径包含特殊字符或中文

**解决方案**：

1. **检查文件格式**
   - 支持：JPG, PNG, GIF, WebP
   - 不支持：BMP, TIFF, SVG

2. **压缩图片到 5MB 以下**：
   ```bash
   # Windows - 使用 Paint
   1. 右键图片 → 编辑
   2. 文件 → 另存为 → JPEG
   3. 保存时选择较低质量

   # 命令行（如果安装了 ImageMagick）
   magick convert input.jpg -quality 85 -resize 2048x2048> output.jpg
   ```

3. **路径问题**
   - 使用绝对路径：`C:\\Users\\<YOUR_USER>\Pictures\photo.jpg`
   - 避免中文路径，或复制文件到英文路径
   - 避免特殊字符（如 `@`, `#`, `%`）

---

### 2. 推文按钮禁用

**症状**：点击发布时提示 "发布按钮被禁用"

**原因**：
- 文本和图片都为空
- 图片还在上传中
- 文本超过 280 字符且账号不是 X Premium
- 网络问题导致页面状态异常

**解决方案**：

1. **确保有内容**
   - 至少有文本或图片之一
   - 检查文本是否真的填入了（查看浏览器预览）

2. **等待上传完成**
   - 每张图片上传后会等待 3 秒
   - 如果网络慢，可能需要更长时间
   - 检查浏览器中是否显示"正在上传"

3. **检查账号类型**
   - 如果文本超过 280 字符，账号必须是 X Premium
   - 登录 https://x.com 查看账号类型
   - 普通账号请将文本截短到 280 字符

4. **刷新重试**
   - 如果页面状态异常，刷新页面重试
   - 或关闭浏览器重新开始

---

### 3. Cookie 过期

**症状**：登录验证失败，提示"未登录"

**解决方案**：

1. **获取新 Cookie**
   ```
   1. 在浏览器中访问 https://x.com 并登录
   2. F12 打开开发者工具
   3. Application → Cookies → https://x.com
   4. 找到以下 Cookie 并复制值：
      - auth_token（必需）
      - ct0（推荐）
      - twid（可选）
   ```

2. **更新 cookies.json**
   ```json
   {
     "cookies": [
       {
         "name": "auth_token",
         "value": "你复制的 auth_token 值",
         "domain": ".x.com",
         "path": "/",
         "expires": -1,
         "httpOnly": true,
         "secure": true,
         "sameSite": "None"
       },
       {
         "name": "ct0",
         "value": "你复制的 ct0 值",
         "domain": ".x.com",
         "path": "/",
         "httpOnly": true,
         "secure": true,
         "sameSite": "Lax"
       }
     ]
   }
   ```

3. **重新运行 skill**

---

### 4. 文本编码问题

**症状**：特殊字符显示异常或乱码

**解决方案**：

1. **确保文本使用 UTF-8 编码**
   - 如果从文件读取，确保文件是 UTF-8 编码
   - 避免使用 GBK 或其他编码

2. **避免特殊 Unicode 字符**
   - Emoji 是支持的：✅ ❤️ 🎉
   - 避免使用罕见的 Unicode 字符
   - 避免使用零宽字符（zero-width characters）

---

### 5. 长推文被拒绝

**症状**：文本超过 280 字符，发布按钮禁用或显示错误

**原因**：账号不是 X Premium

**解决方案**：

1. **方案 A：截短文本**
   ```
   将文本截短到 280 字符以内
   注意：URL 算 23 字符
   ```

2. **方案 B：升级到 X Premium**
   ```
   - 访问 https://x.com/i/premium_sign_up
   - X Premium 支持最多 25,000 字符的长推文
   ```

3. **方案 C：使用 x-article-publisher**
   ```
   将内容发布为 X Article（长文章）而不是推文
   适合超长内容（超过 25,000 字符）
   ```

---

### 6. 图片顺序错误

**症状**：图片显示顺序与提供的顺序不一致

**原因**：网络延迟导致上传顺序打乱

**解决方案**：

1. **当前实现**：按顺序上传，每张等待 3 秒
2. **如果仍有问题**：手动调整 IMAGE_PATHS 的顺序
3. **或**：上传后手动在浏览器中拖动调整顺序

---

### 7. 多张图片上传失败

**症状**：第一张图片成功，后续图片失败

**原因**：
- 文件选择器被覆盖
- 网络超时
- X 平台限制

**解决方案**：

1. **检查图片总大小**
   - 4 张图片总大小不建议超过 15MB
   - 如果超过，压缩图片

2. **分批上传**
   - 先上传 2 张，发布后再发布另外 2 张
   - 或使用推文串（Thread）

3. **检查网络连接**
   - 确保网络稳定
   - 避免在网络高峰期上传

---

### 8. Playwright MCP 连接问题

**症状**：提示 "Playwright MCP 不可用"

**解决方案**：

1. **重新连接 MCP**
   ```
   /mcp
   选择 playwright → Restart
   ```

2. **检查 MCP 配置**
   ```
   确保 ~/.claude/mcp_servers.json 中有 playwright 配置
   ```

3. **清理残留进程**
   ```bash
   # Windows
   taskkill /F /IM chrome.exe /T

   # macOS/Linux
   pkill -f "Chrome.*--remote-debugging"
   ```

---

## 调试技巧

### 1. 启用详细日志

在执行时查看浏览器控制台：
```
browser_snapshot 会显示当前页面状态
可以看到是否有错误提示
```

### 2. 手动验证步骤

如果自动化失败，手动测试：
```
1. 访问 https://x.com/compose/post
2. 手动填入文本
3. 手动选择图片
4. 查看是否有错误提示
```

### 3. 检查 X 平台状态

访问 https://status.x.com 查看 X 是否正常运行

---

## 获取帮助

如果问题仍未解决：

1. **查看 x-article-publisher 的 troubleshooting.md**
   - 许多问题（如 Cookie、浏览器连接）是通用的

2. **检查错误消息**
   - 仔细阅读错误提示
   - 在浏览器中查看是否有 X 平台的错误提示

3. **重新开始**
   - 关闭所有浏览器
   - 重新运行 skill
   - 从最简单的测试开始（只有文本，无图片）


