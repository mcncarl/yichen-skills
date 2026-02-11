---
name: x-quote-tweet
description: |
  Quote an existing tweet with your comment on X (Twitter). Supports unlimited comment length for X Premium users. Use when user wants to quote retweet, mentions "quote tweet", "引用推文", or wants to retweet with comment.
---

# X Quote Tweet

引用现有推文并添加评论，支持 X Premium 长评论。

## 参数

- `TWEET_URL`：要引用的推文 URL（必需）
  - 支持格式：
    - `https://x.com/username/status/1234567890`
    - `https://twitter.com/username/status/1234567890`
    - `https://x.com/username/status/1234567890?s=20` (带参数)
- `COMMENT_TEXT`：评论内容（可选，无字符限制）
  - X Premium 用户支持最多 25,000 字符
  - 普通用户限制 280 字符（由 X 平台强制执行）
  - 可以为空，表示只转发不评论

## 前置要求

- **Playwright MCP** 用于浏览器自动化（必需）
- Cookie 配置文件 `~/.claude/skills/x-publisher/cookies.json` 已配置
- 如需发布长评论（超过280字符），账号必须是 X Premium

## 执行流程（严格遵循）

### Phase 1: 验证输入参数

1.1 验证 TWEET_URL
```bash
检查 URL 格式是否正确
支持格式：
- https://x.com/user/status/123456
- https://twitter.com/user/status/123456

自动转换：twitter.com → x.com
```

1.2 验证 COMMENT_TEXT（可选）
```bash
如果提供了 COMMENT_TEXT：
  检查是否为空

注意：不限制字符长度
- X Premium 用户：最多 25,000 字符
- 普通用户：超过 280 字符会被 X 平台拒绝
```

1.3 记录执行参数
```
- 原推文 URL
- 评论文本字符数（如果有）
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

#### 2.3 导航到原推文页面

```javascript
browser_run_code: |
  async (page) => {
    let tweetUrl = '${TWEET_URL}';

    // 统一转换为 x.com
    tweetUrl = tweetUrl.replace('twitter.com', 'x.com');

    // 移除多余参数（保留核心 URL）
    tweetUrl = tweetUrl.split('?')[0];

    await page.goto(tweetUrl);

    return {
      navigated: true,
      url: tweetUrl
    };
  }

browser_wait_for: time=3
```

**输出提示**：`✅ 已导航到推文：${TWEET_URL}`

#### 2.4 验证推文存在且可访问

```javascript
browser_run_code: |
  async (page) => {
    // 检查推文是否存在
    const tweetExists = await page.locator('[data-testid="tweet"]').count() > 0;

    if (!tweetExists) {
      // 检查是否有错误提示
      const notFound = await page.getByText(/这条推文不可用|This Tweet is unavailable/).count() > 0;
      const suspended = await page.getByText(/账号已被暂停|Account suspended/).count() > 0;
      const protected = await page.getByText(/这些推文受到保护|These Tweets are protected/).count() > 0;

      return {
        tweetExists: false,
        notFound,
        suspended,
        protected
      };
    }

    // 检查转推按钮是否可用
    const retweetButton = await page.locator('[data-testid="retweet"]').count() > 0;

    return {
      tweetExists: true,
      retweetButton
    };
  }
```

**如果 tweetExists=false**，停止并输出：
```
❌ 无法访问该推文

可能原因：
${如果 notFound}
- 推文已被删除
- 推文 ID 错误
${结束}

${如果 suspended}
- 发推账号已被暂停
${结束}

${如果 protected}
- 推文来自私密账号，需要先关注该账号
${结束}

请检查推文 URL 是否正确
```

**输出提示**：`✅ 推文验证成功`

#### 2.5 打开转推菜单

```javascript
browser_run_code: |
  async (page) => {
    const retweetButton = await page.locator('[data-testid="retweet"]').first();
    await retweetButton.click();

    return { clicked: true };
  }

