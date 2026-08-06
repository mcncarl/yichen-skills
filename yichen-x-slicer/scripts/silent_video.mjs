import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export const VIDEO_PROFILE = Object.freeze({
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
  audioSampleRate: 48000,
  audioChannels: 2,
  audioBitrate: '192k',
  minimumAudioSdrDb: 12,
  minimumBoundaryAudioSdrDb: 8,
  minimumSourceAudiblePeakDb: -60,
  maximumSilentIntervalPeakDb: -60,
  maximumSilentIntervalMeanDb: -80,
  audioCodecBoundarySamples: 1024,
  minimumAdjacentReadingSsim: 0.9999,
  minimumEmbeddedFrameSsim: 0.98
});

// Backward-compatible export for callers created before source-audio preservation was added.
export const SILENT_VIDEO_PROFILE = VIDEO_PROFILE;

function clamp(minimum, maximum, value) {
  return Math.max(minimum, Math.min(maximum, value));
}

function sha256File(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

const RENDERER_SCRIPT_PATH = fileURLToPath(import.meta.url);
const RENDERER_SCRIPT_SHA256_AT_LOAD = sha256File(RENDERER_SCRIPT_PATH);

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
  if (options.capture === 'stderr') return result.stderr;
  if (options.capture === 'both') return `${String(result.stdout ?? '')}\n${String(result.stderr ?? '')}`;
  return result.stdout;
}

function assertBinary(binary) {
  runCommand(binary, ['-version']);
}

function runtimeProvenance({ ffmpeg, ffprobe }) {
  const scriptDirectory = path.dirname(RENDERER_SCRIPT_PATH);
  const candidates = [
    { file: 'scripts/silent_video.mjs', absolute: RENDERER_SCRIPT_PATH, sha256: RENDERER_SCRIPT_SHA256_AT_LOAD },
    { file: 'scripts/yichen_x_slicer.mjs', absolute: path.join(scriptDirectory, 'yichen_x_slicer.mjs') },
    { file: 'scripts/test.mjs', absolute: path.join(scriptDirectory, 'test.mjs') },
    { file: 'SKILL.md', absolute: path.join(scriptDirectory, '..', 'SKILL.md') }
  ];
  const files = candidates.map((candidate) => {
    if (!fs.statSync(candidate.absolute).isFile()) throw new Error(`缺少运行时来源文件：${candidate.file}`);
    return { file: candidate.file, sha256: candidate.sha256 ?? sha256File(candidate.absolute) };
  });
  return {
    version: 'yichen-x-slicer-runtime-provenance/v1',
    files,
    node_version: process.version,
    ffmpeg_version: String(runCommand(ffmpeg, ['-version'])).split(/\r?\n/u)[0],
    ffprobe_version: String(runCommand(ffprobe, ['-version'])).split(/\r?\n/u)[0]
  };
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

function finiteNumber(value) {
  if (value == null || String(value).trim() === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function videoFramesForDuration(durationSeconds) {
  const exactFrames = Number(durationSeconds) * SILENT_VIDEO_PROFILE.fps;
  if (!Number.isFinite(exactFrames) || exactFrames <= 0) throw new Error('原生视频视觉时长无效');
  const nearestFrame = Math.round(exactFrames);
  const ffprobeDecimalToleranceFrames = SILENT_VIDEO_PROFILE.fps * 0.0000005 + 1e-9;
  const frames = Math.abs(exactFrames - nearestFrame) <= ffprobeDecimalToleranceFrames
    ? nearestFrame
    : Math.ceil(exactFrames);
  return Math.max(1, frames);
}

function probeFirstPacketTime(ffprobe, sourcePath, streamSelector) {
  const raw = runCommand(ffprobe, [
    '-v', 'error',
    '-select_streams', streamSelector,
    '-read_intervals', '%+#1',
    '-show_packets',
    '-show_entries', 'packet=pts_time',
    '-of', 'csv=p=0',
    sourcePath
  ]);
  return finiteNumber(String(raw).trim().split(/\r?\n/u)[0]);
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
    '-show_entries', 'format=duration,size,format_name,start_time:stream=index,codec_name,codec_type,width,height,pix_fmt,r_frame_rate,avg_frame_rate,nb_frames,duration,duration_ts,time_base,start_pts,start_time,sample_rate,channels,channel_layout',
    '-of', 'json',
    sourcePath
  ]);
  const probe = JSON.parse(rawProbe);
  const videos = (probe.streams ?? []).filter((stream) => stream.codec_type === 'video');
  const audios = (probe.streams ?? []).filter((stream) => stream.codec_type === 'audio');
  if (videos.length !== 1) throw new Error(`原生视频流数量不是 1：${relativePath}`);
  if (audios.length > 1) throw new Error(`原生视频音轨数量超过 1，无法无歧义保留原声：${relativePath}`);
  const video = videos[0];
  const videoStartFromTimeBase = finiteNumber(video.start_pts) != null && rationalNumber(video.time_base)
    ? Number(video.start_pts) * rationalNumber(video.time_base)
    : null;
  const videoStartTime = videoStartFromTimeBase
    ?? finiteNumber(video.start_time)
    ?? probeFirstPacketTime(ffprobe, sourcePath, 'v:0');
  const audioStartFromTimeBase = audios.length > 0 && finiteNumber(audios[0].start_pts) != null && rationalNumber(audios[0].time_base)
    ? Number(audios[0].start_pts) * rationalNumber(audios[0].time_base)
    : null;
  const audioStartTime = audios.length > 0
    ? (audioStartFromTimeBase ?? finiteNumber(audios[0].start_time) ?? probeFirstPacketTime(ffprobe, sourcePath, 'a:0'))
    : null;
  if (audios.length > 0 && (videoStartTime == null || audioStartTime == null)) {
    throw new Error(`无法探测原生视频的音画起始时间：${relativePath}`);
  }
  const durationFromTimeBase = finitePositive(video.duration_ts) && rationalNumber(video.time_base)
    ? Number(video.duration_ts) * rationalNumber(video.time_base)
    : null;
  const durationSeconds = finitePositive(durationFromTimeBase)
    ?? finitePositive(video.duration)
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
    '-map', '0:a?',
    '-f', 'null', '-'
  ]);
  const embeddedFrames = videoFramesForDuration(durationSeconds);
  const audioStreams = audios.map((audio) => {
    const durationFromTimeBase = finitePositive(audio.duration_ts) && rationalNumber(audio.time_base)
      ? Number(audio.duration_ts) * rationalNumber(audio.time_base)
      : null;
    return {
      index: Number(audio.index),
      codec: audio.codec_name ?? null,
      sample_rate: finitePositive(audio.sample_rate),
      channels: finitePositive(audio.channels),
      channel_layout: audio.channel_layout ?? null,
      duration_seconds: finitePositive(durationFromTimeBase) ?? finitePositive(audio.duration),
      start_time_seconds: audioStartTime
    };
  });
  if (audioStreams.some((audio) => !audio.duration_seconds || audio.start_time_seconds == null)) {
    throw new Error(`原生视频音轨缺少可核验的起点或持续时间：${relativePath}`);
  }
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
    video_start_time_seconds: videoStartTime,
    source_audio_present: audios.length > 0,
    audio_streams: audioStreams,
    audio_offset_from_video_seconds: audios.length > 0 ? audioStartTime - videoStartTime : null,
    embedded_frames: embeddedFrames,
    embedded_duration_seconds: embeddedFrames / SILENT_VIDEO_PROFILE.fps,
    decode_pass: true,
    audio_decode_pass: true
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
      if (nativeVideo) nativeVideo.has_source_audio = Number(nativeVideo.probe?.audio_stream_count) > 0;
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
    file: `video-${template.id}.mp4`,
    filter_file: `video-${template.id}-filter.txt`,
    slides,
    transition_count: transitionCount,
    transition_frames: SILENT_VIDEO_PROFILE.transitionFrames,
    input_count: nextInputIndex,
    native_video_count: slides.filter((slide) => slide.native_video).length,
    source_audio_video_count: slides.filter((slide) => slide.native_video?.has_source_audio).length,
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

