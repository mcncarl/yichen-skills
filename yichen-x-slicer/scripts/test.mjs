#!/usr/bin/env node

import assert from 'node:assert/strict';
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
  SILENT_VIDEO_PROFILE,
  assertSilentVideoRuntime,
  buildReadingStabilityFilter,
  buildVideoFilter,
  buildVideoOutputArgs,
  buildVideoPlan,
  isNativeVideoOutput,
  parseReadingSsimStats,
  readingStabilityPairIndices,
  videoFramesForOutput
} from './silent_video.mjs';

const author = Object.freeze({ id: 'author-1', name: '作者甲', screen_name: 'writer' });
const otherAuthor = Object.freeze({ id: 'author-2', name: '作者乙', screen_name: 'reader' });
const deprecatedPaceLabel = new RegExp([
  ['3', 'x'].join(''),
  ['三', '倍', '速'].join(''),
  ['stable', 'fast'].join('-')
].join('|'), 'iu');

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

test('默认追加静音视频，只有显式 --images-only 才关闭', () => {
  assert.equal(SILENT_VIDEO_PROFILE.id, 'fixed-reading-v1');
  assert.doesNotMatch(JSON.stringify(SILENT_VIDEO_PROFILE), deprecatedPaceLabel);
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
  assert.equal(sunsetPlan.file, 'video-sunset-silent.mp4');
  assert.equal(sunsetPlan.filter_file, 'video-sunset-silent-filter.txt');
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
  assert.equal(plan.slides[0].background_input_index, 0);
  assert.equal(plan.slides[1].background_input_index, 1);
  assert.equal(plan.slides[1].native_video_input_index, 2);
  const filter = buildVideoFilter(plan);
  assert.match(filter, /\[2:v\]fps=30/u);
  assert.match(filter, /scale=w=848:h=952:force_original_aspect_ratio=decrease/u);
  assert.match(filter, /overlay=x=116\+\(848-overlay_w\)\/2:y=296\+\(952-overlay_h\)\/2/u);
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
