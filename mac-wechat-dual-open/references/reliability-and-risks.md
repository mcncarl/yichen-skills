# Reliability And Risks

Use this when judging public Mac WeChat dual-open tutorials or explaining
tradeoffs to users.

## Common Tutorial Pattern

Most reliable-looking posts use this core method:

```bash
cp -R /Applications/WeChat.app ~/Applications/WeChat-2.app
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.tencent.xin2" \
  ~/Applications/WeChat-2.app/Contents/Info.plist
codesign --force --deep --sign - ~/Applications/WeChat-2.app
nohup ~/Applications/WeChat-2.app/Contents/MacOS/WeChat >/dev/null 2>&1 &
```

Using `~/Applications` avoids `sudo` and keeps the copy user-owned. Launching
the executable directly is more reliable than `open -n` because WeChat
detects and blocks normal multi-instance launching.

## Verdict

Rate this approach roughly **6.5/10 to 7/10**:

- Works in practice on many macOS + WeChat versions.
- Does not inject code or install third-party tweaks.
- Easy to inspect and undo.
- **Not guaranteed** across WeChat or macOS updates.

## Known Tradeoffs

- **Updates break the copy.** After updating the original WeChat, re-run the
  create/repair steps: recopy, reapply bundle ID, re-sign, relaunch.
- **Push notifications may be unreliable** because APNs and entitlements are
  tied to the original app identity.
- **Login state and Keychain are isolated** by bundle ID.
- **`codesign --force --deep --sign -`** replaces the vendor signature with an
  ad-hoc signature. Acceptable for local use but can fail if WeChat adds
  stricter signature checks.
- **Version-locking is fragile.** Tutorials that require downgrading or
  pinning a specific WeChat version miss security updates and are less
  future-proof.
- **Third-party tweak/injection tools** are higher risk than this
  copy-and-sign method.
- **"Comment to receive script" posts** on social media are unnecessary — the
  underlying operations are just a few simple commands.

## Recommended Response

When a user asks whether a social media tutorial is reliable:

1. The mechanism is real: macOS and app data containers distinguish apps by
   bundle ID.
2. It is not official and not permanent.
3. Prefer doing the steps manually or with a local audited script.
4. Avoid downgrading unless the current version fails.
5. Avoid third-party injection tools unless the user explicitly accepts that
   risk.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Second WeChat opens in English | New bundle ID has no language preference | `defaults write com.tencent.xin2 AppleLanguages -array zh-Hans en`, then restart |
| "已损坏/无法打开" | Gatekeeper blocks unsigned app | System Settings → Privacy & Security → Still Open |
| "应用程序版本过低" | Account logged into wrong instance first | Quit both → log into original first → then start copy |
| Finder/Dock still shows green icon | Icon caches not refreshed | See SKILL.md Icon Pitfalls section |
| WeChat-2 disappears after update | Original WeChat updated, copy is stale | Re-run `create` or `repair` |