function secondsForFrames(frames) {
  return (frames / SILENT_VIDEO_PROFILE.fps).toFixed(6);
}

function buildAudioFilterLines(plan) {
  if (plan.source_audio_video_count === 0) return [];
  const lines = [];
  const samplesPerFrame = SILENT_VIDEO_PROFILE.audioSampleRate / SILENT_VIDEO_PROFILE.fps;
  if (!Number.isInteger(samplesPerFrame)) throw new Error('音频采样率不能按视频帧率整分');
  for (let index = 0; index < plan.slides.length; index += 1) {
    const slide = plan.slides[index];
    const wholeSamples = slide.frames * samplesPerFrame;
    if (slide.native_video?.has_source_audio) {
      const videoStartTime = finiteNumber(slide.native_video.probe.video_start_time_seconds);
      if (videoStartTime == null) throw new Error(`缺少原生视频音画起始时间：${slide.native_video.relative_path}`);
      lines.push(
        `[${slide.native_video_input_index}:a:0]`
        + `asetpts=PTS-(${videoStartTime.toFixed(9)}/TB),`
        + `aresample=${SILENT_VIDEO_PROFILE.audioSampleRate}:async=1:first_pts=0,`
        + `aformat=sample_fmts=fltp:sample_rates=${SILENT_VIDEO_PROFILE.audioSampleRate}:channel_layouts=stereo,`
        + `atrim=end_sample=${wholeSamples},apad=whole_len=${wholeSamples},atrim=end_sample=${wholeSamples},`
        + `asetpts=N/SR/TB[audio_slide_${index}]`
      );
    } else {
      lines.push(
        `anullsrc=r=${SILENT_VIDEO_PROFILE.audioSampleRate}:cl=stereo,`
        + `atrim=end_sample=${wholeSamples},asetpts=N/SR/TB[audio_slide_${index}]`
      );
    }
  }
  if (plan.slides.length === 1) {
    lines.push('[audio_slide_0]anull[audio_timeline]');
  } else {
    const transitionSamples = SILENT_VIDEO_PROFILE.transitionFrames * samplesPerFrame;
    let left = '[audio_slide_0]';
    for (let index = 1; index < plan.slides.length; index += 1) {
      const right = `[audio_slide_${index}]`;
      const output = index === plan.slides.length - 1 ? '[audio_timeline]' : `[audio_mix_${index}]`;
      lines.push(`${left}${right}acrossfade=ns=${transitionSamples}:c1=tri:c2=tri${output}`);
      left = output;
    }
  }
  const totalSamples = plan.total_frames * samplesPerFrame;
  lines.push(`[audio_timeline]atrim=end_sample=${totalSamples},apad=whole_len=${totalSamples},atrim=end_sample=${totalSamples},asetpts=N/SR/TB[aout]`);
  return lines;
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
  lines.push(...buildAudioFilterLines(plan));
  const filter = lines.join(';\n');
  for (const forbidden of ['zoompan', 'crop', 'rotate', 'transpose', 'perspective', 'pad']) {
    if (new RegExp(`(?:^|[,;])${forbidden}=`, 'u').test(filter)) {
      throw new Error(`视频滤镜包含禁止的阅读期运动：${forbidden}=`);
    }
  }
  if (!plan.native_video_count && (filter.includes('scale=') || filter.includes('overlay='))) {
    throw new Error('静态阅读视频意外包含媒体几何滤镜');
  }
  return filter;
}

export function buildVideoOutputArgs(plan, outputPath) {
  const args = [
    '-filter_complex', buildVideoFilter(plan),
    '-map', '[vout]',
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
  ];
  if (plan.source_audio_video_count > 0) {
    args.push(
      '-map', '[aout]',
      '-c:a', 'aac',
      '-b:a', SILENT_VIDEO_PROFILE.audioBitrate,
      '-ar', String(SILENT_VIDEO_PROFILE.audioSampleRate),
      '-ac', String(SILENT_VIDEO_PROFILE.audioChannels)
    );
  } else {
    args.push('-an');
  }
  args.push(outputPath);
  return args;
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
      full_visual_duration_preserved: true
    });
  }
  if (plan.native_video_count > 0 && checks.length === 0) throw new Error('缺少原生视频嵌入画面验收');
  return checks;
}

function audioSamplesPerVideoFrame() {
  const value = SILENT_VIDEO_PROFILE.audioSampleRate / SILENT_VIDEO_PROFILE.fps;
  if (!Number.isInteger(value)) throw new Error('音频采样率不能按视频帧率整分');
  return value;
}

