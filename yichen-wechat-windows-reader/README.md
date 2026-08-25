# yichen-wechat-windows-reader

Windows-only, local, read-only analysis for a plaintext Weixin 4.x SQLite snapshot supplied explicitly by the user.

This skill does **not** inspect `Weixin.exe`, read process memory, obtain or store keys, decrypt SQLCipher databases, recover WAL/SHM data, discover the user's WeChat directory, or control the WeChat UI.

## Install and test

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r yichen-wechat-windows-reader\requirements.lock
.\.venv\Scripts\python.exe -m unittest discover -s yichen-wechat-windows-reader\tests -v
```

See [SKILL.md](./SKILL.md) for the snapshot contract and commands. See [REVIEW_EVIDENCE.md](./REVIEW_EVIDENCE.md) for the review checklist and reproducible evidence.
