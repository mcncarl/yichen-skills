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
  crf: 10,
  minimumAdjacentReadingSsim: 0.9999
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

export function videoFramesForOutput(output) {
  if (output?.kind === 'media') return SILENT_VIDEO_PROFILE.mediaFrames;
  if (output?.kind !== 'text') throw new Error(`视频不支持的帧类型：${String(output?.kind ?? 'missing')}`);
  const calculated = Math.round(21 + 0.157 * String(output.text ?? '').length);
  return clamp(SILENT_VIDEO_PROFILE.minimumTextFrames, SILENT_VIDEO_PROFILE.maximumTextFrames, calculated);
}

export function buildVideoPlan(outputs, template) {
  const slides = outputs
    .filter((output) => output.template_id === template.id)
    .sort((left, right) => left.order - right.order)
    .map((output) => ({
      kind: output.kind,
      png_file: output.png_file,
      frames: videoFramesForOutput(output)
    }));
  if (!slides.length) throw new Error(`模板 ${template.id} 没有可生成视频的图片`);
  const transitionCount = Math.max(0, slides.length - 1);
  const totalFrames = slides.reduce((sum, slide) => sum + slide.frames, 0)
    - transitionCount * SILENT_VIDEO_PROFILE.transitionFrames;
  return {
    template_id: template.id,
    template_name: template.name,
    file: `video-${template.id}-silent.mp4`,
    filter_file: `video-${template.id}-silent-filter.txt`,
    slides,
    transition_count: transitionCount,
    transition_frames: SILENT_VIDEO_PROFILE.transitionFrames,
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
  const stablePairs = [];
  for (let pairIndex = 1; pairIndex < plan.total_frames; pairIndex += 1) {
    if (!transitionPairs.has(pairIndex)) stablePairs.push(pairIndex);
  }
  return {
    transition: [...transitionPairs].sort((left, right) => left - right),
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
  const worst = stablePairs.reduce((current, pair) => pair.all_ssim < current.all_ssim ? pair : current);
  const threshold = SILENT_VIDEO_PROFILE.minimumAdjacentReadingSsim;
  if (!Number.isFinite(worst.all_ssim) || worst.all_ssim < threshold) {
    throw new Error(`阅读区出现画面变化：帧对 ${worst.pair_index} 的 SSIM ${worst.all_ssim} 低于 ${threshold}`);
  }
  return {
    pass: true,
    measured_pair_count: pairs.length,
    stable_pair_count: stablePairs.length,
    transition_pair_count: indices.transition.length,
    minimum_adjacent_reading_ssim: worst.all_ssim,
    required_minimum_ssim: threshold,
    worst_pair_index: worst.pair_index
  };
}

export function buildVideoFilter(plan) {
  const lines = plan.slides.map((slide, index) => (
    `[${index}:v]fps=${SILENT_VIDEO_PROFILE.fps},`
    + `trim=end_frame=${slide.frames},`
    + `settb=expr=1/${SILENT_VIDEO_PROFILE.fps},`
    + 'setpts=N,'
    + 'setsar=1,'
    + `format=yuv420p[v${index}]`
  ));
  if (plan.slides.length === 1) {
    lines[0] = lines[0].replace('[v0]', '[vout]');
  } else {
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
  for (const forbidden of ['zoompan', 'scale=', 'crop=', 'rotate=', 'perspective=', 'pad=']) {
    if (filter.includes(forbidden)) throw new Error(`静音视频滤镜包含禁止的阅读期运动：${forbidden}`);
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
    '-tune', SILENT_VIDEO_PROFILE.tune,
    '-crf', String(SILENT_VIDEO_PROFILE.crf),
    '-g', String(plan.total_frames + 1),
    '-keyint_min', String(plan.total_frames + 1),
    '-sc_threshold', '0',
    '-pix_fmt', 'yuv420p',
    '-movflags', '+faststart',
    outputPath
  ];
}

export function buildFfmpegArgs(plan, outputDirectory, outputPath) {
  const args = ['-nostdin', '-hide_banner', '-loglevel', 'error', '-n'];
  for (const slide of plan.slides) {
    const pngPath = safeOutputPath(outputDirectory, slide.png_file);
    const dimensions = readPngDimensions(pngPath);
    if (dimensions.width !== 1080 || dimensions.height !== 1440) {
      throw new Error(`视频输入尺寸错误：${slide.png_file} 为 ${dimensions.width}×${dimensions.height}`);
    }
    args.push('-loop', '1', '-framerate', String(SILENT_VIDEO_PROFILE.fps), '-i', pngPath);
  }
  args.push(...buildVideoOutputArgs(plan, outputPath));
  return args;
}

function verifyVideo({ ffmpeg, ffprobe, outputPath, plan }) {
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
    reading_stability: readingStability
  };
}

export function renderSilentVideos({ outputs, templates, outputDirectory, ffmpeg = process.env.YICHEN_X_SLICER_FFMPEG || 'ffmpeg', ffprobe = process.env.YICHEN_X_SLICER_FFPROBE || 'ffprobe' }) {
  assertSilentVideoRuntime({ ffmpeg, ffprobe });
  const records = [];
  for (const template of templates) {
    const plan = buildVideoPlan(outputs, template);
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
    const checks = verifyVideo({ ffmpeg, ffprobe, outputPath: partialPath, plan });
    fs.renameSync(partialPath, outputPath);
    records.push({
      version: 'yichen-x-slicer-silent-video/v1',
      template_id: plan.template_id,
      template_name: plan.template_name,
      file: plan.file,
      sha256: sha256File(outputPath),
      filter_file: plan.filter_file,
      filter_sha256: sha256File(filterPath),
      profile: SILENT_VIDEO_PROFILE,
      source_pngs: sourcePngs,
      slide_frames: plan.slides.map((slide) => slide.frames),
      transition_count: plan.transition_count,
      transition_frames: plan.transition_frames,
      total_frames: plan.total_frames,
      duration_seconds: plan.duration_seconds,
      reading_motion: 'none',
      transition_motion_only: true,
      bgm: false,
      voice: false,
      audio: false,
      checks
    });
  }
  return records;
}