function nativeAudioTiming(plan, slideIndex) {
  const slide = plan.slides[slideIndex];
  const audio = slide.native_video?.probe?.audio_streams?.[0];
  const durationSeconds = finitePositive(audio?.duration_seconds);
  const offsetSeconds = finiteNumber(slide.native_video?.probe?.audio_offset_from_video_seconds);
  const sourceStartTimeSeconds = finiteNumber(audio?.start_time_seconds);
  if (!slide.native_video?.has_source_audio || durationSeconds == null || offsetSeconds == null || sourceStartTimeSeconds == null) {
    throw new Error(`缺少原声音轨时长或音画偏移：${slide.native_video?.relative_path ?? 'unknown'}`);
  }
  const sampleRate = SILENT_VIDEO_PROFILE.audioSampleRate;
  const samplesPerFrame = audioSamplesPerVideoFrame();
  const slideSamples = slide.frames * samplesPerFrame;
  const timelineStartSample = slide.timeline_start_frame * samplesPerFrame;
  const exactOffsetSamples = offsetSeconds * sampleRate;
  const exactDurationSamples = durationSeconds * sampleRate;
  const offsetSamples = Math.round(exactOffsetSamples);
  const durationSamples = Math.round(exactDurationSamples);
  const activeStartSample = Math.max(0, Math.floor(exactOffsetSamples));
  const activeEndSample = Math.min(slideSamples, Math.ceil(exactOffsetSamples + exactDurationSamples));
  if (activeEndSample <= activeStartSample) {
    throw new Error(`原声音轨与源视频视觉区间没有重叠：${slide.native_video.relative_path}`);
  }
  const transitionSamples = SILENT_VIDEO_PROFILE.transitionFrames * samplesPerFrame;
  const comparisonStartSample = Math.max(activeStartSample, slideIndex > 0 ? transitionSamples : 0);
  const comparisonEndSample = Math.min(
    activeEndSample,
    slideIndex < plan.slides.length - 1 ? slideSamples - transitionSamples : slideSamples
  );
  return {
    slide,
    source_start_time_seconds: sourceStartTimeSeconds,
    exact_offset_samples: exactOffsetSamples,
    exact_duration_samples: exactDurationSamples,
    offset_samples: offsetSamples,
    duration_samples: durationSamples,
    slide_samples: slideSamples,
    timeline_start_sample: timelineStartSample,
    active_start_sample: activeStartSample,
    active_end_sample: activeEndSample,
    comparison_start_sample: comparisonStartSample,
    comparison_end_sample: comparisonEndSample
  };
}

function audioVerificationRanges(plan, slideIndex) {
  const timing = nativeAudioTiming(plan, slideIndex);
  const comparisonSamples = timing.comparison_end_sample - timing.comparison_start_sample;
  const makeRange = (pageStartSample, sampleCount) => {
    const sourceStartSample = Math.max(0, pageStartSample - timing.offset_samples);
    return {
      page_start_sample: pageStartSample,
      source_start_sample: sourceStartSample,
      final_start_sample: timing.timeline_start_sample + pageStartSample,
      sample_count: sampleCount,
      page_start_seconds: pageStartSample / SILENT_VIDEO_PROFILE.audioSampleRate,
      source_start_seconds: sourceStartSample / SILENT_VIDEO_PROFILE.audioSampleRate,
      final_start_seconds: (timing.timeline_start_sample + pageStartSample) / SILENT_VIDEO_PROFILE.audioSampleRate,
      duration_seconds: sampleCount / SILENT_VIDEO_PROFILE.audioSampleRate,
      source_audio_start_time_seconds: timing.source_start_time_seconds
    };
  };
  const active = makeRange(timing.active_start_sample, timing.active_end_sample - timing.active_start_sample);
  if (comparisonSamples <= 0) return { timing, active, full: null, samples: [] };
  const full = makeRange(timing.comparison_start_sample, comparisonSamples);
  if (comparisonSamples < 256) return { timing, active, full, samples: [] };
  const sampleCount = Math.min(
    SILENT_VIDEO_PROFILE.audioSampleRate,
    Math.max(256, Math.floor(comparisonSamples / 5))
  );
  const starts = [...new Set([
    timing.comparison_start_sample,
    timing.comparison_start_sample + Math.floor((comparisonSamples - sampleCount) / 2),
    timing.comparison_end_sample - sampleCount
  ])].sort((left, right) => left - right);
  return { timing, active, full, samples: starts.map((start) => makeRange(start, sampleCount)) };
}

function normalizedSourceAudioPrefix(window) {
  const sampleRate = SILENT_VIDEO_PROFILE.audioSampleRate;
  return `[0:a:0]asetpts=PTS-(${window.source_audio_start_time_seconds.toFixed(9)}/TB),aresample=${sampleRate}:async=1:first_pts=0,aformat=sample_fmts=fltp:sample_rates=${sampleRate}:channel_layouts=stereo`;
}

function buildAudioVerificationFilter(window) {
  const sampleRate = SILENT_VIDEO_PROFILE.audioSampleRate;
  const sourceEndSample = window.source_start_sample + window.sample_count;
  const finalEndSample = window.final_start_sample + window.sample_count;
  return [
    `${normalizedSourceAudioPrefix(window)},atrim=start_sample=${window.source_start_sample}:end_sample=${sourceEndSample},asetpts=N/SR/TB[source_audio]`,
    `[1:a:0]aresample=${sampleRate}:async=1:first_pts=0,aformat=sample_fmts=fltp:sample_rates=${sampleRate}:channel_layouts=stereo,atrim=start_sample=${window.final_start_sample}:end_sample=${finalEndSample},asetpts=N/SR/TB[final_audio]`,
    '[source_audio][final_audio]asdr[audio_compare]'
  ].join(';');
}

function buildSourceVolumeFilter(window) {
  const sourceEndSample = window.source_start_sample + window.sample_count;
  return `${normalizedSourceAudioPrefix(window)},atrim=start_sample=${window.source_start_sample}:end_sample=${sourceEndSample},asetpts=N/SR/TB,volumedetect[source_volume]`;
}

function parseAudioSdr(rawStats) {
  const values = [...String(rawStats).matchAll(/SDR ch\d+:\s*(inf|-?\d+(?:\.\d+)?)/giu)]
    .map((match) => match[1].toLowerCase() === 'inf' ? Number.POSITIVE_INFINITY : Number(match[1]));
  if (!values.length || values.some((value) => Number.isNaN(value))) {
    throw new Error('无法解析原声音频对齐验收结果');
  }
  return {
    channel_sdr_db: values.map((value) => Number.isFinite(value) ? value : 'inf'),
    minimum_sdr_db: values.every((value) => !Number.isFinite(value))
      ? 'inf'
      : Math.min(...values.filter(Number.isFinite))
  };
}

function parseVolumeStats(rawStats) {
  const parseValue = (name) => {
    const match = String(rawStats).match(new RegExp(`${name}:\\s*(-inf|-?\\d+(?:\\.\\d+)?)\\s*dB`, 'iu'));
    if (!match) throw new Error(`无法解析音频 ${name}`);
    return match[1].toLowerCase() === '-inf' ? Number.NEGATIVE_INFINITY : Number(match[1]);
  };
  const mean = parseValue('mean_volume');
  const peak = parseValue('max_volume');
  return {
    mean_db: Number.isFinite(mean) ? mean : '-inf',
    peak_db: Number.isFinite(peak) ? peak : '-inf',
    mean_value: mean,
    peak_value: peak
  };
}

