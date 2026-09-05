# 访问与凭证边界

执行涉及登录态、凭证或第三方数据传递的路线时阅读本文件；平台命令细节见 routes.md。

- AI 新闻发现查询发给 AI HOT；普通网页、批量/垂直参数与默认候选核验 URL 发给 AnySearch。AI HOT 是聚合发现源，中文摘要可能由 AI 生成，事实必须核验原始 URL。
- 知乎查询经另行安装的 Open Platform CLI 兼容运行时 发给知乎，Access Secret 由该 CLI 保存在 macOS Keychain；本 Skill 不接收、读取、回显 Secret，不触碰私人收藏、关注列表或个人内容。
- 微博匿名查询发给 m.weibo.cn，临时匿名访客会话只驻留内存。适配器直连并忽略环境代理，每次匿名请求间隔 5–8 秒；只有登录/验证重定向、访问拒绝或非 JSON 等访问门失败后才自动回退一次 OpenCLI weibo search。网络错误不触发登录态回退。不取评论、个人主页或媒体。
- 小红书/抖音公开搜索及上述微博回退可复用现有 Chrome 会话。OpenCLI 自己管理登录态，Cookie 值不得进入命令、结果或日志。预先允许的只有有界只读搜索，不包含写操作、私域读取或验证码处理。
- X 查询先发给官方 Grok CLI 原生 x_search；只有明确额度耗尽才发给匿名 FxTwitter，其后浏览器登录态读取按工具提示取得当轮授权。各层失败规则见 routes.md，不把匿名许可扩展到登录态或私域。
- Firecrawl 只接收显式 Map 种子，或明确选择它核验的本轮有效 AnySearch candidate。Scrape 固定 formats=[markdown]、storeInCache=false、proxy=basic、skipTlsVerification=false；不传 actions、headers、cookies 或 zeroDataRetention。storeInCache=false 不等于绝对零数据保留或已启用 ZDR。
- YouTube 仅从现有环境变量 YT_BROWSE_API_KEY 或 YOUTUBE_API_KEY 读取 Key，不打印或写入 Skill。无 Key 时匿名 yt-dlp 列表，不要求普通搜索提供 Cookie，不下载媒体。
- AnySearch 匿名额度可直接使用；收到新 Key 时先询问，明确同意后才能保存，不让用户在聊天中粘贴 Key。现有 CLI 命令来自 `${YICHEN_SKILLS_ROOT}/anysearch/runtime.conf`，不复制 CLI 或改配置。
- AnySearch 回执使用本机专用 HMAC 密钥 `~/.config/agent-secrets/yichen-unified-search-receipt-key`，首次成功返回候选时以 0600 原子创建，不打印或传给 AnySearch。回执有效 2 小时，仅证明 URL 来自近期搜索，不能证明事实；不得伪造、移用或移除签名后继续核验。
- Firecrawl Key 仅来自现有 FIRECRAWL_API_KEY 或 `~/.config/agent-secrets/firecrawl-api-key`，不接受命令行 Key、不回显。缺失时明确失败，不自动替换后端。