browser_wait_for: time=1
```

**输出提示**：`✅ 已打开转推菜单`

#### 2.6 点击"引用"选项

X 的转推菜单有两个选项：
1. 转推（Retweet）
2. 引用（Quote Tweet）

我们需要点击第二个选项。

```javascript
browser_run_code: |
  async (page) => {
    // 等待菜单出现
    await page.locator('[data-testid="Dropdown"]').waitFor({ state: 'visible', timeout: 5000 });

    // 方法1: 优先使用文本匹配（更稳定）
    const quoteByText = await page.locator('[data-testid="Dropdown"] [role="menuitem"]')
      .filter({ hasText: /引用|Quote/ })
      .first();

    if (await quoteByText.count() > 0) {
      await quoteByText.click();
      return {
        clicked: true,
        method: 'text-match',
        message: '使用文本匹配找到引用选项'
      };
    }

    // 方法2: 回退到索引方式（兼容性）
    const menuItems = await page.locator('[data-testid="Dropdown"] [role="menuitem"]').all();

    if (menuItems.length < 2) {
      return {
        error: '转推菜单项不足',
        itemCount: menuItems.length
      };
    }

    // 点击第2个菜单项（"引用"通常是第2个）
    await menuItems[1].click();

    return {
      clicked: true,
      method: 'index-fallback',
      menuItemCount: menuItems.length,
      message: '使用索引方式选择引用选项'
    };
  }

browser_wait_for: time=2
```

**输出提示**：`✅ 已选择引用推文`

#### 2.7 输入评论内容

```javascript
browser_run_code: |
  async (page) => {
    // 等待编辑器出现
    const textBox = await page.locator('[data-testid="tweetTextarea_0"]').first();
    await textBox.waitFor({ state: 'visible', timeout: 5000 });

    // 如果提供了评论，填入
    const commentText = '${COMMENT_TEXT}';
    if (commentText) {
      await textBox.click();
      await textBox.fill(commentText);

      return {
        commentAdded: true,
        textLength: commentText.length
      };
    }

    // 没有评论，保持为空
    return {
      commentAdded: false,
      textLength: 0
    };
  }
```

**输出提示**：
```
${如果有评论}
✅ 已填入评论（${textLength} 字符）
${否则}
✅ 无评论内容（仅转发）
${结束}
```

#### 2.8 预览模式（默认模式）

```javascript
browser_snapshot  # 让用户检查引用推文内容
```

**输出预览提示**：
```
✅ 引用推文已准备完成，请检查预览内容

引用详情：
- 原推文：${TWEET_URL}
- 评论：${COMMENT_TEXT_PREVIEW}（${TEXT_LENGTH} 字符）

${如果 TEXT_LENGTH > 280}
⚠️ 评论超过 280 字符（${TEXT_LENGTH} 字符）
  - 如果账号是 X Premium：可正常发布
  - 如果是普通账号：发布会被 X 平台拒绝
${结束}

如需发布，请重新运行并添加 --submit 参数
```

#### 2.9 发布推文（仅当提供 --submit 参数时）

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
        reason: '可能原因：评论超过限制（非 Premium 用户）或网络问题'
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
✅ 引用推文发布成功！

${如果有 tweetUrl}
推文链接：${tweetUrl}
推文 ID：${tweetId}
原推文：${ORIGINAL_TWEET_URL}
${否则}
推文已发布到首页，请在 https://x.com/home 查看
${结束}
```

**如果发布失败**：
```
❌ 推文发布失败
原因：${ERROR_REASON}

常见问题：
1. 评论超过280字符且账号不是 X Premium
2. 原推文不可用或已删除
3. 网络问题
4. X 平台临时限制

请检查浏览器中的错误提示
```

---

### Phase 3: 生成执行报告

```markdown
## 引用推文执行报告

### 推文详情
- **原推文 URL**：${TWEET_URL}
- **评论内容**：${COMMENT_TEXT_PREVIEW}
- **字符数**：${CHARACTER_COUNT}

### 完成项
- ✅ Cookie 验证：已加载 ${COOKIE_COUNT} 个 Cookie
- ✅ 登录状态：已验证
- ✅ 推文验证：原推文存在且可访问
- ✅ 转推菜单：已打开
- ✅ 引用选项：已选择
${如果有评论}
- ✅ 评论内容：已填入（${CHARACTER_COUNT} 字符）
${否则}
- ✅ 评论内容：无（仅转发）
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
⚠️ 评论文本超过 280 字符
- 当前字符数：${CHARACTER_COUNT}
- 如果账号是 X Premium：可正常发布（最多支持 25,000 字符）
- 如果是普通账号：发布会被 X 平台拒绝
${结束}
```

