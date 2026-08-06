---
name: yichen-x-slicer
description: Convert a public X/Twitter Post, Quote Post, or Thread URL into a verified sequence of 1080×1440 Chinese image slices using one of 11 bundled visual templates and a fixed-timing silent slideshow video by default. Use when the user asks to use Yichen X Slicer（逸尘 X 切片）to turn an X link into image cards, tweet slices, a finished silent social video, 3:4 post graphics, or the 落日琥珀版/default style. Ignore quoted content, retain only the selected Post or same-author Thread body and its own media, and never create TTS, audio, Jianying drafts, or publish content.
---

# Yichen X Slicer（逸尘 X 切片）

Turn one public X status URL into a complete 3:4 image sequence. Use `sunset`（落日琥珀版）unless the user explicitly chooses another template.

## Run

1. Resolve the directory containing this `SKILL.md` as `SKILL_DIR`.
2. Choose a new output directory under the current task's user-facing `outputs/` directory. Never overwrite or delete an earlier run.
3. Run. This default command generates the image sequence, image ZIP, and silent MP4:

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

The normal workflow appends one verified silent MP4 per selected template after PNG and ZIP verification. With `--template all`, generate 11 separate videos; never mix templates into one timeline. `--images-only` is an explicit opt-out. Read [video.md](references/video.md) for the fixed timing and verification contract.

## Content contract

- Keep the author header's right-side label visually blank on every frame.
- For a normal Post, include only that Post's own text and media.
- For a Quote Post, include only the focal Post's own text and media; ignore the Quote completely.
- For a Thread, include the verified same-author direct-reply chain and each selected node's own media.
- For a Thread containing Quotes, ignore every Quote. Skip a node that becomes empty after its Quote-only URL is removed and has no own media.
- Exclude other-author replies, side branches, comments, Quote media, and Quote metrics.

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

8. Every MP4 has one 1080×1440 H.264 video stream at 30fps and zero audio streams.
9. The frame count and duration exactly match the fixed `fixed-reading-v1` plan in [video.md](references/video.md).
10. Reading holds are completely static; motion appears only inside each four-frame page transition.
11. The complete MP4 decodes without errors, and manifest/QA hashes match the delivered file.

Return links to `index.html`, `contact-sheet.png`, the final ZIP, and every verified MP4. State the selected template, frame count, routed input type, and any `quote_only` exclusions. Omit the MP4 only for an explicit `--images-only` request.

## Boundaries

- Read only public X data anonymously through FxTwitter; do not use X login state or cookies.
- Accept runtime media only from HTTPS `pbs.twimg.com` or `video.twimg.com`, including every redirect hop. Reject local paths, `file:`/`data:` URLs, oversized responses, wrong MIME types, and non-image signatures.
- Fail closed when a Thread node has an invalid numeric status ID, the focal author identity is missing, or a Quote `t.co` URL cannot be resolved from top-level URL entities.
- Do not operate WeChat, Jianying, or any publishing UI.
- Do not generate TTS, voice, BGM, music, or any audio track.
- Generate the fixed-timing silent video by default. Suppress it only through an explicit `--images-only` request; do not add other video pacing modes or free-form FFmpeg filters.
- Do not delete prior outputs. If a target exists, let the script create a `-run-N` sibling.
