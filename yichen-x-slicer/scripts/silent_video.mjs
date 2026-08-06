import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

export const SILENT_VIDEO_PROFILE = Object.freeze({
  id: 'fixed-reading-v1',
  fps: 30,
  minimumTextFrames: 54,
  maximumTextFrames: 70,
  mediaFrames: 40,
  transitionFrames: 4,
  encoder: 'libx264',
  preset: 'slow',
  tune: 'stillimage',
  nativeVideoTune: 'film',
  crf: 10,
  minimumAdjacentReadingSsim: 0.9999,
  minimumEmbeddedFrameSsim: 0.98
});

function clamp(minimum, maximum, value) {
  return Math.max(minimum, Math.min(maximum, value));
}

function sha256File(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

function safeOutputPath(outputDirectory, relativePath) {
  const root = path.resolve(outputDirectory);
  const resolved = path.resolve(root, relativePath);
  if (resolved === root || !resolved.startsWith(root + path.sep)) throw new Error(`视频输出路径越界：${relativePath}`);
  return resolved;
}

function readPngDimensions(file) {
  const header = fs.readFileSync(file).subarray(0, 24);
  if (header.length < 24 || !header.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
    throw new Error(`视频输入不是有效 PNG：${path.basename(file)}`);
  }
  return { width: header.readUInt32BE(16), height: header.readUInt32BE(20) };
}

function runCommand(command, args, options = {}) {
  const result = spawnSync(command, args, {
    encoding: options.encoding ?? 'utf8',
    maxBuffer: 256 * 1024 * 1024
  });
  if (result.error) {
    if (result.error.code === 'ENOENT') throw new Error(`缺少本地命令：${command}`);
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`${command} 执行失败：${String(result.stderr ?? '').trim()}`);
  }
  return result.stdout;
}

function assertBinary(binary) {
  runCommand(binary, ['-version']);
}

export function assertSilentVideoRuntime({ ffmpeg = process.env.YICHEN_X_SLICER_FFMPEG || 'ffmpeg', ffprobe = process.env.YICHEN_X_SLICER_FFPROBE || 'ffprobe' } = {}) {
  assertBinary(ffmpeg);
  assertBinary(ffprobe);
  return { ffmpeg, ffprobe };
}