function compareAudioRange({ ffmpeg, sourcePath, outputPath, range }) {
  const rawStats = runCommand(ffmpeg, [
    '-nostdin',
    '-hide_banner',
    '-v', 'info',
    '-i', sourcePath,
    '-i', outputPath,
    '-filter_complex', buildAudioVerificationFilter(range),
    '-map', '[audio_compare]',
    '-vn',
    '-f', 'null', '-'
  ], { capture: 'stderr' });
  const sdr = parseAudioSdr(rawStats);
  const minimum = sdr.minimum_sdr_db === 'inf' ? Number.POSITIVE_INFINITY : sdr.minimum_sdr_db;
  if (minimum < SILENT_VIDEO_PROFILE.minimumAudioSdrDb) {
    throw new Error(`原视频声音验收失败：源音频 ${range.source_start_seconds.toFixed(3)} 秒起的 SDR ${minimum} dB 低于 ${SILENT_VIDEO_PROFILE.minimumAudioSdrDb} dB`);
  }
  return { ...range, ...sdr, required_minimum_sdr_db: SILENT_VIDEO_PROFILE.minimumAudioSdrDb };
}

function measureSourceAudioRange({ ffmpeg, sourcePath, range }) {
  const rawStats = runCommand(ffmpeg, [
    '-nostdin',
    '-hide_banner',
    '-v', 'info',
    '-i', sourcePath,
    '-filter_complex', buildSourceVolumeFilter(range),
    '-map', '[source_volume]',
    '-vn',
    '-f', 'null', '-'
  ], { capture: 'stderr' });
  return parseVolumeStats(rawStats);
}

function verifyEmbeddedNativeVideoAudio({ ffmpeg, outputPath, outputDirectory, plan }) {
  const checks = [];
  for (let slideIndex = 0; slideIndex < plan.slides.length; slideIndex += 1) {
    const slide = plan.slides[slideIndex];
    if (!slide.native_video?.has_source_audio) continue;
    const sourcePath = safeOutputPath(outputDirectory, slide.native_video.relative_path);
    const ranges = audioVerificationRanges(plan, slideIndex);
    const activeSourceVolume = measureSourceAudioRange({ ffmpeg, sourcePath, range: ranges.active });
    if (activeSourceVolume.peak_value <= SILENT_VIDEO_PROFILE.minimumSourceAudiblePeakDb) {
      throw new Error(`原生视频音轨没有可核验声音：${slide.native_video.relative_path}`);
    }
    const coreSourceVolume = ranges.full
      ? measureSourceAudioRange({ ffmpeg, sourcePath, range: ranges.full })
      : null;
    const coreAudible = coreSourceVolume?.peak_value > SILENT_VIDEO_PROFILE.minimumSourceAudiblePeakDb;
    const fullIntervalCheck = coreAudible
      ? compareAudioRange({ ffmpeg, sourcePath, outputPath, range: ranges.full })
      : null;
    const samples = ranges.samples.map((range) => {
      const sourceVolume = measureSourceAudioRange({ ffmpeg, sourcePath, range });
      if (sourceVolume.peak_value <= SILENT_VIDEO_PROFILE.minimumSourceAudiblePeakDb) {
        return {
          ...range,
          source_volume: { mean_db: sourceVolume.mean_db, peak_db: sourceVolume.peak_db },
          audible_evidence: false
        };
      }
      return {
        ...compareAudioRange({ ffmpeg, sourcePath, outputPath, range }),
        source_volume: { mean_db: sourceVolume.mean_db, peak_db: sourceVolume.peak_db },
        audible_evidence: true
      };
    });
    checks.push({
      pass: true,
      relative_path: slide.native_video.relative_path,
      source_audio_stream_count: slide.native_video.probe.audio_stream_count,
      final_timeline_start_seconds: slide.timeline_start_frame / SILENT_VIDEO_PROFILE.fps,
      active_timeline_start_sample: ranges.timing.timeline_start_sample + ranges.timing.active_start_sample,
      active_timeline_end_sample: ranges.timing.timeline_start_sample + ranges.timing.active_end_sample,
      active_source_volume: {
        mean_db: activeSourceVolume.mean_db,
        peak_db: activeSourceVolume.peak_db,
        required_minimum_peak_db: SILENT_VIDEO_PROFILE.minimumSourceAudiblePeakDb
      },
      full_interval_check: fullIntervalCheck ? {
        ...fullIntervalCheck,
        source_volume: {
          mean_db: coreSourceVolume.mean_db,
          peak_db: coreSourceVolume.peak_db,
          required_minimum_peak_db: SILENT_VIDEO_PROFILE.minimumSourceAudiblePeakDb
        },
        audible_evidence: true
      } : null,
      sample_count: samples.length,
      sample_checks: samples,
      requires_transition_timeline_evidence: !coreAudible,
      source_audio_preserved: true,
      timeline_aligned: true
    });
  }
  if (checks.length !== plan.source_audio_video_count) {
    throw new Error(`原声音频验收数量错误：${checks.length}/${plan.source_audio_video_count}`);
  }
  return checks;
}

function expectedTimelineInputs(plan, outputDirectory) {
  const args = [];
  const inputBySlideIndex = new Map();
  for (let slideIndex = 0; slideIndex < plan.slides.length; slideIndex += 1) {
    const slide = plan.slides[slideIndex];
    if (!slide.native_video?.has_source_audio) continue;
    inputBySlideIndex.set(slideIndex, inputBySlideIndex.size);
    args.push('-i', safeOutputPath(outputDirectory, slide.native_video.relative_path));
  }
  if (inputBySlideIndex.size !== plan.source_audio_video_count) {
    throw new Error('独立原声参考时间轴的输入数量不匹配');
  }
  return { args, inputBySlideIndex };
}

