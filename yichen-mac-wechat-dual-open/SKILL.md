---
name: mac-wechat-dual-open
description: |
  Create, inspect, repair, and polish a second WeChat app on macOS.
  Copy WeChat, change the bundle identifier, ad-hoc re-sign, launch the second
  instance, set Chinese language preferences, and recolor only the copied app
  icon from WeChat green to blue. Use when the user asks whether Mac WeChat
  dual-open methods are reliable, asks to double-open WeChat, fix WeChat-2
  language/icon/cache issues, or make the second WeChat visually distinct
  without installing third-party injection tools.
---

# Mac WeChat Dual Open

Create a second WeChat instance on macOS for running two accounts simultaneously.

## Core Method

The underlying mechanism is simple — macOS distinguishes apps by their bundle
identifier. By copying WeChat, changing the copy's bundle ID, and re-signing
it locally, macOS treats the copy as a separate app that can run alongside the
original:

1. Copy `/Applications/WeChat.app` to `~/Applications/WeChat-2.app`.
2. Change the copy's `CFBundleIdentifier` (e.g., to `com.tencent.xin2`).
3. Re-sign the copy with `codesign --force --deep --sign -`.
4. Launch the copy via its executable directly.

No third-party injection tools or modified binaries required.

## Prerequisites

- macOS 12+ with WeChat installed at `/Applications/WeChat.app`
- Python 3.10+ (system python works)
- Pillow (`pip3 install Pillow`) — required only for `recolor-icon`
- Xcode Command Line Tools (`xcode-select --install`) for `codesign`, `iconutil`, `sips`

## Locating the Script

The helper script lives at `scripts/wechat_dual_open.py` relative to this skill
directory. Different agents install skills to different paths. Construct the
script path dynamically:

```bash
# Auto-detect skill directory
SKILL_DIR="$(dirname "$(find ~ -path '*/mac-wechat-dual-open/SKILL.md' -maxdepth 4 2>/dev/null | head -1)")"
SCRIPT="$SKILL_DIR/scripts/wechat_dual_open.py"
```

## Quick Commands

```bash
python3 "$SCRIPT" status          # Check current state
python3 "$SCRIPT" create          # Create the second WeChat
python3 "$SCRIPT" set-language --languages zh-Hans en   # Set Chinese
python3 "$SCRIPT" recolor-icon --blue "#1296db"         # Blue icon
python3 "$SCRIPT" launch          # Start the second instance
python3 "$SCRIPT" repair          # Fix bundle id, signing, language, caches
```

Default paths (override with `--source-app`, `--target-app`, `--bundle-id`):

- Source: `/Applications/WeChat.app`
- Target: `~/Applications/WeChat-2.app`
- Bundle ID: `com.tencent.xin2`

## Workflow

1. **Status first.** Run `status` to see what already exists.
2. **Create.** If no second app exists, run `create`. This copies the app,
   changes the bundle ID, sets Chinese language, removes `CFBundleIconName`,
   re-signs, and registers with Launch Services.
3. **Language.** If the second instance opens in English, run `set-language`,
   then restart it.
4. **Icon.** Run `recolor-icon` to change the WeChat green to a user-chosen
   blue. The script handles both the outer `AppIcon.icns` and the embedded
   `WeChatAppEx.app/.../app.icns`, removes `CFBundleIconName` to avoid stale
   `Assets.car` entries, and sets a Finder custom icon when the Carbon-era
   tools (`DeRez`, `Rez`, `SetFile`) are available.
5. **Launch.** Run `launch`. The second WeChat should appear with its own login
   window. Pin it to the Dock separately from the original.

## Reliability & Tradeoffs

This is **not** an official method. Rate it roughly 6.5–7 / 10 for reliability:

- Works on many macOS + WeChat version combinations.
- No code injection or third-party tweaks — easy to inspect and undo.
- **Breaks after WeChat updates.** Re-run `create` (or `repair`) after
  updating the original WeChat.
- Push notifications may be unreliable (APNs tied to original identity).
- Login state and Keychain are isolated per bundle ID.
- Ad-hoc signing may fail if WeChat adds stricter signature checks.

See `references/reliability-and-risks.md` for the full analysis.

## Icon Pitfalls

WeChat stores icons in multiple locations. The script handles all of them:

| Location | What it affects |
|----------|----------------|
| `Contents/Resources/AppIcon.icns` | Main app icon |
| `Contents/MacOS/WeChatAppEx.app/Contents/Resources/app.icns` | Embedded runtime icon |
| `Contents/Resources/Assets.car` | Asset catalog (handled via `CFBundleIconName` removal) |
| `Icon\r` + Finder custom icon attr | Finder "Applications" view |

If the user reports the icon is still green:
- They may be looking at `/Applications/WeChat.app` (the original), not
  `~/Applications/WeChat-2.app`. Verify with `open -R ~/Applications/WeChat-2.app`.
- Dock caches per-process icons. Quit and relaunch WeChat-2.
- The Finder custom icon step requires `DeRez`/`Rez`/`SetFile` which may not
  exist on macOS 13+. The script skips gracefully — icns replacement is usually
  sufficient.

## Safety

- **Never modify `/Applications/WeChat.app`** — all changes are scoped to the copy.
- Ask before deleting an existing second app. Prefer `repair` over delete/recreate.
- The `codesign` step must run **before** adding a Finder custom icon, otherwise
  macOS rejects the bundle with "resource fork, Finder information, or similar
  detritus not allowed".

## References & Attribution

- Original tutorial by [@koffuxu](https://x.com/koffuxu/status/2043110831584690427)
  (2026-04, blog post: "Mac 微信双开最完美方案")
- Confirmed by [@MinLiBuilds](https://x.com/MinLiBuilds/status/2043121624971678083)
  (2026-04)
- Icon recoloring uses HSV/HLS hue rotation via Pillow.
- Finder custom icon technique uses classic Carbon resource tools (`DeRez`/`Rez`).
