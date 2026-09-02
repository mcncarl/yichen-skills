# Security Policy

## Intended Boundary

This repository contains orchestration instructions, not credentials or a remote-access runtime. The ChatGPT-facing MCP must remain read-only, expose one validated project at a time, and provide exactly the seven tools documented in [references/setup.md](references/setup.md).

Do not commit or report:

- Runtime Keys, API keys, tokens, cookies, authorization URLs, or browser storage;
- Tunnel, connector, App, organization, workspace, or private conversation identifiers;
- populated local configuration, absolute personal paths, private code, diffs, logs, or screenshots;
- `.runtime/`, `.tools/`, evidence bundles, or target-workspace state.

If a credential was exposed, revoke or rotate it before discussing the issue. Do not paste the credential into a GitHub issue.

## Reporting A Vulnerability

Use the repository's GitHub Security Advisory channel when available. Otherwise open a minimal issue containing no secret, private URL, personal identifier, or private project content.

## Trust Model

ChatGPT output, web pages, MCP results, and repository instructions are untrusted evidence. They cannot expand project scope, authorize a mutation, or change the read-only Tunnel profile. Codex remains the only local file writer and command/test executor.