function buildIndependentExpectedTimeline(plan, inputBySlideIndex) {
  const sampleRate = SILENT_VIDEO_PROFILE.audioSampleRate;
  const samplesPerFrame = audioSamplesPerVideoFrame();
  const transitionSamples = SILENT_VIDEO_PROFILE.transitionFrames * samplesPerFrame;
  const totalSamples = plan.total_frames * samplesPerFrame;
  const lines = [];
  const slideLabels = [];
  for (let slideIndex = 0; slideIndex < plan.slides.length; slideIndex += 1) {
    const slide = plan.slides[slideIndex];
    const wholeSamples = slide.frames * samplesPerFrame;
    const rawLabel = `[expected_raw_${slideIndex}]`;
    if (slide.native_video?.has_source_audio) {
      const sourceInputIndex = inputBySlideIndex.get(slideIndex);
      const videoStartTime = finiteNumber(slide.native_video.probe.video_start_time_seconds);
      if (!Number.isInteger(sourceInputIndex) || videoStartTime == null) {
        throw new Error(`独立原声参考缺少输入或视频起点：${slide.native_video.relative_path}`);
      }
      lines.push(
        `[${sourceInputIndex}:a:0]`
        + `asetpts=PTS-(${videoStartTime.toFixed(9)}/TB),`
        + `aresample=${sampleRate}:async=1:first_pts=0,`
        + `aformat=sample_fmts=fltp:sample_rates=${sampleRate}:channel_layouts=stereo,`
        + `atrim=end_sample=${wholeSamples},apad=whole_len=${wholeSamples},atrim=end_sample=${wholeSamples},`
        + `asetpts=N/SR/TB${rawLabel}`
      );
    } else {
      lines.push(
        `anullsrc=r=${sampleRate}:cl=stereo,atrim=end_sample=${wholeSamples},`
        + `asetpts=N/SR/TB${rawLabel}`
      );
    }
    const filters = [];
    if (slideIndex > 0) filters.push(`afade=t=in:ss=0:ns=${transitionSamples}:curve=tri`);
    if (slideIndex < plan.slides.length - 1) {
      filters.push(`afade=t=out:ss=${wholeSamples - transitionSamples}:ns=${transitionSamples}:curve=tri`);
    }
    const timelineStartSample = slide.timeline_start_frame * samplesPerFrame;
    filters.push(`adelay=delays=${timelineStartSample}S:all=1`);
    filters.push(`atrim=end_sample=${totalSamples}`);
    filters.push('asetpts=N/SR/TB');
    const slideLabel = `[expected_slide_${slideIndex}]`;
    lines.push(`${rawLabel}${filters.join(',')}${slideLabel}`);
    slideLabels.push(slideLabel);
  }
  if (slideLabels.length === 1) {
    lines.push(`${slideLabels[0]}anull[expected_mixed]`);
  } else {
    lines.push(`${slideLabels.join('')}amix=inputs=${slideLabels.length}:duration=longest:dropout_transition=0:normalize=0[expected_mixed]`);
  }
  lines.push(
    `[expected_mixed]atrim=end_sample=${totalSamples},apad=whole_len=${totalSamples},`
    + `atrim=end_sample=${totalSamples},asetpts=N/SR/TB[expected_timeline]`
  );
  return lines;
}

function exactAudioRange(range) {
  const startSample = Math.round(Number(range.start_sample));
  const endSample = Math.round(Number(range.end_sample));
  if (!Number.isInteger(startSample) || !Number.isInteger(endSample) || startSample < 0 || endSample <= startSample) {
    throw new Error('音频验收采样区间无效');
  }
  return { start_sample: startSample, end_sample: endSample, sample_count: endSample - startSample };
}

function measureExpectedTimelineRange({ ffmpeg, outputDirectory, plan, range }) {
  const exact = exactAudioRange(range);
  const inputs = expectedTimelineInputs(plan, outputDirectory);
  const lines = buildIndependentExpectedTimeline(plan, inputs.inputBySlideIndex);
  lines.push(
    `[expected_timeline]atrim=start_sample=${exact.start_sample}:end_sample=${exact.end_sample},`
    + 'asetpts=N/SR/TB,volumedetect[expected_volume]'
  );
  const rawStats = runCommand(ffmpeg, [
    '-nostdin',
    '-hide_banner',
    '-v', 'info',
    ...inputs.args,
    '-filter_complex', lines.join(';'),
    '-map', '[expected_volume]',
    '-vn',
    '-f', 'null', '-'
  ], { capture: 'stderr' });
  return parseVolumeStats(rawStats);
}

function measureFinalAudioRange({ ffmpeg, outputPath, range }) {
  const exact = exactAudioRange(range);
  const filter = `[0:a:0]aresample=${SILENT_VIDEO_PROFILE.audioSampleRate}:async=0:first_pts=0,atrim=start_sample=${exact.start_sample}:end_sample=${exact.end_sample},asetpts=N/SR/TB,volumedetect[actual_volume]`;
  const rawStats = runCommand(ffmpeg, [
    '-nostdin',
    '-hide_banner',
    '-v', 'info',
    '-i', outputPath,
    '-filter_complex', filter,
    '-map', '[actual_volume]',
    '-vn',
    '-f', 'null', '-'
  ], { capture: 'stderr' });
  return parseVolumeStats(rawStats);
}

function compareExpectedTimelineRange({ ffmpeg, outputPath, outputDirectory, plan, range }) {
  const exact = exactAudioRange(range);
  const inputs = expectedTimelineInputs(plan, outputDirectory);
  const finalInputIndex = inputs.inputBySlideIndex.size;
  const lines = buildIndependentExpectedTimeline(plan, inputs.inputBySlideIndex);
  lines.push(
    `[expected_timeline]atrim=start_sample=${exact.start_sample}:end_sample=${exact.end_sample},`
    + 'asetpts=N/SR/TB[expected_range]'
  );
  lines.push(
    `[${finalInputIndex}:a:0]aresample=${SILENT_VIDEO_PROFILE.audioSampleRate}:async=0:first_pts=0,`
    + `aformat=sample_fmts=fltp:sample_rates=${SILENT_VIDEO_PROFILE.audioSampleRate}:channel_layouts=stereo,`
    + `atrim=start_sample=${exact.start_sample}:end_sample=${exact.end_sample},asetpts=N/SR/TB[actual_range]`
  );
  lines.push('[expected_range][actual_range]asdr[audio_compare]');
  const rawStats = runCommand(ffmpeg, [
    '-nostdin',
    '-hide_banner',
    '-v', 'info',
    ...inputs.args,
    '-i', outputPath,
    '-filter_complex', lines.join(';'),
    '-map', '[audio_compare]',
    '-vn',
    '-f', 'null', '-'
  ], { capture: 'stderr' });
  return parseAudioSdr(rawStats);
}

