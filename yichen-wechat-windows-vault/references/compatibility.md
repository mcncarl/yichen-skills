# Windows WeChat Compatibility

## Support Matrix

| Component | Verified support |
|---|---|
| Operating system | Windows 10/11 x64 |
| Account scope | Current user's own logged-in desktop account |
| Database capture | WeChat `4.1.10.53` and `4.1.12.26` |
| Voice | SILK V3 decode plus local faster-whisper `small` CPU transcription, with simplified-Chinese normalization |
| Images | legacy XOR, V1 fixed AES, V2 AES/XOR, and WXGF/HEVC full-resolution decode when the image key is present in WeChat memory |
| Agent surfaces | WorkBuddy MCP (stdio); compatible with any MCP client that supports `command` + `args` + `env` registration |

## Verified Database Profile

| WeChat | Weixin.dll SHA-256 | PBKDF2 RVA | Status |
|---|---|---:|---|
| 4.1.10.53 | `AB35CFBD7AA9514EC0530747CFC59CAE9DEB0DD46D953548D3CF01919C62A577` | `0x68831B0` | Hook boundary identified; every captured key must pass database page HMAC verification |
| 4.1.12.26 | `4914A621A810ECBC0A132B6FF8F612658CFCE323D3989B3E5FE32D4FF343BA46` | `0x561D730` | SQLCipher wrapper matched uniquely against 4.1.10.53; 20/20 local databases passed page-1 HMAC verification |

## Observed Unsupported Builds

| WeChat | Weixin.dll SHA-256 | Status |
|---|---|---|
| 4.1.12.25 | `2E5348D7AEDB911D90B34925CD1CA753EF4833F619B14E739F357789F6A7FFC2` | Detected on Windows x64; PBKDF2 profile not validated, so key capture must hard-stop |

## Unsupported Builds

Do not reuse the RVA from another build. For each new `Weixin.dll`:

1. Record its SHA-256 fingerprint.
2. Locate the exact embedded `PKCS5_PBKDF2_HMAC` function boundary.
3. Record and validate a stable prologue.
4. Capture candidates only on the current user's process.
5. Accept a candidate only after SQLCipher page-1 HMAC verification.
6. Add a separate profile and regression fixture.

An unknown fingerprint is a hard stop, not a warning.

## Coverage Limits

Local coverage includes databases and cached media present under the current account's `xwechat_files` directory. It may exclude deleted, expired, server-only, not-yet-synchronized, or evicted media.

V2 images require a verified image key from the running desktop process. Opening the target image, including “view original” when available, usually loads the required key and file variant into memory/cache. Once decoded, the private cached output can be reused.
