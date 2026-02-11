# x-quote-tweet 故障排除

## 常见问题

### 1. 推文不可访问

**症状**：导航后显示"这条推文不可用"或"This Tweet is unavailable"

**原因**：
- 推文已被删除
- 推文来自私密账号（需要关注才能查看）
- 发推账号已被暂停
- 推文 URL 错误

**解决方案**：

1. **验证 URL 格式**
   ```
   ✅ 正确：https://x.com/username/status/1234567890
   ✅ 正确：https://twitter.com/username/status/1234567890
   ❌ 错误：x.com/username/status/1234567890 (缺少 https://)
   ❌ 错误：https://x.com/username (缺少 status ID)
   ```

2. **手动验证推文存在**
   - 在浏览器中访问推文 URL
   - 确认推文公开可见
   - 检查推文是否被删除

3. **处理私密账号**
   - 如果推文来自私密账号
   - 先关注该账号
   - 等待对方通过关注请求

4. **复制正确的 URL**
   - 从浏览器地址栏复制完整 URL
   - 不要从分享菜单复制（可能包含跟踪参数）
   - 确保包含 `/status/` 和状态 ID

---

### 2. 转推菜单未出现

**症状**：点击转推按钮后，菜单未弹出或消失

**原因**：
- 页面加载不完整
- 网络延迟导致元素未加载
- 推文不支持转推（如社区笔记）
- 浏览器状态异常

**解决方案**：

1. **增加等待时间**
   - 在 skill.md 中将 `browser_wait_for: time=1` 改为 `time=2`
   - 等待页面完全加载

2. **刷新页面重试**
   - 关闭浏览器
   - 重新运行 skill
   - 等待推文完全加载后再操作

3. **检查推文类型**
   - 某些推文不支持转推（如草稿）
   - 确保推文已正式发布
   - 避免引用已删除的推文

4. **手动测试**
   - 手动访问推文
   - 手动点击转推按钮
   - 查看菜单是否正常显示

---

### 3. 引用选项未找到

**症状**：转推菜单打开，但无法点击"引用"选项

**原因**：
- 菜单项索引变化
- X 平台更新了菜单结构
- 菜单项被隐藏或禁用

**解决方案**：

1. **检查菜单项数量**
   ```javascript
   // 在 browser_run_code 中添加调试
   const menuItems = await page.locator('[data-testid="Dropdown"] [role="menuitem"]').all();
   console.log('Menu items count:', menuItems.length);

   for (let i = 0; i < menuItems.length; i++) {
     const text = await menuItems[i].textContent();
     console.log(`Item ${i}: ${text}`);
   }
   ```

2. **使用文本定位**
   ```javascript
   // 如果索引变化，改用文本匹配
   const quoteItem = await page.locator('[data-testid="Dropdown"] [role="menuitem"]')
     .filter({ hasText: /引用|Quote/ })
     .first();
   await quoteItem.click();
   ```

3. **手动验证菜单结构**
   - F12 打开开发者工具
   - 点击转推按钮
   - 检查菜单 DOM 结构
   - 确认"引用"选项的位置

---

### 4. 评论未填入

**症状**：评论文本框保持为空，或只填入部分内容

**原因**：
- 文本框未正确聚焦
- 文本框加载延迟
- 特殊字符编码问题
- 文本过长导致截断

**解决方案**：

1. **确保文本框聚焦**
   ```javascript
   const textBox = await page.locator('[data-testid="tweetTextarea_0"]').first();
   await textBox.waitFor({ state: 'visible', timeout: 5000 });
   await textBox.click();  // 必须先点击聚焦
   await page.waitForTimeout(500);  // 等待聚焦生效
   await textBox.fill(commentText);
   ```

2. **检查特殊字符**
   - 避免使用零宽字符
   - 确保文本是 UTF-8 编码
   - 测试简单的纯文本评论

3. **验证填入结果**
   ```javascript
   // 填入后验证
   const textBox = await page.locator('[data-testid="tweetTextarea_0"]').first();
   await textBox.fill(commentText);

   // 检查实际内容
   const actualText = await textBox.inputValue();
   console.log('Filled text length:', actualText.length);
   console.log('Expected length:', commentText.length);
   ```

4. **逐步填入**
   - 如果 fill() 失败，尝试使用 type()
   ```javascript
   await textBox.click();
   await textBox.type(commentText, { delay: 10 });
   ```

---

### 5. 发布按钮被禁用

**症状**：预览正常，但点击发布时提示"发布按钮被禁用"

**原因**：
- 评论超过 280 字符且账号不是 X Premium
- 评论为空且 X 要求必须有内容
- 原推文被删除或不可用
- 网络问题导致状态异常

**解决方案**：

1. **检查评论长度**
   - 如果超过 280 字符，确认账号是否为 X Premium
   - 非 Premium 用户：将评论截短到 280 字符
   - Premium 用户：检查是否有其他错误

2. **检查评论内容**
   - X 可能要求引用推文必须有评论（某些情况下）
   - 尝试添加简短评论
   - 避免评论为空

3. **验证原推文状态**
   - 刷新页面检查原推文是否仍存在
   - 确认原推文未被删除
   - 确认原推文账号未被暂停

4. **手动测试发布**
   - 使用 browser_snapshot 查看页面状态
   - 手动点击发布按钮
   - 查看浏览器控制台是否有错误

---

### 6. 长评论被拒绝

**症状**：评论超过 280 字符，发布按钮禁用或显示错误

**原因**：账号不是 X Premium

**解决方案**：

