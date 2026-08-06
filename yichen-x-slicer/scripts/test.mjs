#!/usr/bin/env node

import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  DEFAULT_TEMPLATE,
  TEMPLATES,
  deriveHook,
  formatMetric,
  materializeAsset,
  materializeVideoAsset,
  normalizeSourcePayload,
  normalizeText,
  ownMedia,
  parseArgs,
  parseStatusUrl,
  removeQuoteStatusUrl,
  routeThread,
  selectNativeVideoVariant,
  splitText
} from './yichen_x_slicer.mjs';
import {
  VIDEO_PROFILE,
  assertSilentVideoRuntime,
  buildReadingStabilityFilter,
  buildVideoFilter,
  buildVideoOutputArgs,
  buildVideoPlan,
  isNativeVideoOutput,
  parseReadingSsimStats,
  probeNativeVideoSource,
  readingStabilityPairIndices,
  renderVideos,
  sampleRangeCoveredByUnion,
  videoFramesForDuration,
  videoFramesForOutput
} from './silent_video.mjs';

const author = Object.freeze({ id: 'author-1', name: '作者甲', screen_name: 'writer' });
const otherAuthor = Object.freeze({ id: 'author-2', name: '作者乙', screen_name: 'reader' });
const deprecatedPaceLabel = new RegExp([
  ['3', 'x'].join(''),
  ['三', '倍', '速'].join(''),
  ['stable', 'fast'].join('-')
].join('|'), 'iu');
const localFfmpeg = process.env.YICHEN_X_SLICER_FFMPEG || 'ffmpeg';
const localFfprobe = process.env.YICHEN_X_SLICER_FFPROBE || 'ffprobe';
const integrationTemplate = Object.freeze({ id: 'integration', name: 'FFmpeg 集成测试版' });