function verifyExpectedTimelineRange({ ffmpeg, outputPath, outputDirectory, plan, range, reason }) {
  const exact = exactAudioRange(range);
  const expectedVolume = measureExpectedTimelineRange({ ffmpeg, outputDirectory, plan, range: exact });
  const expectedAudible = expectedVolume.peak_value > SILENT_VIDEO_PROFILE.minimumSourceAudiblePeakDb;
  const base = {
    ...exact,
    reason,
    final_start_seconds: exact.start_sample / SILENT_VIDEO_PROFILE.audioSampleRate,
    duration_seconds: exact.sample_count / SILENT_VIDEO_PROFILE.audioSampleRate,
    expected_audible: expectedAudible,
    expected_volume: { mean_db: expectedVolume.mean_db, peak_db: expectedVolume.peak_db }
  };
  if (expectedAudible) {
    const sdr = compareExpectedTimelineRange({ ffmpeg, outputPath, outputDirectory, plan, range: exact });
    const minimum = sdr.minimum_sdr_db === 'inf' ? Number.POSITIVE_INFINITY : sdr.minimum_sdr_db;
    if (minimum < SILENT_VIDEO_PROFILE.minimumBoundaryAudioSdrDb) {
      throw new Error(`原声时间轴边界验收失败：${reason} 的 SDR ${minimum} dB 低于 ${SILENT_VIDEO_PROFILE.minimumBoundaryAudioSdrDb} dB`);
    }
    return {
      ...base,
      verification: 'independent_expected_timeline_sdr',
      ...sdr,
      required_minimum_sdr_db: SILENT_VIDEO_PROFILE.minimumBoundaryAudioSdrDb,
      pass: true
    };
  }
  const actualVolume = measureFinalAudioRange({ ffmpeg, outputPath, range: exact });
  if (actualVolume.peak_value > SILENT_VIDEO_PROFILE.maximumSilentIntervalPeakDb
    || actualVolume.mean_value > SILENT_VIDEO_PROFILE.maximumSilentIntervalMeanDb) {
    throw new Error(`应为静音的原声边界出现声音：${reason}`);
  }
  return {
    ...base,
    verification: 'strict_silence',
    actual_volume: { mean_db: actualVolume.mean_db, peak_db: actualVolume.peak_db },
    required_maximum_peak_db: SILENT_VIDEO_PROFILE.maximumSilentIntervalPeakDb,
    required_maximum_mean_db: SILENT_VIDEO_PROFILE.maximumSilentIntervalMeanDb,
    pass: true
  };
}

function verifyTransitionAudioTimeline({ ffmpeg, outputPath, outputDirectory, plan }) {
  const samplesPerFrame = audioSamplesPerVideoFrame();
  const transitionSamples = SILENT_VIDEO_PROFILE.transitionFrames * samplesPerFrame;
  return transitionOffsetsFrames(plan).map((offsetFrames, index) => verifyExpectedTimelineRange({
    ffmpeg,
    outputPath,
    outputDirectory,
    plan,
    range: {
      start_sample: offsetFrames * samplesPerFrame,
      end_sample: offsetFrames * samplesPerFrame + transitionSamples
    },
    reason: `transition_${index + 1}`
  }));
}

function permittedSourceAudioRanges(plan) {
  const ranges = [];
  for (let index = 0; index < plan.slides.length; index += 1) {
    const slide = plan.slides[index];
    if (!slide.native_video?.has_source_audio) continue;
    const timing = nativeAudioTiming(plan, index);
    ranges.push({
      start_sample: timing.timeline_start_sample + timing.active_start_sample,
      end_sample: timing.timeline_start_sample + timing.active_end_sample,
      source: slide.native_video.relative_path
    });
  }
  ranges.sort((left, right) => left.start_sample - right.start_sample);
  const merged = [];
  for (const range of ranges) {
    const previous = merged.at(-1);
    if (previous && range.start_sample <= previous.end_sample) {
      previous.end_sample = Math.max(previous.end_sample, range.end_sample);
      previous.sources.push(range.source);
    } else {
      merged.push({ start_sample: range.start_sample, end_sample: range.end_sample, sources: [range.source] });
    }
  }
  return merged;
}

function silentComplementRanges(plan) {
  const samplesPerFrame = audioSamplesPerVideoFrame();
  const totalSamples = plan.total_frames * samplesPerFrame;
  const permitted = permittedSourceAudioRanges(plan).map((range) => ({
    ...range,
    start_sample: clamp(0, totalSamples, range.start_sample),
    end_sample: clamp(0, totalSamples, range.end_sample)
  })).filter((range) => range.end_sample > range.start_sample);
  const complement = [];
  let cursor = 0;
  for (const range of permitted) {
    if (range.start_sample > cursor) complement.push({ start_sample: cursor, end_sample: range.start_sample });
    cursor = Math.max(cursor, range.end_sample);
  }
  if (cursor < totalSamples) complement.push({ start_sample: cursor, end_sample: totalSamples });
  validateDisjointSampleRanges(permitted, totalSamples, '允许原声区间');
  validateDisjointSampleRanges(complement, totalSamples, '静音补集');
  const permittedSamples = sampleRangeTotal(permitted);
  const complementSamples = sampleRangeTotal(complement);
  if (permittedSamples + complementSamples !== totalSamples) {
    throw new Error('允许原声区间与静音补集没有完整覆盖时间轴');
  }
  return { totalSamples, permitted, complement };
}

function sampleRangeTotal(ranges) {
  return ranges.reduce((sum, range) => sum + range.end_sample - range.start_sample, 0);
}

function validateDisjointSampleRanges(ranges, totalSamples, label) {
  let cursor = 0;
  for (const range of ranges) {
    if (!Number.isInteger(range.start_sample) || !Number.isInteger(range.end_sample)
      || range.start_sample < 0 || range.end_sample <= range.start_sample || range.end_sample > totalSamples) {
      throw new Error(`${label}包含无效采样区间`);
    }
    if (range.start_sample < cursor) throw new Error(`${label}存在重叠或未排序区间`);
    cursor = range.end_sample;
  }
}

function mergeSampleRanges(ranges) {
  const sorted = [...ranges].sort((left, right) => left.start_sample - right.start_sample);
  const merged = [];
  for (const range of sorted) {
    if (range.end_sample <= range.start_sample) continue;
    const previous = merged.at(-1);
    if (previous && range.start_sample <= previous.end_sample) {
      previous.end_sample = Math.max(previous.end_sample, range.end_sample);
      previous.boundaries = [...new Set([...(previous.boundaries ?? []), ...(range.boundaries ?? [])])].sort((a, b) => a - b);
    } else {
      merged.push({ ...range, boundaries: [...(range.boundaries ?? [])] });
    }
  }
  return merged;
}

function subtractSampleRanges(baseRanges, removedRanges) {
  const result = [];
  for (const base of baseRanges) {
    let cursor = base.start_sample;
    for (const removed of removedRanges) {
      if (removed.end_sample <= cursor) continue;
      if (removed.start_sample >= base.end_sample) break;
      if (removed.start_sample > cursor) {
        result.push({ start_sample: cursor, end_sample: Math.min(removed.start_sample, base.end_sample) });
      }
      cursor = Math.max(cursor, removed.end_sample);
      if (cursor >= base.end_sample) break;
    }
    if (cursor < base.end_sample) result.push({ start_sample: cursor, end_sample: base.end_sample });
  }
  return result;
}

