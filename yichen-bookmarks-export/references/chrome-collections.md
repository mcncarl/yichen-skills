# Chrome 收藏页抓取细则

## 通用要求

1. 先读取 `chrome:control-chrome` Skill，并复用现有 `globalThis.chrome` 绑定。
2. 从页面快照确认 URL、账号身份和选中标签。不要仅凭查询参数推断当前标签已加载。
3. 所有滚动使用 `tab.cua.scroll()`；DOM 读取使用 `tab.playwright.evaluate()`。
4. 使用页面实际视口计算滚动坐标，避免固定坐标越界。
5. 采集器先用 `tab.cua.scroll()` 回到列表顶部，再开始累计；连续 4 次到达底部且内容数、滚动高度都不再增长，才标记 `completed`。

## 小红书

从用户个人主页开始，点击一级标签“收藏”，确认：

- URL 包含 `tab=fav&subTab=note`；
- 一级“收藏”元素具有 active 状态；
- 二级“笔记・N”具有 active 状态。

只接受下列笔记 URL 结构：

```text
/user/profile/<24位账号ID>/<24位笔记ID>
/explore/<24位笔记ID>
/discovery/item/<24位笔记ID>
```

不要用“所有 24 位路径 ID”计数，因为作者主页链接也是 24 位 ID。收藏页采用横向标签容器时，应选取与视口相交面积最大的 `tab-content-item`，避免把被平移到屏幕外的“笔记/点赞”面板混入。

调用示例。先解析当前 Skill 的实际安装目录为绝对路径 `<SKILL_DIR>`：

```js
var collectors = await import("<SKILL_DIR>/scripts/chrome_collectors.mjs");
var xhs = await collectors.collectXiaohongshuBookmarks(tab, {
  stableBottomRounds: 4,
  maxIterations: 80,
});
```

结果中的 `labelCount` 是页面标签数字，`count` 是滚动累计的当前可访问笔记数，两者必须分别报告。

## 抖音

打开：

```text
https://www.douyin.com/user/self?showTab=favorite_collection
```

确认外层“收藏”和内层“视频”均处于 selected 状态。滚动目标是 `div.route-scroll-container`，不是 `window`。只接受：

```text
/video/<数字ID>
/note/<数字ID>
```

调用示例：

```js
var collectors = await import("<SKILL_DIR>/scripts/chrome_collectors.mjs");
var douyin = await collectors.collectDouyinFavorites(tab, {
  stableBottomRounds: 4,
  maxIterations: 120,
});
```

分别报告 `typeCounts.video` 与 `typeCounts.note`。平台页面可能随时间返回不同数量，以当次滚动到底的结果为准。

## 收尾

抽样验证后调用 `chrome.tabs.finalize({})`，并确保它是本轮最后一个 Chrome 动作。只关闭或释放本轮创建/认领的标签，不操作用户无关页面。