---

## 关键规则

1. **Cookie 优先** - 必须先加载 Cookie 再访问 X
2. **URL 自动转换** - twitter.com 自动转换为 x.com
3. **推文验证** - 必须验证推文存在且可访问
4. **菜单定位** - 使用 [role="menuitem"] 选择器定位引用选项
5. **评论可选** - 支持无评论的纯转发
6. **默认预览** - 不使用 --submit 时仅预览不发布
7. **长评论支持** - 不限制文本长度，由 X 平台根据账号类型处理

## DOM 选择器参考

```javascript
// 推文内容
'[data-testid="tweet"]'

// 转推按钮
'[data-testid="retweet"]'

// 转推菜单
'[data-testid="Dropdown"]'

// 菜单项（引用是第2个）
'[data-testid="Dropdown"] [role="menuitem"]'

// 评论文本框
'[data-testid="tweetTextarea_0"]'

// 发布按钮
'[data-testid="tweetButton"]'

// 登录验证
'[data-testid="primaryColumn"]'
```

## 错误处理

### 推文不可访问

**症状**：导航后显示"这条推文不可用"

**原因**：
- 推文已被删除
- 推文来自私密账号
- 发推账号已被暂停
- 推文 ID 错误

**解决方案**：
1. 检查 URL 是否正确复制
2. 访问推文确认是否公开可见
3. 如果是私密账号，先关注该账号
4. 使用其他公开推文测试

### 转推菜单未出现

**症状**：点击转推按钮后菜单未出现

**原因**：
- 页面加载不完整
- 推文不支持转推（如私信）
- 网络延迟

**解决方案**：
1. 增加等待时间（browser_wait_for: time=2）
2. 刷新页面重试
3. 检查推文类型是否支持转推
4. 手动测试转推功能是否可用

### 评论未填入

**症状**：评论文本框为空

**原因**：
- 文本框未正确聚焦
- 文本框选择器变化
- 填入速度过快

**解决方案**：
1. 确保使用 textBox.click() 先聚焦
2. 增加 await textBox.waitFor() 等待
3. 使用 browser_snapshot 检查页面状态
4. 手动验证文本框是否可编辑

### Cookie 过期

**症状**：登录验证失败

**解决方案**：参考 x-post-with-images 的 troubleshooting.md 更新 Cookie

### 长评论被拒绝

**症状**：评论超过 280 字符，发布按钮禁用或显示错误

**原因**：账号不是 X Premium

**解决方案**：
1. 将评论截短到 280 字符以内
2. 或升级账号到 X Premium
3. 或使用 x-article-publisher 发布为长文章后引用

---

## URL 格式支持

### 支持的格式

✅ `https://x.com/username/status/1234567890`
✅ `https://twitter.com/username/status/1234567890`
✅ `https://x.com/username/status/1234567890?s=20`
✅ `https://x.com/username/status/1234567890?t=abc`

### 不支持的格式

❌ `x.com/username/status/1234567890` (缺少 https://)
❌ `https://x.com/username` (缺少 status ID)
❌ `https://x.com/i/web/status/1234567890` (错误路径)

### 自动处理

- `twitter.com` → 自动转换为 `x.com`
- URL 参数（?s=20, ?t=abc）→ 自动移除

---

## 常见使用场景

### 场景 1：引用并添加评论
```
TWEET_URL: https://x.com/elonmusk/status/1234567890
COMMENT_TEXT: 很有趣的观点，我认为...
```

### 场景 2：纯转发（无评论）
```
TWEET_URL: https://x.com/elonmusk/status/1234567890
COMMENT_TEXT: (空)
```

### 场景 3：长评论（X Premium）
```
TWEET_URL: https://x.com/elonmusk/status/1234567890
COMMENT_TEXT: (超过 280 字符的详细评论)
```

### 场景 4：引用自己的推文
```
TWEET_URL: https://x.com/myusername/status/1234567890
COMMENT_TEXT: 补充一下刚才的观点...
```

