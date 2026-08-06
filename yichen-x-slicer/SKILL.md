---
name: yichen-x-slicer
description: Convert a public X/Twitter Post, Quote Post, or Thread URL into a verified sequence of 1080×1440 Chinese image slices and a finished MP4 using one of 11 bundled visual templates. Native videos attached to selected posts play in full inside their media frame instead of becoming frozen thumbnails and retain their own source audio on the matching page timeline when present; source-silent pages remain silent, and the final MP4 has no audio stream when no selected native video has one. Use when the user asks to use Yichen X Slicer（逸尘 X 切片）to turn an X link into image cards, tweet slices, a finished social video, 3:4 post graphics, or the 落日琥珀版/default style. Ignore quoted content, retain only the selected Post or same-author Thread body and its own media, and never create TTS, voice-over, BGM, music, Jianying drafts, or publish content.
---

# Yichen X Slicer（逸尘 X 切片）

Turn one public X status URL into a complete 3:4 image sequence. Use `sunset`（落日琥珀版）unless the user explicitly chooses another template.

## Run

1. Resolve the directory containing this `SKILL.md` as `SKILL_DIR`.
2. Choose a new output directory under the current task's user-facing `outputs/` directory. Never overwrite or delete an earlier run.
3. Run. This default command generates the image sequence, image ZIP, and MP4:

```bash
"<node-bin>" "$SKILL_DIR/scripts/yichen_x_slicer.mjs" \
  --url "<x-status-url>" \
  --output "<absolute-output-directory>"
```

Use the bundled Codex Node.js executable when available. The script locates bundled Playwright automatically; if discovery fails, set `YICHEN_X_SLICER_PLAYWRIGHT_MODULE` to `<workspace-node-packages>/playwright/index.mjs` after loading workspace dependencies.

The default template is `sunset`. To override it:

```bash
"<node-bin>" "$SKILL_DIR/scripts/yichen_x_slicer.mjs" \
  --url "<x-status-url>" \
  --template editorial \
  --output "<absolute-output-directory>"
```

Use `--template all` only when the user asks to compare every style. Use `--list-templates` to print the registry. Read [templates.md](references/templates.md) only when choosing or explaining a non-default template.

Generate images without a video only when the user explicitly asks for images only:

```bash
"<node-bin>" "$SKILL_DIR/scripts/yichen_x_slicer.mjs" \
  --url "<x-status-url>" \
  --images-only \
  --output "<absolute-output-directory>"
```

The normal workflow appends one verified MP4 per selected template after PNG and ZIP verification. With `--template all`, generate 11 separate videos; never mix templates into one timeline. `--images-only` is an explicit opt-out. Read [video.md](references/video.md) for the fixed timing, source-audio, and verification contract.

## Content contract

- Keep the author header's right-side label visually blank on every frame.
- For a normal Post, include only that Post's own text and media.
- For a Quote Post, include only the focal Post's own text and media; ignore the Quote completely.
- For a Thread, include the verified same-author direct-reply chain and each selected node's own media.
- For a Thread containing Quotes, ignore every Quote. Skip a node that becomes empty after its Quote-only URL is removed and has no own media.
- Exclude other-author replies, side branches, comments, Quote media, and Quote metrics.
- When a selected Post or Thread node has a native video, keep its poster in the PNG/ZIP deliverables but play the complete native video visual inside the same media stage in the final MP4. Never silently substitute the poster for the moving video.
- When that selected native video has a valid source audio stream, retain its own audio over the matching source-video interval on that page and keep it aligned with the source picture. If it has no source audio stream, keep that interval silent. Never include audio from Quote media.

Read [content-routing.md](references/content-routing.md) when diagnosing routing, branches, missing Thread nodes, or `quote_only` exclusions.

## Visual contract

- Fix every final image at 1080×1440（3:4）.
- Keep the complete source slice centered; split long text across consecutive frames instead of shrinking it below the readable limit or cropping it.
- Fit each source image with `contain`; verify the rendered image bounds remain fully inside the media stage.
- Add no visible English outside original text, account handles, and original URLs.
- Outside the source card, keep only one short source-derived hook and up to three verified snapshot metrics: reads, likes, and bookmarks. Omit a metric when the source does not provide it; never turn missing data into zero.
- Use the small source avatar only in the author header; do not reuse it decoratively.

## Verify and deliver

Require all of the following before reporting completion:

1. `qa-report.json` has zero failures.
2. `manifest.json` records the requested template and `sunset` when no template was passed.
3. All PNGs are 1080×1440 and the normalized selected text is completely covered in order.
4. `source-label` is empty and visually zero-sized on every frame.
5. No Quote text, Quote media, or excluded Thread node appears in the outputs.
6. The ZIP contains only numbered final PNGs, and its entries match current PNG hashes.
7. Inspect `contact-sheet.png` visually, then inspect the densest text frame and every media frame at full size.

Unless `--images-only` was explicitly requested, also require:

8. Every MP4 has one 1080×1440 H.264 video stream at 30fps. It has one audio stream if and only if at least one selected non-Quote native video has a valid source audio stream; otherwise it has zero audio streams.
9. The frame count and duration exactly match the `fixed-reading-v1` plan in [video.md](references/video.md), including the complete probed visual duration of every native video page.
10. Text and photo reading holds are completely static; added motion appears only inside each four-frame page transition. Native video pages may contain only their source motion, with no added shake, pan, zoom, crop, or loop.
11. The complete MP4 decodes without errors, and manifest/QA hashes match the delivered file.
12. For every native video page, QA proves that the downloaded MP4 fully decodes, records whether its source has audio, and confirms that transition-free near-start, middle, and near-end source frames match their corresponding embedded frames in the final timeline. For a source-audio page, QA proves the complete transition-free source interval plus every four-frame transition against an independently rebuilt source-audio timeline, and verifies the full sample-accurate complement outside permitted source-audio ranges. For a source-silent page, QA proves that the matching interval is silent. No final audio may appear outside source-audio video-page intervals, and the manifest must bind the artifact to current script/test hashes and FFmpeg/ffprobe versions.

Return links to `index.html`, `contact-sheet.png`, the final ZIP, and every verified MP4. State the selected template, frame count, routed input type, and any `quote_only` exclusions. Omit the MP4 only for an explicit `--images-only` request.

## Boundaries

- Read only public X data anonymously through FxTwitter; do not use X login state or cookies.
- Accept runtime media only from HTTPS `pbs.twimg.com` or `video.twimg.com`, including every redirect hop. Native MP4 downloads must remain on exact host `video.twimg.com`. Reject local paths, `file:`/`data:` URLs, oversized responses, wrong MIME types, non-image signatures, and non-MP4 video signatures.
- Fail closed when a Thread node has an invalid numeric status ID, the focal author identity is missing, or a Quote `t.co` URL cannot be resolved from top-level URL entities.
- Do not operate WeChat, Jianying, or any publishing UI.
- Do not generate or add TTS, voice-over, BGM, or music. The only permitted audio is the original audio carried by a selected non-Quote native video, placed on that video's matching page timeline; do not synthesize an empty audio stream when none of the selected videos has audio.
- Generate the fixed-timing video by default. Suppress it only through an explicit `--images-only` request; do not add other video pacing modes or free-form FFmpeg filters.
- Do not delete prior outputs. If a target exists, let the script create a `-run-N` sibling.
