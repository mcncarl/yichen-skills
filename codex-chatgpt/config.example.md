# Local Configuration Example

Copy this template to a private location supported by your agent environment. Do not commit the populated copy. This Markdown file is documentation only: the Skill does not parse it automatically, so the host agent environment must map these values to the placeholders used by the Skill.

```yaml
CODEX_CHATGPT_RUNTIME_ROOT: /absolute/path/to/your/compatible-runtime
PRIVATE_CHATGPT_APP_NAME: Codex × ChatGPT Review Loop
EVIDENCE_ROOT: /absolute/path/outside/source-repositories/codex-chatgpt-evidence
LOCAL_CODE_MCP_NAME: "" # Optional; leave empty to disable local-only mode
```

The Runtime Key, Tunnel ID, connector ID, private URL, account email, browser profile, and target workspace do not belong in this file.