function runLocalCommand(command, args) {
  const result = spawnSync(command, args, {
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${command} 集成测试命令失败：${String(result.stderr ?? '').trim()}`);
  }
  return result.stdout;
}

function integrationDirectory(label) {
  return fs.mkdtempSync(path.join(os.tmpdir(), `yichen-x-slicer-${label}-`));
}

function writeFixturePng(directory, file, color) {
  const target = path.join(directory, file);
  runLocalCommand(localFfmpeg, [
    '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
    '-f', 'lavfi', '-i', `color=c=${color}:s=1080x1440:r=30:d=0.04`,
    '-frames:v', '1', '-threads', '1', '-c:v', 'png',
    target
  ]);
  return target;
}

function writePositiveOffsetFixture(directory, relativePath) {
  const target = path.join(directory, relativePath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  runLocalCommand(localFfmpeg, [
    '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
    '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=1.8',
    '-itsoffset', '0.6',
    '-f', 'lavfi', '-i', 'sine=frequency=740:sample_rate=48000:duration=0.6',
    '-map', '0:v:0', '-map', '1:a:0',
    '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-b:a', '128k',
    '-t', '1.8', '-avoid_negative_ts', 'disabled', '-movflags', '+faststart',
    target
  ]);
  return target;
}

function writeNegativeOffsetFixture(directory, relativePath) {
  const target = path.join(directory, relativePath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  runLocalCommand(localFfmpeg, [
    '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
    '-itsoffset', '0.3',
    '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=1.5',
    '-f', 'lavfi', '-i', 'sine=frequency=980:sample_rate=48000:duration=1.2',
    '-map', '0:v:0', '-map', '1:a:0',
    '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-b:a', '128k',
    '-t', '1.8', '-avoid_negative_ts', 'disabled', '-movflags', '+faststart',
    target
  ]);
  return target;
}

function writeSilentVideoFixture(directory, relativePath) {
  const target = path.join(directory, relativePath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  runLocalCommand(localFfmpeg, [
    '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
    '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=1',
    '-map', '0:v:0',
    '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p',
    '-an', '-movflags', '+faststart',
    target
  ]);
  return target;
}

function writeTwoAudioTrackFixture(directory, relativePath) {
  const target = path.join(directory, relativePath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  runLocalCommand(localFfmpeg, [
    '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
    '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=1',
    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
    '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000:duration=1',
    '-map', '0:v:0', '-map', '1:a:0', '-map', '2:a:0',
    '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart',
    target
  ]);
  return target;
}

function ffprobeFixture(file) {
  return JSON.parse(runLocalCommand(localFfprobe, [
    '-v', 'error',
    '-show_entries', 'format=duration:stream=index,codec_name,codec_type,start_time,duration,nb_frames,sample_rate,channels',
    '-of', 'json',
    file
  ]));
}

function nativeVideoOutput(order, pngFile, relativePath) {
  return {
    template_id: integrationTemplate.id,
    order,
    kind: 'media',
    png_file: pngFile,
    media: {
      type: 'video',
      native_video_requested: true,
      native_video: { relative_path: relativePath }
    },
    media_layout: { x: 180, y: 500, width: 720, height: 406 }
  };
}

function post(id, text, options = {}) {
  return {
    id: String(id),
    text,
    created_at: options.createdAt ?? `2026-08-05T00:00:${String(Number(id) % 60).padStart(2, '0')}Z`,
    author: options.author ?? author,
    replying_to: options.replyTo ? {
      status: String(options.replyTo),
      screen_name: options.replyHandle ?? 'writer'
    } : null,
    quote: options.quoteId ? {
      id: String(options.quoteId),
      text: options.quoteText ?? '这段引用内容绝不能输出',
      media: { all: [{ id: 'quote-media', type: 'photo', url: 'https://quote.invalid/image.jpg', width: 800, height: 800 }] }
    } : null,
    media: { all: options.media ?? [] },
    views: 12345,
    likes: 88,
    bookmarks: 66
  };
}

function normalizeFixture(focal, thread = [focal]) {
  return normalizeSourcePayload({ status: focal, thread }, String(focal.id));
}

function ids(route) {
  return route.selectedNodes.map(({ node }) => String(node.id));
}

const tests = [];
function test(name, callback) {
  tests.push({ name, callback });
}

test('默认模板为落日琥珀版', () => {
  assert.equal(DEFAULT_TEMPLATE, 'sunset');
  const parsed = parseArgs(['--url', 'https://x.com/writer/status/100', '--output', '/tmp/example']);
  assert.equal(parsed.template, 'sunset');
  assert.equal(parsed.video, true);
});

test('默认追加成片，只有显式 --images-only 才关闭', () => {
  assert.equal(VIDEO_PROFILE.id, 'fixed-reading-v1');
  assert.doesNotMatch(JSON.stringify(VIDEO_PROFILE), deprecatedPaceLabel);
  const parsed = parseArgs(['--url', 'https://x.com/writer/status/100', '--template', 'all']);
  assert.equal(parsed.video, true);
  assert.equal(parsed.template, 'all');
  assert.equal(parseArgs(['--url', 'https://x.com/writer/status/100', '--images-only']).video, false);
  assert.equal(parseArgs(['--url', 'https://x.com/writer/status/100', '--video']).video, true);
  assert.throws(
    () => parseArgs(['--url', 'https://x.com/writer/status/100', '--video', '--images-only']),
    /不能同时使用/u
  );
  const outputs = [
    { template_id: 'sunset', order: 2, kind: 'media', png_file: '02-sunset-media.png' },
    { template_id: 'editorial', order: 1, kind: 'text', text: '乙', png_file: '01-editorial-text.png' },
    { template_id: 'sunset', order: 1, kind: 'text', text: '甲', png_file: '01-sunset-text.png' }
  ];
  const sunsetPlan = buildVideoPlan(outputs, { id: 'sunset', name: '落日琥珀版' });
  const editorialPlan = buildVideoPlan(outputs, { id: 'editorial', name: '暖白编辑版' });
  assert.deepEqual(sunsetPlan.slides.map(({ png_file }) => png_file), ['01-sunset-text.png', '02-sunset-media.png']);
  assert.deepEqual(editorialPlan.slides.map(({ png_file }) => png_file), ['01-editorial-text.png']);
  assert.equal(sunsetPlan.file, 'video-sunset.mp4');
  assert.equal(sunsetPlan.filter_file, 'video-sunset-filter.txt');
  assert.doesNotMatch(JSON.stringify([sunsetPlan.file, sunsetPlan.filter_file]), deprecatedPaceLabel);
});

test('固定阅读节奏帧数公式严格按 JavaScript text.length 计算', () => {
  for (const [length, expected] of [[0, 54], [213, 54], [214, 55], [308, 69], [309, 70], [800, 70]]) {
    assert.equal(videoFramesForOutput({ kind: 'text', text: '字'.repeat(length) }), expected);
  }
  assert.equal(videoFramesForOutput({ kind: 'text', text: '😀'.repeat(107) }), 55);
  assert.equal('😀'.repeat(107).length, 214);
  assert.equal(videoFramesForOutput({ kind: 'media' }), 40);
  assert.throws(() => videoFramesForOutput({ kind: 'quote' }), /不支持的帧类型/u);
  assert.equal(videoFramesForDuration(2620 / 30), 2620);
  assert.equal(videoFramesForDuration(0.066667), 2);
  assert.equal(videoFramesForDuration(1.033333), 31);
  assert.equal(videoFramesForDuration(1.0001), 31);
  assert.equal(sampleRangeCoveredByUnion(
    { start_sample: 1000, end_sample: 2500 },
    [{ start_sample: 500, end_sample: 2000 }, { start_sample: 1500, end_sample: 3000 }]
  ), true);
  assert.equal(sampleRangeCoveredByUnion(
    { start_sample: 1000, end_sample: 2500 },
    [{ start_sample: 500, end_sample: 1499 }, { start_sample: 1500, end_sample: 3000 }]
  ), false);
});

test('九页黄金样本固定为 492 帧与 16.4 秒', () => {
  const lengths = [301, 262, 276, 283, 244, 215, 209, 228];
  const outputs = lengths.map((length, index) => ({
    template_id: 'sunset',
    order: index + 1,
    kind: 'text',
    text: '字'.repeat(length),
    png_file: `${String(index + 1).padStart(2, '0')}-sunset-text.png`
  }));
  outputs.push({ template_id: 'sunset', order: 9, kind: 'media', png_file: '09-sunset-media.png' });
  const plan = buildVideoPlan(outputs, { id: 'sunset', name: '落日琥珀版' });
  assert.deepEqual(plan.slides.map(({ frames }) => frames), [68, 62, 64, 65, 59, 55, 54, 57, 40]);
  assert.equal(plan.slides.reduce((sum, slide) => sum + slide.frames, 0), 524);
  assert.equal(plan.transition_count, 8);
  assert.equal(plan.total_frames, 492);
  assert.equal(plan.duration_seconds, 16.4);
});

test('视频滤镜只在四帧换页窗口运动，阅读期没有几何动画', () => {
  const outputs = [
    { template_id: 'sunset', order: 1, kind: 'text', text: '字'.repeat(301), png_file: '01.png' },
    { template_id: 'sunset', order: 2, kind: 'text', text: '字'.repeat(262), png_file: '02.png' },
    { template_id: 'sunset', order: 3, kind: 'media', png_file: '03.png' }
  ];
  const plan = buildVideoPlan(outputs, { id: 'sunset', name: '落日琥珀版' });
  const filter = buildVideoFilter(plan);
  assert.equal((filter.match(/xfade=/gu) ?? []).length, 2);
  assert.equal((filter.match(/duration=0\.133333/gu) ?? []).length, 2);
  assert.match(filter, /format=yuv420p\[v0\]/u);
  assert.doesNotMatch(filter, /format=yuv420p,\[/u);
  for (const forbidden of ['zoompan', 'scale=', 'crop=', 'rotate=', 'transpose=', 'perspective=', 'pad=']) {
    assert(!filter.includes(forbidden), `不应包含 ${forbidden}`);
  }
  const args = buildVideoOutputArgs(plan, '/tmp/output.mp4');
  assert(args.includes('-an'));
  assert.equal(args[args.indexOf('-frames:v') + 1], String(plan.total_frames));
  assert.equal(args[args.indexOf('-r') + 1], '30');
  assert.equal(args[args.indexOf('-c:v') + 1], 'libx264');
  assert.equal(args[args.indexOf('-g') + 1], String(plan.total_frames + 1));
  assert.equal(args[args.indexOf('-keyint_min') + 1], String(plan.total_frames + 1));
  assert.equal(args[args.indexOf('-sc_threshold') + 1], '0');
});

test('视频 QA 排除转场后逐对检查所有阅读区相邻帧', () => {
  const outputs = [
    { template_id: 'sunset', order: 1, kind: 'text', text: '字'.repeat(301), png_file: '01.png' },
    { template_id: 'sunset', order: 2, kind: 'text', text: '字'.repeat(262), png_file: '02.png' },
    { template_id: 'sunset', order: 3, kind: 'media', png_file: '03.png' }
  ];
  const plan = buildVideoPlan(outputs, { id: 'sunset', name: '落日琥珀版' });
  const indices = readingStabilityPairIndices(plan);
  assert.deepEqual(indices.transition, [65, 66, 67, 68, 123, 124, 125, 126]);
  assert.equal(indices.stable.length + indices.transition.length, plan.total_frames - 1);
  assert.match(buildReadingStabilityFilter(plan), /ssim=stats_file=-/u);
  const stats = Array.from({ length: plan.total_frames - 1 }, (_, index) => (
    `n:${index + 1} Y:1.000000 U:1.000000 V:1.000000 All:${index === 20 ? '0.999950' : '1.000000'} (inf)`
  )).join('\n');
  const audit = parseReadingSsimStats(stats, plan);
  assert.equal(audit.pass, true);
  assert.equal(audit.minimum_adjacent_reading_ssim, 0.99995);
  const failing = stats.replace('n:21 Y:1.000000 U:1.000000 V:1.000000 All:0.999950', 'n:21 Y:1.000000 U:1.000000 V:1.000000 All:0.998000');
  assert.throws(() => parseReadingSsimStats(failing, plan), /阅读区出现画面变化/u);
});

test('原生视频页使用混合输入并完整保留实际视觉帧数', () => {
  const nativeOutput = {
    template_id: 'sunset',
    order: 2,
    kind: 'media',
    png_file: '02-video-poster.png',
    media: {
      type: 'video',
      native_video: { relative_path: 'assets/source.mp4' }
    },
    media_layout: { x: 116, y: 296, width: 848, height: 952 }
  };
  assert.equal(isNativeVideoOutput(nativeOutput), true);
  const outputs = [
    { template_id: 'sunset', order: 1, kind: 'text', text: '字'.repeat(287), png_file: '01-text.png' },
    nativeOutput
  ];
  const probe = {
    decode_pass: true,
    audio_decode_pass: true,
    audio_stream_count: 1,
    audio_streams: [{ codec: 'aac', sample_rate: 48000, channels: 2, duration_seconds: 87.333333, start_time_seconds: 0.7 }],
    video_start_time_seconds: 0.5,
    audio_offset_from_video_seconds: 0.2,
    embedded_frames: 2620,
    source_duration_seconds: 87.333333,
    embedded_duration_seconds: 87.333333
  };
  const plan = buildVideoPlan(outputs, { id: 'sunset', name: '落日琥珀版' }, {
    nativeVideoProbes: new Map([['assets/source.mp4', probe]])
  });
  assert.deepEqual(plan.slides.map(({ frames }) => frames), [66, 2620]);
  assert.equal(plan.total_frames, 2682);
  assert.equal(plan.duration_seconds, 89.4);
  assert.equal(plan.input_count, 3);
  assert.equal(plan.native_video_count, 1);
  assert.equal(plan.source_audio_video_count, 1);
  assert.equal(plan.slides[0].background_input_index, 0);
  assert.equal(plan.slides[1].background_input_index, 1);
  assert.equal(plan.slides[1].native_video_input_index, 2);
  const filter = buildVideoFilter(plan);
  assert.match(filter, /\[2:v\]fps=30/u);
  assert.match(filter, /scale=w=848:h=952:force_original_aspect_ratio=decrease/u);
  assert.match(filter, /overlay=x=116\+\(848-overlay_w\)\/2:y=296\+\(952-overlay_h\)\/2/u);
  assert.match(filter, /\[2:a:0\]asetpts=PTS-\(0\.500000000\/TB\),aresample=48000/u);
  assert.match(filter, /atrim=end_sample=4192000,apad=whole_len=4192000,atrim=end_sample=4192000/u);
  assert.match(filter, /anullsrc=r=48000:cl=stereo/u);
  assert.match(filter, /acrossfade=ns=6400/u);
  assert.match(filter, /\[audio_timeline\]atrim=end_sample=4291200,apad=whole_len=4291200,atrim=end_sample=4291200/u);
  const outputArgs = buildVideoOutputArgs(plan, '/tmp/native-audio.mp4');
  assert(!outputArgs.includes('-an'));
  assert.equal(outputArgs[outputArgs.indexOf('-c:a') + 1], 'aac');
  assert.equal(outputArgs[outputArgs.indexOf('-b:a') + 1], '192k');
  assert(outputArgs.includes('[aout]'));
  const indices = readingStabilityPairIndices(plan);
  assert.equal(indices.transition.length, 4);
  assert.equal(indices.dynamic_native_video.length, 2615);
  assert.equal(indices.stable.length, 62);
  assert.equal(indices.transition.length + indices.dynamic_native_video.length + indices.stable.length, plan.total_frames - 1);
  const stats = Array.from({ length: plan.total_frames - 1 }, (_, index) => (
    `n:${index + 1} Y:1.000000 U:1.000000 V:1.000000 All:1.000000 (inf)`
  )).join('\n');
  const audit = parseReadingSsimStats(stats, plan);
  assert.equal(audit.dynamic_native_video_pair_count, 2615);
  assert.equal(audit.stable_pair_count, 62);
});

test('原生视频没有源音轨时最终不创建空白音轨', () => {
  const output = {
    template_id: 'sunset',
    order: 1,
    kind: 'media',
    png_file: '01-video-poster.png',
    media: { type: 'video', native_video: { relative_path: 'assets/silent-source.mp4' } },
    media_layout: { x: 116, y: 296, width: 848, height: 952 }
  };
  const plan = buildVideoPlan([output], { id: 'sunset', name: '落日琥珀版' }, {
    nativeVideoProbes: new Map([['assets/silent-source.mp4', {
      decode_pass: true,
      audio_decode_pass: true,
      audio_stream_count: 0,
      audio_streams: [],
      embedded_frames: 90,
      source_duration_seconds: 3,
      embedded_duration_seconds: 3
    }]])
  });
  assert.equal(plan.source_audio_video_count, 0);
  assert(!buildVideoFilter(plan).includes('anullsrc='));
  const outputArgs = buildVideoOutputArgs(plan, '/tmp/no-source-audio.mp4');
  assert(outputArgs.includes('-an'));
  assert(!outputArgs.includes('[aout]'));
});

test('多个原生视频的原声按真实输入索引与页面转场拼成一条时间轴', () => {
  const videoOutput = (order, relativePath, pngFile) => ({
    template_id: 'sunset',
    order,
    kind: 'media',
    png_file: pngFile,
    media: { type: 'video', native_video: { relative_path: relativePath } },
    media_layout: { x: 116, y: 296, width: 848, height: 952 }
  });
  const audioProbe = (frames, duration) => ({
    decode_pass: true,
    audio_decode_pass: true,
    audio_stream_count: 1,
    audio_streams: [{ codec: 'aac', sample_rate: 48000, channels: 2, duration_seconds: duration, start_time_seconds: 0 }],
    video_start_time_seconds: 0,
    audio_offset_from_video_seconds: 0,
    embedded_frames: frames,
    source_duration_seconds: duration,
    embedded_duration_seconds: duration
  });
  const outputs = [
    { template_id: 'sunset', order: 1, kind: 'text', text: '正文', png_file: '01-text.png' },
    videoOutput(2, 'assets/first.mp4', '02-video.png'),
    { template_id: 'sunset', order: 3, kind: 'media', png_file: '03-photo.png' },
    videoOutput(4, 'assets/second.mp4', '04-video.png')
  ];
  const plan = buildVideoPlan(outputs, { id: 'sunset', name: '落日琥珀版' }, {
    nativeVideoProbes: new Map([
      ['assets/first.mp4', audioProbe(60, 2)],
      ['assets/second.mp4', audioProbe(90, 3)]
    ])
  });
  assert.deepEqual(plan.slides.map(({ background_input_index, native_video_input_index }) => [background_input_index, native_video_input_index ?? null]), [
    [0, null], [1, 2], [3, null], [4, 5]
  ]);
  assert.equal(plan.input_count, 6);
  assert.equal(plan.source_audio_video_count, 2);
  assert.equal(plan.total_frames, 232);
  const filter = buildVideoFilter(plan);
  assert.match(filter, /\[2:a:0\]asetpts=/u);
  assert.match(filter, /\[5:a:0\]asetpts=/u);
  assert.equal((filter.match(/acrossfade=ns=6400/gu) ?? []).length, 3);
  assert.match(filter, /\[audio_timeline\]atrim=end_sample=371200,apad=whole_len=371200/u);
});

test('真实 FFmpeg 混合时间轴保留正负音画偏移并验证静音前后区间', () => {
  assertSilentVideoRuntime({ ffmpeg: localFfmpeg, ffprobe: localFfprobe });
  const directory = integrationDirectory('mixed-audio-e2e');
  writeFixturePng(directory, '01-static.png', '0x152033');
  writeFixturePng(directory, '02-positive-video.png', '0x573226');
  writeFixturePng(directory, '03-photo.png', '0x244f3c');
  writeFixturePng(directory, '04-negative-video.png', '0x392753');
  writePositiveOffsetFixture(directory, 'assets/positive-audio.mp4');
  writeNegativeOffsetFixture(directory, 'assets/negative-audio.mp4');

  const positiveProbe = probeNativeVideoSource({
    outputDirectory: directory,
    relativePath: 'assets/positive-audio.mp4',
    ffmpeg: localFfmpeg,
    ffprobe: localFfprobe
  });
  const negativeProbe = probeNativeVideoSource({
    outputDirectory: directory,
    relativePath: 'assets/negative-audio.mp4',
    ffmpeg: localFfmpeg,
    ffprobe: localFfprobe
  });
  assert.equal(positiveProbe.video_stream_count, 1);
  assert.equal(positiveProbe.audio_stream_count, 1);
  assert.equal(positiveProbe.decode_pass, true);
  assert.equal(positiveProbe.audio_decode_pass, true);
  assert(positiveProbe.audio_offset_from_video_seconds > 0.5);
  assert(positiveProbe.audio_streams[0].duration_seconds < positiveProbe.source_duration_seconds);
  assert(positiveProbe.audio_offset_from_video_seconds + positiveProbe.audio_streams[0].duration_seconds
    < positiveProbe.source_duration_seconds - 0.5);
  assert.equal(negativeProbe.video_stream_count, 1);
  assert.equal(negativeProbe.audio_stream_count, 1);
  assert.equal(negativeProbe.decode_pass, true);
  assert(negativeProbe.audio_offset_from_video_seconds < -0.25);

  const outputs = [
    {
      template_id: integrationTemplate.id,
      order: 1,
      kind: 'text',
      text: '静态正文',
      png_file: '01-static.png'
    },
    nativeVideoOutput(2, '02-positive-video.png', 'assets/positive-audio.mp4'),
    {
      template_id: integrationTemplate.id,
      order: 3,
      kind: 'media',
      png_file: '03-photo.png',
      media: { type: 'photo' }
    },
    nativeVideoOutput(4, '04-negative-video.png', 'assets/negative-audio.mp4')
  ];
  const [record] = renderVideos({
    outputs,
    templates: [integrationTemplate],
    outputDirectory: directory,
    ffmpeg: localFfmpeg,
    ffprobe: localFfprobe
  });
  assert.deepEqual(record.slide_frames, [54, 54, 40, 45]);
  assert.equal(record.transition_count, 3);
  assert.equal(record.total_frames, 181);
  assert.equal(record.duration_seconds, 181 / 30);
  assert.equal(record.source_audio_video_count, 2);
  assert.equal(record.source_audio_preserved, true);
  assert.equal(record.checks.pass, true);
  assert.equal(record.checks.video_stream_count, 1);
  assert.equal(record.checks.audio_stream_count, 1);
  assert.equal(record.checks.frame_count, record.total_frames);
  assert(Math.abs(record.checks.duration_seconds - record.duration_seconds) < 0.001);
  assert.equal(record.checks.final_audio_matches_source_presence, true);
  assert.equal(record.checks.audio.source_audio_video_count, 2);
  assert.equal(record.checks.audio.all_source_audio_preserved, true);
  assert.equal(record.checks.audio.timeline_checks.length, 2);
  assert.equal(record.checks.audio.transition_timeline_checks.length, 3);
  assert(record.checks.audio.transition_timeline_checks.every((check) => check.pass));
  assert(record.checks.audio.transition_timeline_checks.some((check) => check.expected_audible));
  assert(record.checks.audio.timeline_checks.every((check) => (
    check.pass && check.source_audio_preserved && check.timeline_aligned && check.sample_count >= 1
  )));
  assert.equal(record.checks.native_video.count, 2);
  assert.equal(record.checks.native_video.all_source_videos_decode_pass, true);
  assert.equal(record.checks.native_video.all_visual_durations_preserved, true);
  assert.equal(record.checks.native_video.embedded_frame_checks.length, 2);
  const silenceQa = record.checks.audio.non_source_intervals;
  assert.equal(silenceQa.pass, true);
  assert.equal(silenceQa.coverage_complete, true);
  assert.equal(silenceQa.total_timeline_samples, record.total_frames * 1600);
  assert.equal(silenceQa.checked_samples, silenceQa.expected_complement_samples);
  assert.equal(
    silenceQa.permitted_source_audio_samples + silenceQa.strict_silent_samples + silenceQa.boundary_band_samples,
    silenceQa.total_timeline_samples
  );
  assert(silenceQa.boundary_audits.every((check) => check.pass));
  assert(silenceQa.checks.filter((check) => check.verification === 'bounded_aac_boundary_expected_timeline')
    .every((check) => check.sample_count <= 2 * VIDEO_PROFILE.audioCodecBoundarySamples));
  assert.equal(silenceQa.permitted_source_audio_ranges.length, 2);
  assert(silenceQa.checks.every((check) => check.silent || check.bounded_codec_boundary));
  const positiveRange = silenceQa.permitted_source_audio_ranges.find((range) => (
    range.sources.includes('assets/positive-audio.mp4')
  ));
  const negativeRange = silenceQa.permitted_source_audio_ranges.find((range) => (
    range.sources.includes('assets/negative-audio.mp4')
  ));
  assert(positiveRange.start_sample > 50 * 1600 + 0.5 * 48000);
  assert(positiveRange.end_sample < (50 + 54) * 1600 - 0.5 * 48000);
  assert.equal(negativeRange.start_sample, 136 * 1600);
  assert(negativeRange.end_sample < (136 + 45) * 1600);
  const silenceCoversSample = (sample) => silenceQa.checks.some((check) => (
    check.start_sample <= sample && sample < check.end_sample
  ));
  assert(silenceCoversSample(20 * 1600));
  assert(silenceCoversSample(120 * 1600));
  assert(silenceCoversSample(positiveRange.start_sample - 1));
  assert(silenceCoversSample(positiveRange.end_sample));

  const finalProbe = ffprobeFixture(path.join(directory, record.file));
  assert.equal(finalProbe.streams.filter((stream) => stream.codec_type === 'video').length, 1);
  assert.equal(finalProbe.streams.filter((stream) => stream.codec_type === 'audio').length, 1);
  assert.equal(Number(finalProbe.streams.find((stream) => stream.codec_type === 'video').nb_frames), 181);
  assert(Math.abs(Number(finalProbe.format.duration) - 181 / 30) < 0.01);
  assert.equal(record.runtime_provenance.version, 'yichen-x-slicer-runtime-provenance/v1');
  assert.deepEqual(
    record.runtime_provenance.files.map((entry) => entry.file),
    ['scripts/silent_video.mjs', 'scripts/yichen_x_slicer.mjs', 'scripts/test.mjs', 'SKILL.md']
  );
});

test('真实 FFmpeg 无声源视频生成零音频流并保留完整视觉 QA', () => {
  const directory = integrationDirectory('silent-source-e2e');
  writeFixturePng(directory, '01-silent-video.png', '0x28384d');
  writeSilentVideoFixture(directory, 'assets/silent-source.mp4');
  const sourceProbe = probeNativeVideoSource({
    outputDirectory: directory,
    relativePath: 'assets/silent-source.mp4',
    ffmpeg: localFfmpeg,
    ffprobe: localFfprobe
  });
  assert.equal(sourceProbe.video_stream_count, 1);
  assert.equal(sourceProbe.audio_stream_count, 0);
  assert.equal(sourceProbe.source_audio_present, false);
  assert.deepEqual(sourceProbe.audio_streams, []);
  assert.equal(sourceProbe.embedded_frames, 30);

  const [record] = renderVideos({
    outputs: [nativeVideoOutput(1, '01-silent-video.png', 'assets/silent-source.mp4')],
    templates: [integrationTemplate],
    outputDirectory: directory,
    ffmpeg: localFfmpeg,
    ffprobe: localFfprobe
  });
  assert.equal(record.total_frames, 30);
  assert.equal(record.duration_seconds, 1);
  assert.equal(record.source_audio_video_count, 0);
  assert.equal(record.audio, null);
  assert.equal(record.checks.pass, true);
  assert.equal(record.checks.video_stream_count, 1);
  assert.equal(record.checks.audio_stream_count, 0);
  assert.equal(record.checks.final_audio_matches_source_presence, true);
  assert.equal(record.checks.audio, null);
  assert.equal(record.checks.native_video.count, 1);
  assert.equal(record.checks.native_video.all_source_videos_decode_pass, true);
  assert.equal(record.checks.native_video.all_visual_durations_preserved, true);
  assert.equal(record.checks.native_video.embedded_frame_checks.length, 1);
  const finalProbe = ffprobeFixture(path.join(directory, record.file));
  assert.equal(finalProbe.streams.filter((stream) => stream.codec_type === 'video').length, 1);
  assert.equal(finalProbe.streams.filter((stream) => stream.codec_type === 'audio').length, 0);
  assert.equal(Number(finalProbe.streams.find((stream) => stream.codec_type === 'video').nb_frames), 30);
  assert(Math.abs(Number(finalProbe.format.duration) - 1) < 0.01);
});

test('真实 FFmpeg 双音轨源在探测和渲染入口都 fail closed', () => {
  const directory = integrationDirectory('two-audio-tracks-e2e');
  writeFixturePng(directory, '01-two-audio-tracks.png', '0x4d2525');
  writeTwoAudioTrackFixture(directory, 'assets/two-audio-tracks.mp4');
  const rawProbe = ffprobeFixture(path.join(directory, 'assets/two-audio-tracks.mp4'));
  assert.equal(rawProbe.streams.filter((stream) => stream.codec_type === 'video').length, 1);
  assert.equal(rawProbe.streams.filter((stream) => stream.codec_type === 'audio').length, 2);
  assert.throws(
    () => probeNativeVideoSource({
      outputDirectory: directory,
      relativePath: 'assets/two-audio-tracks.mp4',
      ffmpeg: localFfmpeg,
      ffprobe: localFfprobe
    }),
    /音轨数量超过 1/u
  );
  assert.throws(
    () => renderVideos({
      outputs: [nativeVideoOutput(1, '01-two-audio-tracks.png', 'assets/two-audio-tracks.mp4')],
      templates: [integrationTemplate],
      outputDirectory: directory,
      ffmpeg: localFfmpeg,
      ffprobe: localFfprobe
    }),
    /音轨数量超过 1/u
  );
});

test('单页视频不创建转场，缺少本地视频运行时会 fail closed', () => {
  const plan = buildVideoPlan([
    { template_id: 'sunset', order: 1, kind: 'text', text: '正文', png_file: '01.png' }
  ], { id: 'sunset', name: '落日琥珀版' });
  const filter = buildVideoFilter(plan);
  assert(!filter.includes('xfade='));
  assert(filter.endsWith('[vout]'));
  assert.throws(
    () => assertSilentVideoRuntime({ ffmpeg: '__x_post_missing_ffmpeg__', ffprobe: '__x_post_missing_ffprobe__' }),
    /缺少本地命令/u
  );
});

test('支持 handle 与 i/web 两类 X status 输入链接', () => {
  assert.deepEqual(parseStatusUrl('https://x.com/writer/status/900?s=20'), {
    id: '900', handle: 'writer', canonicalUrl: 'https://x.com/writer/status/900'
  });
  assert.deepEqual(parseStatusUrl('https://x.com/i/web/status/900'), {
    id: '900', handle: null, canonicalUrl: 'https://x.com/i/web/status/900'
  });
  assert.deepEqual(parseStatusUrl('https://twitter.com/i/status/900'), {
    id: '900', handle: null, canonicalUrl: 'https://x.com/i/web/status/900'
  });
});

test('11 套模板完整注册且无重复', () => {
  assert.equal(TEMPLATES.length, 11);
  assert.equal(new Set(TEMPLATES.map(({ id }) => id)).size, 11);
  assert.deepEqual(TEMPLATES.map(({ id }) => id), [
    'sunset', 'editorial', 'data', 'fire', 'yellow', 'mono', 'night', 'ribbon', 'cobalt', 'news', 'minimal'
  ]);
});

test('普通 Post 只选择链接所指本体', () => {
  const root = post(100, '这是一条普通帖子。');
  const route = routeThread(normalizeFixture(root));
  assert.equal(route.resolvedInputType, 'post');
  assert.deepEqual(ids(route), ['100']);
});

test('Quote Post 只保留主贴并删除 Quote 专用链接', () => {
  const root = post(100, '主贴自己的结论。\nhttps://x.com/quoted/status/900?s=20\nhttps://example.com/keep', { quoteId: 900 });
  const route = routeThread(normalizeFixture(root));
  assert.equal(route.resolvedInputType, 'quote_post');
  assert.deepEqual(ids(route), ['100']);
  assert.equal(route.selectedNodes[0].cleanedText, '主贴自己的结论。\n\nhttps://example.com/keep');
  assert(!route.selectedNodes[0].cleanedText.includes('/status/900'));
  assert(route.selectedNodes[0].cleanedText.includes('https://example.com/keep'));
  assert.deepEqual(route.selectedNodes[0].media, []);
  assert.deepEqual(route.audit.ignored_quote_ids, ['900']);
});

test('Quote 缺少显式 ID 时从 URL 补提取，无法提取则 fail closed', () => {
  const withUrl = post(100, '自己的观点。\nhttps://x.com/i/web/status/900');
  withUrl.quote = { url: 'https://x.com/quoted/status/900', text: '引用正文不能输出' };
  const route = routeThread(normalizeFixture(withUrl));
  assert.equal(route.resolvedInputType, 'quote_post');
  assert.equal(route.selectedNodes[0].cleanedText, '自己的观点。');
  assert.deepEqual(route.audit.ignored_quote_ids, ['900']);

  const missing = post(101, '自己的观点。');
  missing.quote = { text: '引用正文不能输出' };
  assert.throws(() => normalizeFixture(missing), (error) => error.code === 'quote_identity_missing');
});

test('Quote 直链变体会精确删除且不吞掉相邻中文', () => {
  for (const url of [
    'https://x.com/i/web/status/900?s=20',
    'https://twitter.com/i/web/status/900#ref',
    'https://mobile.twitter.com/quoted/status/900/photo/1'
  ]) {
    assert.equal(removeQuoteStatusUrl(`我的评论 ${url}。后半句不能丢`, '900'), '我的评论 。后半句不能丢');
  }
});

test('Quote t.co 短链只在实体映射到 Quote 时删除', () => {
  const root = post(100, '主贴观点 https://t.co/quote900\n普通链接 https://t.co/keep', { quoteId: 900 });
  root.entities = { urls: [
    { url: 'https://t.co/quote900', expanded_url: 'https://x.com/i/web/status/900' },
    { url: 'https://t.co/keep', expanded_url: 'https://example.com/keep' }
  ] };
  const route = routeThread(normalizeFixture(root));
  assert.equal(route.selectedNodes[0].cleanedText, '主贴观点\n普通链接 https://t.co/keep');
  const unresolved = post(101, '主贴观点 https://t.co/unknown', { quoteId: 901 });
  assert.throws(() => routeThread(normalizeFixture(unresolved)), (error) => error.code === 'unresolved_quote_short_url');
});

test('Thread 从中间链接向前找根并加载同作者连续链', () => {
  const root = post(100, '第一段。', { createdAt: '2026-08-05T00:00:00Z' });
  const middle = post(101, '第二段。', { replyTo: 100, createdAt: '2026-08-05T00:01:00Z' });
  const end = post(102, '第三段。', { replyTo: 101, createdAt: '2026-08-05T00:02:00Z' });
  const route = routeThread(normalizeFixture(middle, [root, middle, end]));
  assert.equal(route.resolvedInputType, 'thread');
  assert.deepEqual(route.audit.verified_chain_status_ids, ['100', '101', '102']);
  assert.deepEqual(ids(route), ['100', '101', '102']);
  assert.equal(route.audit.thread_root_status_id, '100');
});

test('带 Quote 的 Thread 忽略 Quote 正文和 Quote 媒体但保留自身媒体', () => {
  const root = post(100, '第一段。', { createdAt: '2026-08-05T00:00:00Z' });
  const child = post(101, '第二段自己的文字。\nhttps://twitter.com/quoted/status/900', {
    replyTo: 100,
    createdAt: '2026-08-05T00:01:00Z',
    quoteId: 900,
    media: [{ id: 'own-photo', type: 'photo', url: 'https://pbs.twimg.com/media/own-photo.jpg', width: 10, height: 20 }]
  });
  const route = routeThread(normalizeFixture(root, [root, child]));
  assert.equal(route.resolvedInputType, 'thread_with_quote');
  assert.deepEqual(ids(route), ['100', '101']);
  assert.equal(route.selectedNodes[1].cleanedText, '第二段自己的文字。');
  assert.deepEqual(route.selectedNodes[1].media.map(({ id }) => id), ['own-photo']);
  assert(!JSON.stringify(route.selectedNodes.map(({ cleanedText, media }) => ({ cleanedText, media }))).includes('quote-media'));
});

test('Quote-only Thread 节点在去链接后无正文和自身媒体则跳过', () => {
  const root = post(100, '主贴正文。', { createdAt: '2026-08-05T00:00:00Z' });
  const quoteOnly = post(101, 'https://x.com/quoted/status/900?s=20', {
    replyTo: 100,
    createdAt: '2026-08-05T00:01:00Z',
    quoteId: 900
  });
  const route = routeThread(normalizeFixture(root, [root, quoteOnly]));
  assert.equal(route.resolvedInputType, 'thread_with_quote');
  assert.deepEqual(ids(route), ['100']);
  assert.deepEqual(route.audit.excluded_statuses, [{ id: '101', reason: 'quote_only', ignored_quote_id: '900' }]);
});

test('他人回复不进入 Thread', () => {
  const root = post(100, '主贴正文。', { createdAt: '2026-08-05T00:00:00Z' });
  const otherReply = post(101, '评论内容。', {
    replyTo: 100,
    replyHandle: 'writer',
    author: otherAuthor,
    createdAt: '2026-08-05T00:01:00Z'
  });
  const route = routeThread(normalizeFixture(root, [root, otherReply]));
  assert.equal(route.resolvedInputType, 'post');
  assert.deepEqual(ids(route), ['100']);
  assert.deepEqual(route.audit.excluded_other_author_reply_ids, ['101']);
});

test('回复外部账号的根不扩展为 Thread', () => {
  const focal = post(100, '我对别人的回复。', {
    replyTo: 80,
    replyHandle: 'outsider',
    createdAt: '2026-08-05T00:00:00Z'
  });
  const selfReply = post(101, '继续解释。', { replyTo: 100, createdAt: '2026-08-05T00:01:00Z' });
  const route = routeThread(normalizeFixture(focal, [focal, selfReply]));
  assert.equal(route.resolvedInputType, 'post');
  assert.deepEqual(ids(route), ['100']);
  assert.equal(route.audit.focal_is_external_reply, true);
});

test('同作者 Thread 父节点缺失时报 thread_parent_missing', () => {
  const middle = post(101, '中间一段。', {
    replyTo: 100,
    replyHandle: 'writer',
    createdAt: '2026-08-05T00:01:00Z'
  });
  assert.throws(
    () => routeThread(normalizeFixture(middle, [middle])),
    (error) => error.code === 'thread_parent_missing' && error.parentStatusId === '100'
  );
});

test('同一节点出现多个同作者直接子分支时报错', () => {
  const root = post(100, '主贴正文。', { createdAt: '2026-08-05T00:00:00Z' });
  const childOne = post(101, '分支一。', { replyTo: 100, createdAt: '2026-08-05T00:01:00Z' });
  const childTwo = post(102, '分支二。', { replyTo: 100, createdAt: '2026-08-05T00:02:00Z' });
  assert.throws(
    () => routeThread(normalizeFixture(root, [root, childOne, childTwo])),
    (error) => error.code === 'ambiguous_self_reply_branch' && error.parentStatusId === '100'
  );
});

test('缺失作者身份或非数字帖子 ID 时 fail closed', () => {
  const missingAuthor = post(100, '正文。', { author: {} });
  assert.throws(() => normalizeFixture(missingAuthor), /缺少可核验的作者身份/u);
  const malicious = post('../../../outside', '正文。');
  assert.throws(() => normalizeFixture(malicious), /帖子 ID 不是有效数字 ID/u);
  const unsafeMedia = post(101, '正文。', {
    media: [{ id: 'unsafe', type: 'photo', url: 'file:///etc/passwd', width: 10, height: 10 }]
  });
  assert.throws(() => routeThread(normalizeFixture(unsafeMedia)), /拒绝非白名单/u);
});

test('视频保留封面并选择无需上采样的安全 MP4 供成片完整嵌入', () => {
  const root = post(100, '视频帖子。', {
    media: [{
      id: 'video-1',
      type: 'video',
      url: 'https://video.twimg.com/video/high.mp4',
      thumbnail_url: 'https://pbs.twimg.com/video_thumb/cover.jpg',
      duration: 87.492,
      width: 1920,
      height: 1080,
      format: 'video/mp4',
      formats: [
        { url: 'https://video.twimg.com/video/playlist.m3u8', container: 'm3u8' },
        { url: 'https://video.twimg.com/video/640x360/low.mp4', container: 'mp4', codec: 'h264', bitrate: 832000 },
        { url: 'https://video.twimg.com/video/1280x720/canvas.mp4', container: 'mp4', codec: 'h264', bitrate: 3000000 },
        { url: 'https://video.twimg.com/video/1920x1080/high.mp4', container: 'mp4', codec: 'h264', bitrate: 6000000 },
        { url: 'https://evil.invalid/video/3840x2160/unsafe.mp4', container: 'mp4', codec: 'h264', bitrate: 99999999 }
      ]
    }]
  });
  assert.deepEqual(ownMedia(root), [{
    id: 'video-1',
    type: 'video',
    url: 'https://pbs.twimg.com/video_thumb/cover.jpg',
    poster_url: 'https://pbs.twimg.com/video_thumb/cover.jpg',
    width: null,
    height: null,
    video_url: 'https://video.twimg.com/video/1280x720/canvas.mp4',
    video_duration_seconds: 87.492,
    video_variant: {
      url: 'https://video.twimg.com/video/1280x720/canvas.mp4',
      container: 'mp4',
      codec: 'h264',
      bitrate: 3000000,
      width: 1280,
      height: 720,
      selection: 'canvas_matched_mp4'
    }
  }]);
  assert.equal(selectNativeVideoVariant({
    url: 'file:///etc/passwd',
    format: 'video/mp4',
    formats: [{ url: 'https://video.invalid/a.mp4', container: 'mp4', bitrate: 1 }]
  }), null);
  assert.deepEqual(selectNativeVideoVariant({
    url: 'https://video.twimg.com/video/1080x1920/fallback.mp4',
    format: 'video/mp4',
    width: 1080,
    height: 1920
  }), {
    url: 'https://video.twimg.com/video/1080x1920/fallback.mp4',
    container: 'mp4',
    codec: null,
    bitrate: null,
    width: 1080,
    height: 1920,
    selection: 'validated_top_level_mp4_fallback'
  });
  const missingPoster = post(102, '缺封面视频。', {
    media: [{
      id: 'video-without-poster',
      type: 'video',
      url: 'https://video.twimg.com/video/1280x720/source.mp4',
      format: 'video/mp4'
    }]
  });
  assert.throws(() => ownMedia(missingPoster), /缺少 thumbnail_url；拒绝静默忽略/u);
});

test('长正文按顺序完整拆帧且外围标题来自原文', () => {
  const text = Array.from({ length: 40 }, (_, index) => `第${index + 1}段：这是需要完整保留的正文内容。`).join('\n\n');
  const slices = splitText(text);
  assert(slices.length > 1);
  assert.equal(slices.join(''), text);
  for (const slice of slices) {
    const hook = deriveHook(slice);
    assert(slice.includes(hook));
  }
});

test('无空白切点的连续正文也能逐字完整拆帧', () => {
  for (const text of [
    '中'.repeat(400),
    'a'.repeat(400),
    Array.from({ length: 160 }, (_, index) => `第${index + 1}项。`).join('')
  ]) {
    const slices = splitText(text);
    assert(slices.length > 1);
    assert.equal(slices.join(''), text);
    assert(slices.every((slice) => slice.length <= 370));
  }
});

test('Emoji 字形与密集换行不会被拆坏或挤进单帧', () => {
  const emojiText = '👨‍👩‍👧‍👦'.repeat(371);
  const emojiSlices = splitText(emojiText);
  assert.equal(emojiSlices.join(''), emojiText);
  assert(emojiSlices.every((slice) => !slice.includes('\ufffd')));
  assert(emojiSlices.every((slice) => !slice.endsWith('\u200d')));

  const denseLines = Array.from({ length: 100 }, (_, index) => `第${index + 1}行`).join('\n');
  const denseSlices = splitText(denseLines);
  assert.equal(denseSlices.join(''), denseLines);
  assert(denseSlices.length > 1);
  assert(denseSlices.every((slice) => slice.split('\n').length <= 18));
});

test('缺失指标不伪装成真实零，外部本地素材一律拒绝', async () => {
  assert.equal(formatMetric(undefined, '阅读'), null);
  assert.equal(formatMetric(-1, '赞'), null);
  assert.equal(formatMetric(0, '收藏'), '0收藏');
  await assert.rejects(materializeAsset('/etc/passwd', '/tmp/yichen-x-slicer-never-written.jpg'), /拒绝本地路径/u);
  await assert.rejects(materializeAsset('data:image/png;base64,AA==', '/tmp/yichen-x-slicer-never-written.jpg'), /拒绝本地路径/u);
  await assert.rejects(materializeVideoAsset('/etc/passwd', '/tmp/yichen-x-slicer-never-written.mp4'), /拒绝本地路径/u);
});

let passed = 0;
for (const { name, callback } of tests) {
  try {
    await callback();
    passed += 1;
    process.stdout.write(`通过：${name}\n`);
  } catch (error) {
    process.stderr.write(`失败：${name}\n${error.stack}\n`);
    process.exitCode = 1;
  }
}

if (process.exitCode) {
  process.stderr.write(`测试失败：${tests.length - passed}/${tests.length}\n`);
} else {
  process.stdout.write(`全部通过：${passed}/${tests.length}\n`);
}
