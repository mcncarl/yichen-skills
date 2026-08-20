# Privacy and operational boundaries

- Work only with the current user's account and explicit local paths.
- Source databases are read-only. Snapshot before decryption.
- Keep `keys.dpapi`, `manifest.json`, decrypted databases, query state, and exports under a private local directory.
- DPAPI protects keys for the current Windows user; it does not make exported plaintext chat data safe to share.
- Never paste keys into command-line arguments, environment variables, logs, issues, commits, or pull requests.
- Never commit real databases, messages, contacts, account identifiers, media, exports, or personal absolute paths.
- Key capture is on-demand and finite. Never install a watcher, service, scheduled task, or persistent hook.
- If a capture reports zero verified databases, report that outcome and retry only when normal WeChat activity can cause the required database derivation.
- This Skill indexes media metadata only. It does not decode image files, transcribe voice, or recover server-only content.