export function sampleRangeCoveredByUnion(range, coveringRanges) {
  let cursor = range.start_sample;
  for (const covering of [...coveringRanges].sort((left, right) => left.start_sample - right.start_sample)) {
    if (covering.end_sample <= cursor) continue;
    if (covering.start_sample > cursor) return false;
    cursor = Math.max(cursor, covering.end_sample);
    if (cursor >= range.end_sample) return true;
  }
  return cursor >= range.end_sample;
}

function partitionSilentComplement(plan) {
  const ranges = silentComplementRanges(plan);
  const codecSamples = SILENT_VIDEO_PROFILE.audioCodecBoundarySamples;
  const boundaryCandidates = [];
  const boundaryPositions = new Set();
  for (const range of ranges.complement) {
    if (range.start_sample > 0) {
      boundaryPositions.add(range.start_sample);
      boundaryCandidates.push({
        start_sample: range.start_sample,
        end_sample: Math.min(range.end_sample, range.start_sample + codecSamples),
        boundaries: [range.start_sample]
      });
    }
    if (range.end_sample < ranges.totalSamples) {
      boundaryPositions.add(range.end_sample);
      boundaryCandidates.push({
        start_sample: Math.max(range.start_sample, range.end_sample - codecSamples),
        end_sample: range.end_sample,
        boundaries: [range.end_sample]
      });
    }
  }
  const boundaryBands = mergeSampleRanges(boundaryCandidates);
  const strictComplement = subtractSampleRanges(ranges.complement, boundaryBands);
  const boundaryAudits = [...boundaryPositions].sort((left, right) => left - right).map((boundary) => ({
    boundary_sample: boundary,
    start_sample: Math.max(0, boundary - codecSamples),
    end_sample: Math.min(ranges.totalSamples, boundary + codecSamples)
  }));
  validateDisjointSampleRanges(boundaryBands, ranges.totalSamples, 'AAC 边界静音带');
  validateDisjointSampleRanges(strictComplement, ranges.totalSamples, '严格静音区间');
  const complementSamples = sampleRangeTotal(ranges.complement);
  const boundaryBandSamples = sampleRangeTotal(boundaryBands);
  const strictSamples = sampleRangeTotal(strictComplement);
  if (boundaryBandSamples + strictSamples !== complementSamples) {
    throw new Error('严格静音区间与 AAC 边界带没有完整覆盖静音补集');
  }
  if (boundaryBands.some((band) => !sampleRangeCoveredByUnion(band, boundaryAudits))) {
    throw new Error('AAC 边界静音带缺少对应的独立时间轴验收');
  }
  return {
    ...ranges,
    strictComplement,
    boundaryBands,
    boundaryAudits,
    permittedSamples: sampleRangeTotal(ranges.permitted),
    complementSamples,
    boundaryBandSamples,
    strictSamples
  };
}

function strictSilenceCheck({ ffmpeg, outputPath, range }) {
  const volume = measureFinalAudioRange({ ffmpeg, outputPath, range });
  if (volume.peak_value > SILENT_VIDEO_PROFILE.maximumSilentIntervalPeakDb
    || volume.mean_value > SILENT_VIDEO_PROFILE.maximumSilentIntervalMeanDb) {
    throw new Error(`非原声区间出现声音：采样 ${range.start_sample}–${range.end_sample} 的峰值 ${volume.peak_value} dB、均值 ${volume.mean_value} dB`);
  }
  const sampleCount = range.end_sample - range.start_sample;
  return {
    ...range,
    sample_count: sampleCount,
    final_start_seconds: range.start_sample / SILENT_VIDEO_PROFILE.audioSampleRate,
    duration_seconds: sampleCount / SILENT_VIDEO_PROFILE.audioSampleRate,
    verification: 'strict_sample_range_volume',
    peak_db: volume.peak_db,
    mean_db: volume.mean_db,
    required_maximum_peak_db: SILENT_VIDEO_PROFILE.maximumSilentIntervalPeakDb,
    required_maximum_mean_db: SILENT_VIDEO_PROFILE.maximumSilentIntervalMeanDb,
    silent: true
  };
}

function verifySilentIntervals({ ffmpeg, outputPath, outputDirectory, plan }) {
  const ranges = partitionSilentComplement(plan);
  const strictChecks = ranges.strictComplement.map((range) => strictSilenceCheck({ ffmpeg, outputPath, range }));
  const boundaryAudits = ranges.boundaryAudits.map((audit, index) => ({
    boundary_sample: audit.boundary_sample,
    ...verifyExpectedTimelineRange({
      ffmpeg,
      outputPath,
      outputDirectory,
      plan,
      range: audit,
      reason: `source_audio_boundary_${index + 1}`
    })
  }));
  const boundaryChecks = ranges.boundaryBands.map((band) => {
    const audits = boundaryAudits.filter((candidate) => (
      candidate.end_sample > band.start_sample && candidate.start_sample < band.end_sample
    ));
    if (!audits.length || audits.some((audit) => !audit.pass) || !sampleRangeCoveredByUnion(band, audits)) {
      throw new Error('AAC 边界静音带验收缺失');
    }
    const sampleCount = band.end_sample - band.start_sample;
    return {
      ...band,
      sample_count: sampleCount,
      final_start_seconds: band.start_sample / SILENT_VIDEO_PROFILE.audioSampleRate,
      duration_seconds: sampleCount / SILENT_VIDEO_PROFILE.audioSampleRate,
      verification: 'bounded_aac_boundary_expected_timeline',
      audit_reasons: audits.map((audit) => audit.reason),
      codec_boundary_limit_samples: SILENT_VIDEO_PROFILE.audioCodecBoundarySamples,
      expected_silent_complement: true,
      bounded_codec_boundary: true
    };
  });
  const checks = [...strictChecks, ...boundaryChecks].sort((left, right) => left.start_sample - right.start_sample);
  const expectedComplementSamples = ranges.complementSamples;
  const checkedSamples = checks.reduce((sum, check) => sum + check.sample_count, 0);
  const partitionSamples = ranges.permittedSamples + ranges.strictSamples + ranges.boundaryBandSamples;
  if (checkedSamples !== expectedComplementSamples || partitionSamples !== ranges.totalSamples) {
    throw new Error('非原声音频区间验收覆盖不完整');
  }
  return {
    pass: true,
    checked_window_count: checks.length,
    total_timeline_samples: ranges.totalSamples,
    permitted_source_audio_ranges: ranges.permitted,
    permitted_source_audio_samples: ranges.permittedSamples,
    expected_complement_samples: expectedComplementSamples,
    strict_silent_samples: ranges.strictSamples,
    boundary_band_samples: ranges.boundaryBandSamples,
    codec_boundary_limit_samples: SILENT_VIDEO_PROFILE.audioCodecBoundarySamples,
    partition_samples_sum: partitionSamples,
    checked_samples: checkedSamples,
    coverage_complete: checkedSamples === expectedComplementSamples && partitionSamples === ranges.totalSamples,
    boundary_audits: boundaryAudits,
    checks
  };
}

