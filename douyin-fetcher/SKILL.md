---
name: douyin-fetcher
description: |
  抖音视频下载工具。使用 Playwright 拦截 Network 响应提取无水印直链并下载。
  触发词：「下载抖音视频」「抓取抖音」「douyin」「帮我下载这个抖音」
---

# Douyin Fetcher

抖音视频下载 skill，使用 Playwright 控制浏览器拦截 API 响应，绕过抖音的 msToken/X-Bogus 签名验证，获取无水印视频直链并下载。

## 核心方法

1. 启动无头 Chromium（Playwright）
2. 访问抖音视频页面
3. 拦截 `aweme/detail` API 响应
4. 从 JSON 响应中提取 `play_addr.url_list[0]`（无水印直链）
5. 用 requests 下载，带 Referer 模拟浏览器来源

## 使用方式

### 下载单个视频

用户提供抖音链接（支持以下格式）：
- `https://www.douyin.com/video/7611845735025364265`
- `https://www.douyin.com/jingxuan?modal_id=7611845735025364265`
- 任意 douyin.com 下的视频 URL

### 执行脚本

运行下载脚本：
```bash
python3 douyin-fetcher/scripts/download.py "<抖音链接>" [输出路径]
```

**参数说明：**
- 抖音链接（必需）：视频页面 URL
- 输出路径（可选）：本地保存路径，默认为 `~/Downloads/douyin_<video_id>.mp4`
- `--metadata-only`（可选）：只抓取元数据，不下载视频，用于快速检查链接是否能解析
- `--timeout 60`（可选）：等待 `aweme/detail` 响应的秒数

**示例：**
```bash
python3 douyin-fetcher/scripts/download.py "https://www.douyin.com/video/7611845735025364265"
python3 douyin-fetcher/scripts/download.py "https://www.douyin.com/video/7611845735025364265" "/tmp/my_video.mp4"
python3 douyin-fetcher/scripts/download.py "https://www.douyin.com/video/7611845735025364265" --metadata-only
```

## 输出信息

下载成功后返回：
- 视频标题（desc）
- 视频大小（MB）
- 保存路径
- 作者信息
- 同目录生成 `<视频文件名>.metadata.json`，包含标题、作者、发布时间、时长、互动数据等精简元数据

## 依赖

- Python 3.9+
- playwright (`pip install playwright`；Chromium 首次缺失时脚本会自动执行 `python3 -m playwright install chromium`)
- requests

## 注意事项

- 视频链接必须包含有效的 video_id
- 推荐页面链接需要转换为视频详情页格式（`/video/` 前缀）
- 下载的视频为无水印 MP4 格式
- 部分视频可能因版权或地区限制无法下载
- 这个 skill 只负责抓视频和元数据；需要口播稿时继续调用 `volc-asr` 做转写
