# x-post-with-video 故障排除

## 常见问题

### 1. 视频处理超时

**症状**：等待 180 秒后仍未完成处理，提示"视频处理超时"

**原因**：
- 视频文件过大
- 网络速度慢
- X 服务器负载高
- 视频编码格式复杂

**解决方案**：

1. **压缩视频文件**
   ```bash
   # 使用 FFmpeg 压缩到 1Mbps 比特率
   ffmpeg -i input.mp4 -vcodec h264 -acodec aac -b:v 1M output.mp4

   # 更激进的压缩（500kbps）
   ffmpeg -i input.mp4 -vcodec h264 -acodec aac -b:v 500k output.mp4
   ```

2. **降低分辨率**
   ```bash
   # 降低到 720p
   ffmpeg -i input.mp4 -vf scale=1280:720 -b:v 1M output.mp4

   # 降低到 480p（更小）
   ffmpeg -i input.mp4 -vf scale=854:480 -b:v 500k output.mp4
   ```

3. **检查网络连接**
   - 确保网络稳定
   - 避免在网络高峰期上传
   - 尝试使用有线连接而不是 Wi-Fi

4. **稍后重试**
   - X 服务器可能暂时负载高
   - 等待几分钟后重试

---

### 2. 视频格式不支持

**症状**：上传后提示"无法上传此文件"或"格式不支持"

**原因**：
- 视频编码格式不支持
- 容器格式不是 MP4/MOV/WebM
- 音频编码格式不支持

**解决方案**：

1. **转换为 X 支持的格式**
   ```bash
   # 转换为 MP4 (H.264 + AAC)
   ffmpeg -i input.avi -vcodec h264 -acodec aac output.mp4

   # 确保兼容性（使用保守的编码参数）
   ffmpeg -i input.mkv -vcodec h264 -acodec aac -profile:v baseline -level 3.0 output.mp4
   ```

2. **检查视频信息**
   ```bash
   ffmpeg -i video.mp4
   # 查看输出中的 Video 和 Audio 行
   # 确保是 h264 (或 H.264) 和 aac
   ```

3. **使用在线转换工具**
   - https://www.freeconvert.com/video-converter
   - 选择 MP4 格式，H.264 编码

---

### 3. 视频时长超限

**症状**：上传后提示"视频太长"

**原因**：
- 普通用户：视频超过 140 秒（2分20秒）
- X Premium 用户：视频超过 60 分钟

**解决方案**：

1. **截取前 140 秒（普通用户）**
   ```bash
   ffmpeg -i input.mp4 -t 140 -c copy output.mp4
   ```

2. **截取指定时间段**
   ```bash
   # 从第 10 秒开始，截取 140 秒
   ffmpeg -i input.mp4 -ss 10 -t 140 -c copy output.mp4
   ```

3. **加速播放（使视频变短）**
   ```bash
   # 2倍速（视频时长减半）
   ffmpeg -i input.mp4 -filter:v "setpts=0.5*PTS" -an output.mp4
   ```

4. **升级到 X Premium**
   - 访问 https://x.com/i/premium_sign_up
   - X Premium 支持最长 60 分钟的视频

---

### 4. 文件大小超限

**症状**：上传后提示"文件太大"

**原因**：视频文件超过 512MB

**解决方案**：

1. **降低比特率**
   ```bash
   # 降低到 1Mbps
   ffmpeg -i input.mp4 -b:v 1M output.mp4

   # 降低到 500kbps（更小）
   ffmpeg -i input.mp4 -b:v 500k output.mp4
   ```

2. **降低分辨率和比特率**
   ```bash
   # 720p + 1Mbps
   ffmpeg -i input.mp4 -vf scale=1280:720 -b:v 1M output.mp4
   ```

3. **使用两遍编码（质量更好）**
   ```bash
   # 第一遍
   ffmpeg -i input.mp4 -c:v libx264 -b:v 1M -pass 1 -f null /dev/null

   # 第二遍
   ffmpeg -i input.mp4 -c:v libx264 -b:v 1M -pass 2 output.mp4
   ```

---

### 5. 视频处理失败但无错误提示

**症状**：
- 视频上传后一直显示"正在上传媒体"
- 发布按钮始终禁用
- 没有明确的错误提示

**原因**：
- X 平台静默处理失败
- 视频元数据损坏
- 编码参数不兼容

**解决方案**：