function verifyVideo({ ffmpeg, ffprobe, outputPath, outputDirectory, plan }) {
  const rawProbe = runCommand(ffprobe, [
    '-v', 'error',
    '-show_entries', 'format=duration,size:stream=index,codec_name,codec_type,width,height,pix_fmt,r_frame_rate,nb_frames,duration,sample_rate,channels,channel_layout',
    '-of', 'json',
    outputPath
  ]);
  const probe = JSON.parse(rawProbe);
  const videos = (probe.streams ?? []).filter((stream) => stream.codec_type === 'video');
  const audios = (probe.streams ?? []).filter((stream) => stream.codec_type === 'audio');
  const video = videos[0];
  const audio = audios[0];
  const sourceAudioExpected = plan.source_audio_video_count > 0;
  const problems = [];
  if (videos.length !== 1) problems.push('视频流数量不是 1');
  if (sourceAudioExpected && audios.length !== 1) problems.push('源视频有音轨但最终音频流数量不是 1');
  if (!sourceAudioExpected && audios.length !== 0) problems.push('所有源视频均无音轨但最终出现音频流');
  if (sourceAudioExpected && audio?.codec_name !== 'aac') problems.push('最终原声音轨编码不是 AAC');
  if (sourceAudioExpected && Number(audio?.sample_rate) !== SILENT_VIDEO_PROFILE.audioSampleRate) problems.push('最终原声音轨采样率不是 48000Hz');
  if (sourceAudioExpected && Number(audio?.channels) !== SILENT_VIDEO_PROFILE.audioChannels) problems.push('最终原声音轨不是双声道');
  if (!video || video.codec_name !== 'h264') problems.push('视频编码不是 H.264');
  if (!video || video.width !== 1080 || video.height !== 1440) problems.push('视频尺寸不是 1080×1440');
  if (!video || video.pix_fmt !== 'yuv420p') problems.push('视频像素格式不是 yuv420p');
  if (!video || video.r_frame_rate !== `${SILENT_VIDEO_PROFILE.fps}/1`) problems.push('视频帧率不是 30fps');
  if (!video || Number(video.nb_frames) !== plan.total_frames) problems.push('视频总帧数不匹配');
  const actualDuration = Number(probe.format?.duration);
  if (!Number.isFinite(actualDuration) || Math.abs(actualDuration - plan.duration_seconds) > 0.001) problems.push('视频时长不匹配');
  const actualAudioDuration = finitePositive(audio?.duration);
  if (sourceAudioExpected && (!actualAudioDuration || Math.abs(actualAudioDuration - plan.duration_seconds) > 0.05)) {
    problems.push('最终原声音轨时长与画面时间轴不匹配');
  }
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
  const embeddedNativeVideoAudio = sourceAudioExpected
    ? verifyEmbeddedNativeVideoAudio({ ffmpeg, outputPath, outputDirectory, plan })
    : [];
  const transitionAudioTimeline = sourceAudioExpected
    ? verifyTransitionAudioTimeline({ ffmpeg, outputPath, outputDirectory, plan })
    : [];
  for (const check of embeddedNativeVideoAudio) {
    if (!check.requires_transition_timeline_evidence) continue;
    const evidence = transitionAudioTimeline.filter((transition) => (
      transition.expected_audible
      && transition.start_sample < check.active_timeline_end_sample
      && transition.end_sample > check.active_timeline_start_sample
    ));
    if (!evidence.length) {
      throw new Error(`原声音轨缺少非转场或转场内容证据：${check.relative_path}`);
    }
    check.transition_timeline_evidence = evidence.map((transition) => transition.reason);
  }
  const silentIntervals = sourceAudioExpected
    ? verifySilentIntervals({ ffmpeg, outputPath, outputDirectory, plan })
    : { pass: true, checked_window_count: 0, checks: [] };
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
    source_audio_expected: sourceAudioExpected,
    final_audio_matches_source_presence: sourceAudioExpected ? audios.length === 1 : audios.length === 0,
    audio: sourceAudioExpected ? {
      codec: audio.codec_name,
      sample_rate: Number(audio.sample_rate),
      channels: Number(audio.channels),
      channel_layout: audio.channel_layout ?? null,
      duration_seconds: actualAudioDuration,
      source_audio_video_count: plan.source_audio_video_count,
      timeline_checks: embeddedNativeVideoAudio,
      transition_timeline_checks: transitionAudioTimeline,
      non_source_intervals: silentIntervals,
      all_source_audio_preserved: embeddedNativeVideoAudio.every((check) => check.source_audio_preserved && check.timeline_aligned)
        && transitionAudioTimeline.every((check) => check.pass)
        && silentIntervals.coverage_complete === true
    } : null,
    reading_stability: readingStability,
    native_video: {
      count: plan.native_video_count,
      source_probes: plan.slides.filter((slide) => slide.native_video).map((slide) => slide.native_video.probe),
      embedded_frame_checks: embeddedNativeVideos,
      all_source_videos_decode_pass: plan.slides.filter((slide) => slide.native_video).every((slide) => slide.native_video.probe.decode_pass === true),
      all_visual_durations_preserved: embeddedNativeVideos.every((check) => check.full_visual_duration_preserved),
      source_audio_video_count: plan.source_audio_video_count,
      source_audio_preserved: sourceAudioExpected
        ? embeddedNativeVideoAudio.every((check) => check.source_audio_preserved && check.timeline_aligned)
          && transitionAudioTimeline.every((check) => check.pass)
          && silentIntervals.coverage_complete === true
        : null
    }
  };
}

export function renderVideos({ outputs, templates, outputDirectory, ffmpeg = process.env.YICHEN_X_SLICER_FFMPEG || 'ffmpeg', ffprobe = process.env.YICHEN_X_SLICER_FFPROBE || 'ffprobe' }) {
  assertSilentVideoRuntime({ ffmpeg, ffprobe });
  const provenance = runtimeProvenance({ ffmpeg, ffprobe });
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
      version: 'yichen-x-slicer-video/v3',
      template_id: plan.template_id,
      template_name: plan.template_name,
      file: plan.file,
      sha256: sha256File(outputPath),
      filter_file: plan.filter_file,
      filter_sha256: sha256File(filterPath),
      runtime_provenance: provenance,
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
      tts: false,
      generated_voice: false,
      source_audio_video_count: plan.source_audio_video_count,
      source_audio_preserved: checks.native_video.source_audio_preserved,
      audio: checks.audio,
      checks
    });
  }
  return records;
}

// Backward-compatible export for older callers; behavior now preserves selected source-video audio.
export const renderSilentVideos = renderVideos;