1. **方案 A：截短评论**
   ```
   将评论截短到 280 字符以内
   注意：URL 算 23 字符
   ```

2. **方案 B：升级到 X Premium**
   ```
   - 访问 https://x.com/i/premium_sign_up
   - X Premium 支持最多 25,000 字符的长评论
   ```

3. **方案 C：分成多条推文**
   ```
   - 先发布引用推文（简短评论）
   - 然后在评论区补充详细内容
   - 或使用推文串（Thread）
   ```

---

### 7. URL 格式错误

**症状**：提示"URL 格式不正确"或无法导航

**原因**：
- 缺少 https:// 前缀
- 使用了错误的 URL 路径
- URL 包含无效字符

**解决方案**：

1. **使用正确的 URL 格式**
   ```
   ✅ https://x.com/username/status/1234567890
   ✅ https://twitter.com/username/status/1234567890
   ✅ https://x.com/username/status/1234567890?s=20

   ❌ x.com/username/status/1234567890
   ❌ https://x.com/username
   ❌ https://x.com/i/web/status/1234567890
   ```

2. **从浏览器复制 URL**
   - 访问推文
   - 从地址栏复制完整 URL
   - 确保包含 `/status/` 和状态 ID

3. **移除多余参数**
   - Skill 会自动移除 `?s=20` 等参数
   - 但确保核心 URL 正确

---

### 8. Cookie 过期

**症状**：登录验证失败，提示"未登录"

**解决方案**：参考 x-post-with-images 的 troubleshooting.md 更新 Cookie

---

### 9. 网络超时

**症状**：操作过程中提示"超时"或"timeout"

**原因**：
- 网络速度慢
- X 服务器响应慢
- 推文加载时间长

**解决方案**：

1. **增加超时时间**
   - 在 skill.md 中调整 timeout 参数
   - 例如：`await element.waitFor({ timeout: 10000 })`

2. **检查网络连接**
   ```bash
   # Windows
   ping x.com

   # 检查网络速度
   ```

3. **稍后重试**
   - X 服务器可能暂时负载高
   - 等待几分钟后重试

---

### 10. 推文发布成功但未显示

**症状**：提示发布成功，但在个人主页未找到

**原因**：
- X 平台延迟（1-2 分钟）
- 缓存未刷新
- 推文被过滤或限制

**解决方案**：

1. **等待同步**
   - X 平台可能需要 1-2 分钟同步
   - 刷新页面查看

2. **检查发布状态**
   - 访问 https://x.com/compose/post
   - 查看草稿是否还在
   - 检查已发送的推文列表

3. **手动验证**
   - 在个人主页查找推文
   - 使用搜索功能查找
   - 检查"推文和回复"标签

---

## 调试技巧

### 1. 启用详细日志

在 browser_run_code 中添加 console.log：
```javascript
browser_run_code: |
  async (page) => {
    console.log('Current URL:', page.url());
    console.log('Menu items:', await page.locator('[role="menuitem"]').count());
    // ...
  }
```

### 2. 使用 browser_snapshot

在关键步骤后使用 `browser_snapshot` 查看页面状态：
```
browser_click: ref=<retweet按钮>
browser_snapshot  # 查看菜单是否出现
```

### 3. 手动验证步骤

如果自动化失败，手动测试：
```
1. 访问推文 URL
2. 手动点击转推按钮
3. 手动选择"引用"
4. 手动填入评论
5. 查看是否有错误提示
```

### 4. 检查 DOM 结构

使用浏览器开发者工具：
```
F12 → Elements → 搜索 data-testid="retweet"
查看转推按钮和菜单的 DOM 结构
```

---

## 获取帮助

如果问题仍未解决：

1. **查看其他 skill 的 troubleshooting.md**
   - x-post-with-images（图片上传问题）
   - x-post-with-video（视频处理问题）
   - x-article-publisher（Cookie 和登录问题）

2. **检查 X 平台状态**
   - 访问 https://status.x.com
   - 检查推文功能是否正常

3. **测试简化场景**
   - 使用公开推文
   - 使用简短评论（<100 字符）
   - 排除复杂因素

4. **检查错误消息**
   - 仔细阅读错误提示
   - 在浏览器中查看 X 平台的错误提示
   - 使用 F12 查看控制台错误

---

## 常见错误代码

### ERR_NAME_NOT_RESOLVED
- 原因：DNS 解析失败
- 解决：检查网络连接，尝试访问其他网站

### ERR_CONNECTION_TIMED_OUT
- 原因：连接超时
- 解决：检查防火墙，尝试使用 VPN

### 403 Forbidden
- 原因：Cookie 无效或账号被限制
- 解决：更新 Cookie，检查账号状态

### 404 Not Found
- 原因：推文不存在
- 解决：检查 URL 是否正确

### 429 Too Many Requests
- 原因：请求过于频繁
- 解决：等待几分钟后重试

---

## 最佳实践

### 1. 验证推文 URL
- 发布前先手动访问推文
- 确认推文公开可见
- 复制完整的 URL

### 2. 测试评论长度
- 如果不确定账号类型，先使用短评论（<280 字符）
- 测试成功后再尝试长评论

### 3. 避免频繁操作
- 不要连续发布多条引用推文
- 间隔至少 30 秒
- 避免触发 X 的速率限制

### 4. 使用预览模式
- 默认使用预览模式（不带 --submit）
- 检查内容无误后再发布
- 避免发布错误内容

### 5. 定期更新 Cookie
- Cookie 通常有效期为 1-2 周
- 定期检查登录状态
- 及时更新过期的 Cookie