function finitePositive(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

function rationalNumber(value) {
  const match = String(value ?? '').match(/^(\d+)\/(\d+)$/u);
  if (!match || Number(match[2]) === 0) return null;
  return Number(match[1]) / Number(match[2]);
}

function normalizedMediaLayout(layout) {
  const normalized = {
    x: Math.round(Number(layout?.x)),
    y: Math.round(Number(layout?.y)),
    width: Math.round(Number(layout?.width)),
    height: Math.round(Number(layout?.height))
  };
  if (!Object.values(normalized).every(Number.isFinite)
    || normalized.x < 0
    || normalized.y < 0
    || normalized.width < 2
    || normalized.height < 2
    || normalized.x + normalized.width > 1080
    || normalized.y + normalized.height > 1440) {
    throw new Error('原生视频嵌入区域无效，拒绝退化为静态封面');
  }
  return normalized;
}

export function isNativeVideoOutput(output) {
  return output?.kind === 'media'
    && output?.media?.type === 'video'
    && typeof output?.media?.native_video?.relative_path === 'string'
    && output.media.native_video.relative_path.length > 0
    && Boolean(output?.media_layout);
}

export function probeNativeVideoSource({
  outputDirectory,
  relativePath,
  ffmpeg = process.env.YICHEN_X_SLICER_FFMPEG || 'ffmpeg',
  ffprobe = process.env.YICHEN_X_SLICER_FFPROBE || 'ffprobe'
}) {
  const sourcePath = safeOutputPath(outputDirectory, relativePath);
  const stat = fs.statSync(sourcePath);
  if (!stat.isFile() || stat.size <= 0) throw new Error(`原生视频文件为空：${relativePath}`);
  const rawProbe = runCommand(ffprobe, [
    '-v', 'error',
    '-show_entries', 'format=duration,size,format_name:stream=index,codec_name,codec_type,width,height,pix_fmt,r_frame_rate,avg_frame_rate,nb_frames,duration,duration_ts,time_base',
    '-of', 'json',
    sourcePath
  ]);
  const probe = JSON.parse(rawProbe);
  const videos = (probe.streams ?? []).filter((stream) => stream.codec_type === 'video');
  const audios = (probe.streams ?? []).filter((stream) => stream.codec_type === 'audio');
  if (videos.length !== 1) throw new Error(`原生视频流数量不是 1：${relativePath}`);
  const video = videos[0];
  const durationFromTimeBase = finitePositive(video.duration_ts) && rationalNumber(video.time_base)
    ? Number(video.duration_ts) * rationalNumber(video.time_base)
    : null;
  const durationSeconds = finitePositive(video.duration)
    ?? finitePositive(durationFromTimeBase)
    ?? finitePositive(probe.format?.duration);
  if (!durationSeconds) throw new Error(`无法探测原生视频视觉时长：${relativePath}`);
  if (!finitePositive(video.width) || !finitePositive(video.height) || !video.codec_name) {
    throw new Error(`原生视频流信息不完整：${relativePath}`);
  }
  runCommand(ffmpeg, [
    '-nostdin',
    '-hide_banner',
    '-v', 'error',
    '-i', sourcePath,
    '-map', '0:v:0',
    '-an',
    '-f', 'null', '-'
  ]);
  const embeddedFrames = Math.max(1, Math.ceil(durationSeconds * SILENT_VIDEO_PROFILE.fps));
  return {
    pass: true,
    relative_path: relativePath,
    sha256: sha256File(sourcePath),
    size_bytes: stat.size,
    format_name: probe.format?.format_name ?? null,
    video_stream_count: videos.length,
    audio_stream_count: audios.length,
    codec: video.codec_name,
    width: Number(video.width),
    height: Number(video.height),
    pixel_format: video.pix_fmt ?? null,
    source_fps: video.avg_frame_rate ?? video.r_frame_rate ?? null,
    source_frame_count: finitePositive(video.nb_frames),
    source_duration_seconds: durationSeconds,
    embedded_frames: embeddedFrames,
    embedded_duration_seconds: embeddedFrames / SILENT_VIDEO_PROFILE.fps,
    decode_pass: true
  };
}

function probeFromCollection(collection, relativePath) {
  if (collection instanceof Map) return collection.get(relativePath) ?? null;
  return collection?.[relativePath] ?? null;
}

export function videoFramesForOutput(output, sourceVideoProbe = null) {
  if (isNativeVideoOutput(output)) {
    const frames = finitePositive(sourceVideoProbe?.embedded_frames);
    if (!frames || sourceVideoProbe?.decode_pass !== true) {
      throw new Error('原生视频必须先通过 ffprobe 探测与 ffmpeg 完整解码');
    }
    return Math.ceil(frames);
  }
  if (output?.kind === 'media') return SILENT_VIDEO_PROFILE.mediaFrames;
  if (output?.kind !== 'text') throw new Error(`视频不支持的帧类型：${String(output?.kind ?? 'missing')}`);
  const calculated = Math.round(21 + 0.157 * String(output.text ?? '').length);
  return clamp(SILENT_VIDEO_PROFILE.minimumTextFrames, SILENT_VIDEO_PROFILE.maximumTextFrames, calculated);
}

export function buildVideoPlan(outputs, template, { nativeVideoProbes = null } = {}) {
  let nextInputIndex = 0;
  const slides = outputs
    .filter((output) => output.template_id === template.id)
    .sort((left, right) => left.order - right.order)
    .map((output) => {
      const nativeVideo = isNativeVideoOutput(output) ? {
        relative_path: output.media.native_video.relative_path,
        layout: normalizedMediaLayout(output.media_layout),
        probe: probeFromCollection(nativeVideoProbes, output.media.native_video.relative_path)
      } : null;
      const slide = {
        kind: output.kind,
        png_file: output.png_file,
        frames: videoFramesForOutput(output, nativeVideo?.probe ?? null),
        background_input_index: nextInputIndex,
        native_video: nativeVideo
      };
      nextInputIndex += 1;
      if (nativeVideo) {
        slide.native_video_input_index = nextInputIndex;
        nextInputIndex += 1;
      }
      return slide;
    });
  if (!slides.length) throw new Error(`模板 ${template.id} 没有可生成视频的图片`);
  let timelineStartFrame = 0;
  for (let index = 0; index < slides.length; index += 1) {
    slides[index].timeline_start_frame = timelineStartFrame;
    slides[index].timeline_end_frame_exclusive = timelineStartFrame + slides[index].frames;
    timelineStartFrame += slides[index].frames;
    if (index < slides.length - 1) timelineStartFrame -= SILENT_VIDEO_PROFILE.transitionFrames;
  }
  const transitionCount = Math.max(0, slides.length - 1);
  const totalFrames = timelineStartFrame;
  return {
    template_id: template.id,
    template_name: template.name,
    file: `video-${template.id}-silent.mp4`,
    filter_file: `video-${template.id}-silent-filter.txt`,
    slides,
    transition_count: transitionCount,
    transition_frames: SILENT_VIDEO_PROFILE.transitionFrames,
    input_count: nextInputIndex,
    native_video_count: slides.filter((slide) => slide.native_video).length,
    total_frames: totalFrames,
    duration_seconds: totalFrames / SILENT_VIDEO_PROFILE.fps
  };
}

function transitionOffsetsFrames(plan) {
  const offsets = [];
  let accumulatedFrames = 0;
  for (let index = 0; index < plan.slides.length - 1; index += 1) {
    accumulatedFrames += plan.slides[index].frames;
    offsets.push(accumulatedFrames - SILENT_VIDEO_PROFILE.transitionFrames * (index + 1));
  }
  return offsets;
}

export function readingStabilityPairIndices(plan) {
  const transitionPairs = new Set();
  for (const offsetFrames of transitionOffsetsFrames(plan)) {
    for (let delta = 1; delta <= SILENT_VIDEO_PROFILE.transitionFrames; delta += 1) {
      transitionPairs.add(offsetFrames + delta);
    }
  }
  const dynamicNativeVideoPairs = new Set();
  for (const slide of plan.slides) {
    if (!slide.native_video) continue;
    const firstPair = Math.max(1, slide.timeline_start_frame + 1);
    const lastPair = Math.min(plan.total_frames - 1, slide.timeline_end_frame_exclusive - 1);
    for (let pairIndex = firstPair; pairIndex <= lastPair; pairIndex += 1) {
      if (!transitionPairs.has(pairIndex)) dynamicNativeVideoPairs.add(pairIndex);
    }
  }
  const stablePairs = [];
  for (let pairIndex = 1; pairIndex < plan.total_frames; pairIndex += 1) {
    if (!transitionPairs.has(pairIndex) && !dynamicNativeVideoPairs.has(pairIndex)) stablePairs.push(pairIndex);
  }
  return {
    transition: [...transitionPairs].sort((left, right) => left - right),
    dynamic_native_video: [...dynamicNativeVideoPairs].sort((left, right) => left - right),
    stable: stablePairs
  };
}

export function buildReadingStabilityFilter(plan) {
  return [
    '[0:v]split=2[reading_left][reading_right]',
    `[reading_left]trim=end_frame=${plan.total_frames - 1},setpts=PTS-STARTPTS[reading_a]`,
    '[reading_right]trim=start_frame=1,setpts=PTS-STARTPTS[reading_b]',
    '[reading_a][reading_b]ssim=stats_file=-'
  ].join(';');
}

export function parseReadingSsimStats(rawStats, plan) {
  const pairs = [];
  for (const line of String(rawStats).split(/\r?\n/u)) {
    const match = line.match(/^n:(\d+)\s+.*\sAll:([0-9.]+)/u);
    if (match) pairs.push({ pair_index: Number(match[1]), all_ssim: Number(match[2]) });
  }
  const expectedPairCount = plan.total_frames - 1;
  if (pairs.length !== expectedPairCount) {
    throw new Error(`阅读静止验收帧对数量错误：${pairs.length}/${expectedPairCount}`);
  }
  const indices = readingStabilityPairIndices(plan);
  const stableSet = new Set(indices.stable);
  const stablePairs = pairs.filter((pair) => stableSet.has(pair.pair_index));
  if (stablePairs.length !== indices.stable.length) throw new Error('阅读静止验收缺少稳定区帧对');
  const worst = stablePairs.length
    ? stablePairs.reduce((current, pair) => pair.all_ssim < current.all_ssim ? pair : current)
    : null;
  const threshold = SILENT_VIDEO_PROFILE.minimumAdjacentReadingSsim;
  if (worst && (!Number.isFinite(worst.all_ssim) || worst.all_ssim < threshold)) {
    throw new Error(`阅读区出现画面变化：帧对 ${worst.pair_index} 的 SSIM ${worst.all_ssim} 低于 ${threshold}`);
  }
  return {
    pass: true,
    checked_scope: 'static_slides_only',
    measured_pair_count: pairs.length,
    stable_pair_count: stablePairs.length,
    transition_pair_count: indices.transition.length,
    dynamic_native_video_pair_count: indices.dynamic_native_video.length,
    minimum_adjacent_reading_ssim: worst?.all_ssim ?? null,
    required_minimum_ssim: threshold,
    worst_pair_index: worst?.pair_index ?? null
  };
}

export function buildVideoFilter(plan) {
  const lines = [];
  for (let index = 0; index < plan.slides.length; index += 1) {
    const slide = plan.slides[index];
    const outputLabel = plan.slides.length === 1 ? '[vout]' : `[v${index}]`;
    const backgroundLabel = slide.native_video ? `[bg${index}]` : outputLabel;
    lines.push(
      `[${slide.background_input_index}:v]fps=${SILENT_VIDEO_PROFILE.fps},`
      + `trim=end_frame=${slide.frames},`
      + `settb=expr=1/${SILENT_VIDEO_PROFILE.fps},`
      + 'setpts=N,'
      + 'setsar=1,'
      + `format=yuv420p${backgroundLabel}`
    );
    if (!slide.native_video) continue;
    const { layout } = slide.native_video;
    lines.push(
      `[${slide.native_video_input_index}:v]fps=${SILENT_VIDEO_PROFILE.fps},`
      + 'tpad=stop_mode=clone:stop_duration=1,'
      + `trim=end_frame=${slide.frames},`
      + `settb=expr=1/${SILENT_VIDEO_PROFILE.fps},`
      + 'setpts=N,'
      + 'setsar=1,'
      + `scale=w=${layout.width}:h=${layout.height}:force_original_aspect_ratio=decrease:force_divisible_by=2,`
      + `format=yuv420p[native${index}]`
    );
    lines.push(
      `${backgroundLabel}[native${index}]`
      + `overlay=x=${layout.x}+(${layout.width}-overlay_w)/2:y=${layout.y}+(${layout.height}-overlay_h)/2:`
      + `shortest=1:eof_action=repeat:eval=init,setsar=1,format=yuv420p${outputLabel}`
    );
  }
  if (plan.slides.length > 1) {
    const offsets = transitionOffsetsFrames(plan);
    for (let index = 0; index < plan.slides.length - 1; index += 1) {
      const offsetFrames = offsets[index];
      const left = index === 0 ? '[v0]' : `[x${index}]`;
      const right = `[v${index + 1}]`;
      const output = index === plan.slides.length - 2 ? '[vout]' : `[x${index + 1}]`;
      const transition = index % 2 === 0 ? 'wipeleft' : 'fade';
      lines.push(`${left}${right}xfade=transition=${transition}:duration=${(SILENT_VIDEO_PROFILE.transitionFrames / SILENT_VIDEO_PROFILE.fps).toFixed(6)}:offset=${(offsetFrames / SILENT_VIDEO_PROFILE.fps).toFixed(6)}${output}`);
    }
  }
  const filter = lines.join(';\n');
  for (const forbidden of ['zoompan', 'crop', 'rotate', 'transpose', 'perspective', 'pad']) {
    if (new RegExp(`(?:^|[,;])${forbidden}=`, 'u').test(filter)) {
      throw new Error(`静音视频滤镜包含禁止的阅读期运动：${forbidden}=`);
    }
  }
  if (!plan.native_video_count && (filter.includes('scale=') || filter.includes('overlay='))) {
    throw new Error('静态阅读视频意外包含媒体几何滤镜');
  }
  return filter;
}

export function buildVideoOutputArgs(plan, outputPath) {
  return [
    '-filter_complex', buildVideoFilter(plan),
    '-map', '[vout]',
    '-an',
    '-r', String(SILENT_VIDEO_PROFILE.fps),
    '-frames:v', String(plan.total_frames),
    '-c:v', SILENT_VIDEO_PROFILE.encoder,
    '-preset', SILENT_VIDEO_PROFILE.preset,
    '-tune', plan.native_video_count > 0 ? SILENT_VIDEO_PROFILE.nativeVideoTune : SILENT_VIDEO_PROFILE.tune,
    '-crf', String(SILENT_VIDEO_PROFILE.crf),
    '-g', String(plan.total_frames + 1),
    '-keyint_min', String(plan.total_frames + 1),
    '-sc_threshold', '0',
    '-pix_fmt', 'yuv420p',
    '-map_metadata', '-1',
    '-movflags', '+faststart',
    outputPath
  ];
}

export function buildFfmpegArgs(plan, outputDirectory, outputPath) {
  const args = ['-nostdin', '-hide_banner', '-loglevel', 'error', '-n'];
  let nextInputIndex = 0;
  for (const slide of plan.slides) {
    if (slide.background_input_index !== nextInputIndex) throw new Error('视频输入索引不连续');
    const pngPath = safeOutputPath(outputDirectory, slide.png_file);
    const dimensions = readPngDimensions(pngPath);
    if (dimensions.width !== 1080 || dimensions.height !== 1440) {
      throw new Error(`视频输入尺寸错误：${slide.png_file} 为 ${dimensions.width}×${dimensions.height}`);
    }
    args.push('-loop', '1', '-framerate', String(SILENT_VIDEO_PROFILE.fps), '-i', pngPath);
    nextInputIndex += 1;
    if (slide.native_video) {
      if (slide.native_video_input_index !== nextInputIndex) throw new Error('原生视频输入索引不连续');
      const videoPath = safeOutputPath(outputDirectory, slide.native_video.relative_path);
      if (!fs.statSync(videoPath).isFile()) throw new Error(`原生视频不存在：${slide.native_video.relative_path}`);
      args.push('-i', videoPath);
      nextInputIndex += 1;
    }
  }
  if (nextInputIndex !== plan.input_count) throw new Error('视频输入数量与计划不一致');
  args.push(...buildVideoOutputArgs(plan, outputPath));
  return args;
}

function embeddedVerificationFrames(plan, slideIndex) {
  const slide = plan.slides[slideIndex];
  const leadingGuard = slideIndex > 0 ? SILENT_VIDEO_PROFILE.transitionFrames + 1 : 0;
  const trailingGuard = slideIndex < plan.slides.length - 1 ? SILENT_VIDEO_PROFILE.transitionFrames + 1 : 0;
  const firstSafeSourceFrame = leadingGuard;
  const lastSafeSourceFrame = slide.frames - trailingGuard - 1;
  if (lastSafeSourceFrame < firstSafeSourceFrame) {
    throw new Error(`原生视频过短，无法在转场外做嵌入画面验收：${slide.native_video.relative_path}`);
  }
  const sourceFrames = [...new Set([
    firstSafeSourceFrame,
    Math.floor((firstSafeSourceFrame + lastSafeSourceFrame) / 2),
    lastSafeSourceFrame
  ])].sort((left, right) => left - right);
  return sourceFrames.map((sourceFrame) => ({
    source_frame: sourceFrame,
    final_frame: slide.timeline_start_frame + sourceFrame
  }));
}

function buildEmbeddedVerificationFilter(slide, verification) {
  const { layout } = slide.native_video;
  const nextSourceFrame = verification.source_frame + 1;
  const nextFinalFrame = verification.final_frame + 1;
  return [
    `[0:v]fps=${SILENT_VIDEO_PROFILE.fps},trim=end_frame=1,settb=expr=1/${SILENT_VIDEO_PROFILE.fps},setpts=N,setsar=1,format=yuv420p[verify_bg]`,
    `[1:v]fps=${SILENT_VIDEO_PROFILE.fps},tpad=stop_mode=clone:stop_duration=1,trim=start_frame=${verification.source_frame}:end_frame=${nextSourceFrame},settb=expr=1/${SILENT_VIDEO_PROFILE.fps},setpts=N,setsar=1,scale=w=${layout.width}:h=${layout.height}:force_original_aspect_ratio=decrease:force_divisible_by=2,format=yuv420p[verify_native]`,
    `[verify_bg][verify_native]overlay=x=${layout.x}+(${layout.width}-overlay_w)/2:y=${layout.y}+(${layout.height}-overlay_h)/2:shortest=1:eof_action=repeat:eval=init,setsar=1,format=yuv420p[verify_expected_full]`,
    `[verify_expected_full]crop=w=${layout.width}:h=${layout.height}:x=${layout.x}:y=${layout.y},setsar=1,format=yuv420p[verify_expected]`,
    `[2:v]fps=${SILENT_VIDEO_PROFILE.fps},trim=start_frame=${verification.final_frame}:end_frame=${nextFinalFrame},settb=expr=1/${SILENT_VIDEO_PROFILE.fps},setpts=N,crop=w=${layout.width}:h=${layout.height}:x=${layout.x}:y=${layout.y},setsar=1,format=yuv420p[verify_actual]`,
    '[verify_expected][verify_actual]ssim=stats_file=-'
  ].join(';');
}

function verifyEmbeddedNativeVideoFrames({ ffmpeg, outputPath, outputDirectory, plan }) {
  const checks = [];
  for (let slideIndex = 0; slideIndex < plan.slides.length; slideIndex += 1) {
    const slide = plan.slides[slideIndex];
    if (!slide.native_video) continue;
    const verifications = embeddedVerificationFrames(plan, slideIndex);
    const pngPath = safeOutputPath(outputDirectory, slide.png_file);
    const sourcePath = safeOutputPath(outputDirectory, slide.native_video.relative_path);
    const threshold = SILENT_VIDEO_PROFILE.minimumEmbeddedFrameSsim;
    const sampleChecks = [];
    for (const verification of verifications) {
      const rawStats = runCommand(ffmpeg, [
        '-nostdin',
        '-hide_banner',
        '-v', 'error',
        '-loop', '1',
        '-framerate', String(SILENT_VIDEO_PROFILE.fps),
        '-i', pngPath,
        '-i', sourcePath,
        '-i', outputPath,
        '-filter_complex', buildEmbeddedVerificationFilter(slide, verification),
        '-an',
        '-f', 'null', '-'
      ]);
      const match = String(rawStats).match(/All:([0-9.]+)/u);
      const measuredSsim = match ? Number(match[1]) : null;
      if (!Number.isFinite(measuredSsim) || measuredSsim < threshold) {
        throw new Error(`原生视频嵌入画面验收失败：${slide.native_video.relative_path} 的源帧 ${verification.source_frame} SSIM ${String(measuredSsim)} 低于 ${threshold}`);
      }
      sampleChecks.push({
        source_frame: verification.source_frame,
        source_time_seconds: verification.source_frame / SILENT_VIDEO_PROFILE.fps,
        final_frame: verification.final_frame,
        final_time_seconds: verification.final_frame / SILENT_VIDEO_PROFILE.fps,
        measured_ssim: measuredSsim,
        required_minimum_ssim: threshold
      });
    }
    const sourceDuration = slide.native_video.probe.source_duration_seconds;
    const embeddedDuration = slide.frames / SILENT_VIDEO_PROFILE.fps;
    if (embeddedDuration + 1e-9 < sourceDuration) {
      throw new Error(`原生视频视觉时长被截断：${embeddedDuration}/${sourceDuration} 秒`);
    }
    checks.push({
      pass: true,
      relative_path: slide.native_video.relative_path,
      sample_count: sampleChecks.length,
      sample_frame_checks: sampleChecks,
      minimum_measured_ssim: Math.min(...sampleChecks.map((sample) => sample.measured_ssim)),
      required_minimum_ssim: threshold,
      source_duration_seconds: sourceDuration,
      embedded_frames: slide.frames,
      embedded_duration_seconds: embeddedDuration,
      full_visual_duration_preserved: true,
      source_audio_discarded: true
    });
  }
  if (plan.native_video_count > 0 && checks.length === 0) throw new Error('缺少原生视频嵌入画面验收');
  return checks;
}

function verifyVideo({ ffmpeg, ffprobe, outputPath, outputDirectory, plan }) {
  const rawProbe = runCommand(ffprobe, [
    '-v', 'error',
    '-show_entries', 'format=duration,size:stream=index,codec_name,codec_type,width,height,pix_fmt,r_frame_rate,nb_frames',
    '-of', 'json',
    outputPath
  ]);
  const probe = JSON.parse(rawProbe);
  const videos = (probe.streams ?? []).filter((stream) => stream.codec_type === 'video');
  const audios = (probe.streams ?? []).filter((stream) => stream.codec_type === 'audio');
  const video = videos[0];
  const problems = [];
  if (videos.length !== 1) problems.push('视频流数量不是 1');
  if (audios.length !== 0) problems.push('出现音频流');
  if (!video || video.codec_name !== 'h264') problems.push('视频编码不是 H.264');
  if (!video || video.width !== 1080 || video.height !== 1440) problems.push('视频尺寸不是 1080×1440');
  if (!video || video.pix_fmt !== 'yuv420p') problems.push('视频像素格式不是 yuv420p');
  if (!video || video.r_frame_rate !== `${SILENT_VIDEO_PROFILE.fps}/1`) problems.push('视频帧率不是 30fps');
  if (!video || Number(video.nb_frames) !== plan.total_frames) problems.push('视频总帧数不匹配');
  const actualDuration = Number(probe.format?.duration);
  if (!Number.isFinite(actualDuration) || Math.abs(actualDuration - plan.duration_seconds) > 0.001) problems.push('视频时长不匹配');
  if (!Number.isFinite(Number(probe.format?.size)) || Number(probe.format.size) <= 0) problems.push('视频文件为空');
  if (problems.length) throw new Error(`视频验收失败：${problems.join('；')}`);
  runCommand(ffmpeg, ['-v', 'error', '-i', outputPath, '-f', 'null', '-']);
  const readingStability = parseReadingSsimStats(runCommand(ffmpeg, [
    '-nostdin',
    '-hide_banner',
    '-v', 'error',
    '-i', outputPath,
    '-filter_complex', buildReadingStabilityFilter(plan),
    '-an',
    '-f', 'null', '-'
  ]), plan);
  const embeddedNativeVideos = verifyEmbeddedNativeVideoFrames({
    ffmpeg,
    outputPath,
    outputDirectory,
    plan
  });
  return {
    pass: true,
    video_stream_count: videos.length,
    audio_stream_count: audios.length,
    codec: video.codec_name,
    width: video.width,
    height: video.height,
    pixel_format: video.pix_fmt,
    fps: video.r_frame_rate,
    frame_count: Number(video.nb_frames),
    duration_seconds: actualDuration,
    size_bytes: Number(probe.format.size),
    decode_pass: true,
    final_audio_absent: audios.length === 0,
    reading_stability: readingStability,
    native_video: {
      count: plan.native_video_count,
      source_probes: plan.slides.filter((slide) => slide.native_video).map((slide) => slide.native_video.probe),
      embedded_frame_checks: embeddedNativeVideos,
      all_source_videos_decode_pass: plan.slides.filter((slide) => slide.native_video).every((slide) => slide.native_video.probe.decode_pass === true),
      all_visual_durations_preserved: embeddedNativeVideos.every((check) => check.full_visual_duration_preserved),
      source_audio_discarded: true
    }
  };
}

export function renderSilentVideos({ outputs, templates, outputDirectory, ffmpeg = process.env.YICHEN_X_SLICER_FFMPEG || 'ffmpeg', ffprobe = process.env.YICHEN_X_SLICER_FFPROBE || 'ffprobe' }) {
  assertSilentVideoRuntime({ ffmpeg, ffprobe });
  const nativeVideoProbes = new Map();
  for (const output of outputs) {
    const isRequestedNativeVideo = output?.kind === 'media'
      && output?.media?.type === 'video'
      && output?.media?.native_video_requested === true;
    if (isRequestedNativeVideo && !isNativeVideoOutput(output)) {
      throw new Error('原生视频已请求但缺少本地 MP4 或媒体布局；拒绝只输出静态封面');
    }
    if (!isNativeVideoOutput(output)) continue;
    const relativePath = output.media.native_video.relative_path;
    normalizedMediaLayout(output.media_layout);
    if (!nativeVideoProbes.has(relativePath)) {
      nativeVideoProbes.set(relativePath, probeNativeVideoSource({
        outputDirectory,
        relativePath,
        ffmpeg,
        ffprobe
      }));
    }
  }
  const records = [];
  for (const template of templates) {
    const plan = buildVideoPlan(outputs, template, { nativeVideoProbes });
    const outputPath = safeOutputPath(outputDirectory, plan.file);
    const partialPath = safeOutputPath(outputDirectory, plan.file.replace(/\.mp4$/u, '.partial.mp4'));
    const filterPath = safeOutputPath(outputDirectory, plan.filter_file);
    const filter = buildVideoFilter(plan);
    fs.writeFileSync(filterPath, filter + '\n', { encoding: 'utf8', flag: 'wx' });
    const sourcePngs = plan.slides.map((slide) => {
      const pngPath = safeOutputPath(outputDirectory, slide.png_file);
      return { file: slide.png_file, sha256: sha256File(pngPath), frames: slide.frames, kind: slide.kind };
    });
    runCommand(ffmpeg, buildFfmpegArgs(plan, outputDirectory, partialPath));
    const checks = verifyVideo({ ffmpeg, ffprobe, outputPath: partialPath, outputDirectory, plan });
    fs.renameSync(partialPath, outputPath);
    const hasNativeVideo = plan.native_video_count > 0;
    records.push({
      version: 'yichen-x-slicer-silent-video/v2',
      template_id: plan.template_id,
      template_name: plan.template_name,
      file: plan.file,
      sha256: sha256File(outputPath),
      filter_file: plan.filter_file,
      filter_sha256: sha256File(filterPath),
      profile: SILENT_VIDEO_PROFILE,
      source_pngs: sourcePngs,
      source_videos: plan.slides.filter((slide) => slide.native_video).map((slide) => slide.native_video.probe),
      slide_frames: plan.slides.map((slide) => slide.frames),
      transition_count: plan.transition_count,
      transition_frames: plan.transition_frames,
      total_frames: plan.total_frames,
      duration_seconds: plan.duration_seconds,
      reading_motion: hasNativeVideo ? 'native_video_content_only' : 'none',
      transition_motion_only: !hasNativeVideo,
      native_video_embedded: hasNativeVideo,
      complete_native_video_visual_duration: hasNativeVideo ? checks.native_video.all_visual_durations_preserved : null,
      bgm: false,
      voice: false,
      audio: false,
      checks
    });
  }
  return records;
}