1. **重新编码视频**
   ```bash
   # 使用保守的编码参数确保兼容性
   ffmpeg -i input.mp4 \
     -vcodec h264 -profile:v baseline -level 3.0 \
     -acodec aac -ar 44100 -ac 2 \
     -movflags +faststart \
     output.mp4
   ```

2. **修复视频元数据**
   ```bash
   ffmpeg -i input.mp4 -c copy -map_metadata -1 output.mp4
   ```

3. **手动测试**
   - 手动访问 https://x.com/compose/post
   - 手动选择视频
   - 查看浏览器控制台是否有错误

---

### 6. 网络中断导致上传失败

**症状**：上传过程中提示"网络错误"或进度停滞

**解决方案**：

1. **检查网络稳定性**
   ```bash
   # Windows
   ping x.com -t

   # macOS/Linux
   ping x.com
   ```

2. **使用有线连接**
   - Wi-Fi 可能不稳定
   - 有线连接更可靠

3. **分段上传（手动）**
   - 如果视频很大，考虑分段发布
   - 或使用 X 的视频托管服务（如果可用）

---

### 7. Cookie 过期

**症状**：登录验证失败

**解决方案**：参考 x-post-with-images 的 troubleshooting.md 更新 Cookie

---

### 8. 长推文被拒绝

**症状**：文本超过 280 字符，发布按钮禁用

**解决方案**：参考 x-post-with-images 的 troubleshooting.md

---

## 视频优化最佳实践

### 推荐的视频规格

```
格式：MP4
视频编码：H.264
音频编码：AAC
分辨率：1280x720 (720p) 或 1920x1080 (1080p)
帧率：30 FPS
比特率：2-5 Mbps
最大文件大小：100MB（推荐）
最长时长：120 秒（普通用户推荐）
```

### FFmpeg 完整优化命令

```bash
ffmpeg -i input.mp4 \
  -vf "scale=1280:720" \
  -c:v libx264 -preset slow -crf 23 \
  -c:a aac -b:a 128k -ar 44100 \
  -movflags +faststart \
  -r 30 \
  output.mp4
```

**参数说明**：
- `-vf "scale=1280:720"`: 缩放到 720p
- `-preset slow`: 较慢的编码速度，但质量更好
- `-crf 23`: 恒定质量模式（18-28，值越小质量越好）
- `-b:a 128k`: 音频比特率 128kbps
- `-movflags +faststart`: 优化流媒体播放
- `-r 30`: 帧率 30 FPS

---

## 检查视频是否符合要求

### 使用 FFmpeg 检查视频信息

```bash
ffmpeg -i video.mp4
```

**查看输出**：
```
Video: h264 (High) (avc1 / 0x31637661), yuv420p, 1920x1080, 2500 kb/s, 30 fps
Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp, 128 kb/s
Duration: 00:01:45.00
```

**检查要点**：
- ✅ Video: h264
- ✅ Audio: aac
- ✅ 1920x1080 或 1280x720
- ✅ 30 fps
- ✅ 2500 kb/s（2.5 Mbps）
- ✅ Duration < 140 秒（普通用户）

### 计算文件大小

```bash
# 比特率 * 时长 / 8 = 文件大小

例如：
2.5 Mbps * 120 秒 / 8 = 37.5 MB
```

---

## 调试技巧

### 1. 启用详细日志

在浏览器控制台中查看网络请求：
```
F12 → Network → 筛选 "upload" 或 "media"
查看上传请求的状态
```

### 2. 手动验证

如果自动化失败：
```
1. 手动访问 https://x.com/compose/post
2. 手动选择视频
3. 观察上传过程
4. 查看是否有错误提示
```

### 3. 测试小视频

先测试一个小视频（< 10MB，< 30 秒）：
```
如果小视频成功，说明是文件大小或时长问题
如果小视频失败，说明是格式或网络问题
```

---

## 获取帮助

如果问题仍未解决：

1. **查看 X 平台状态**
   - 访问 https://status.x.com
   - 检查视频上传服务是否正常

2. **查看通用问题**
   - x-post-with-images 的 troubleshooting.md
   - x-article-publisher 的 troubleshooting.md

3. **检查视频文件**
   - 使用 FFmpeg 查看视频信息
   - 确认符合 X 的要求

4. **简化测试**
   - 使用最简单的视频（小文件、短时长、标准格式）
   - 排除复杂因素

