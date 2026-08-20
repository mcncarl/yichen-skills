# Windows compatibility profiles

Key capture is supported only when every profile check succeeds.

| WeChat version | Weixin.dll SHA-256 | PBKDF2 RVA | Required prologue |
|---|---|---:|---|
| 4.1.10.53 | `AB35CFBD7AA9514EC0530747CFC59CAE9DEB0DD46D953548D3CF01919C62A577` | `0x68831B0` | `40535556574154415541564157B898000000E82955F4FF482BE0488B052FD197` |

The runtime table is `scripts/profiles.json`. The profile pins the complete DLL hash and the bytes at the target RVA. A matching version label alone is insufficient.

## Adding a version

Do not guess or copy an offset from another build. For each new DLL:

1. record the complete SHA-256 and file version;
2. independently identify the PBKDF2 function within that exact PE image;
3. record at least 16 bytes of its prologue;
4. validate captured 32-byte outputs against multiple encrypted database first-page HMACs;
5. add a synthetic regression and document the derivation evidence;
6. keep unknown builds fail-closed until review is complete.

The current profile was derived independently from PE metadata, embedded OpenSSL source references, x64 calling convention, and the OpenSSL PBKDF2 control flow. It was not obtained from an older Windows implementation.
