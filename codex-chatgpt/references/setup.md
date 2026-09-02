# Public Setup And Runtime Contract

This repository publishes the orchestration Skill only. It does not include an MCP server, Tunnel client, Runtime Key, private ChatGPT App, browser session, or local workspace configuration.

## Required Capabilities

Before using `code`, `hybrid`, or `review`, configure all of the following locally:

- a supported Codex environment with the in-app browser and, when used, the Chrome and Computer Use Skills named by this Skill;
- an intended signed-in ChatGPT account where Chat/聊天 and a model route visibly labeled `Pro` are available;
- a private ChatGPT App connected through a compatible Secure Tunnel;
- a separate local runtime that can bind one validated project and expose the exact seven-tool `remote-review` profile;
- an evidence directory outside every source repository.

Pure `research` needs only the website-control capabilities. It must not start or inspect the code Tunnel.

## Private Local Configuration

Copy [../config.example.md](../config.example.md) to a private local configuration source supported by your agent environment. Do not commit the populated file. Resolve these placeholders before the first code, hybrid, or review run:

| Placeholder | Meaning |
| --- | --- |
| `<CODEX_CHATGPT_RUNTIME_ROOT>` | Absolute path to the separately installed compatible runtime |
| `<PRIVATE_CHATGPT_APP_NAME>` | Visible name of the user's private ChatGPT App |
| `<EVIDENCE_ROOT>` | Directory outside source repositories for sanitized screenshots and manifests |
| `<LOCAL_CODE_MCP_NAME>` | Optional compatible local-only MCP; leave disabled when absent |

If a required value is absent or ambiguous, report `BLOCKED`. Never discover a Runtime Key, guess a local path, create a public endpoint, or silently broaden a workspace.

## Required Remote MCP Contract

The ChatGPT-facing profile is named `remote-review` in this Skill and exposes exactly:

- `workspace_overview`
- `list_files`
- `search_code`
- `read_snippet`
- `review_changes`
- `verification_report`
- `review_packet`

It must not expose web search, file writes, deletion, arbitrary commands, package installation, commit, push, publishing, deployment, or account operations.

The companion runtime referenced by [review.md](review.md) is expected to provide equivalent read-only operations for:

- validating one canonical project root;
- reading the selected and live workspace;
- reporting managed runtime status, health, readiness, and control-plane polling;
- selecting a validated workspace only after explicit exposure/rebind confirmation;
- running the Tunnel in a visible foreground process.

Names and scripts may differ in another implementation, but the security and state guarantees may not be weakened.

## Optional Local-Only Contract

`local-only` is disabled unless `<LOCAL_CODE_MCP_NAME>` names a compatible locally configured MCP. Its `local-agent` profile may add public search/fetch and bounded preview/apply tools, but it still may not delete, run arbitrary commands, install, commit, push, publish, deploy, or operate accounts. C2C failure never activates this route automatically.

## Secret And Evidence Boundary

- Store Runtime Keys in an operating-system credential store, such as macOS Keychain.
- Never place credentials, Tunnel/App/connector IDs, private URLs, account identifiers, browser storage, or populated local configuration in this repository.
- Keep `<EVIDENCE_ROOT>` outside Git repositories. The included `.gitignore` is a backup guard, not permission to save unsafe evidence.
- This Skill does not provision, register, or publish a new Tunnel. After explicit exposure/rebind confirmation, it may start only an already configured compatible local runtime as described in [review.md](review.md).
