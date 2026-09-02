# ChatGPT-Architected Code Mode

Use when the request depends on the current workspace and does not require current external research. ChatGPT Pro architects and reviews; Codex alone edits files and runs commands/tests.

## Default C2C Procedure

1. Read [review.md](review.md), confirm one exact workspace, and prove the managed Secure Tunnel is bound to that workspace with the seven-tool `remote-review` profile.
2. Read [browser-session.md](browser-session.md) and [c2c-protocol.md](c2c-protocol.md). Complete `PRECHECK`, then send the protocol `INIT` control message to the verified ChatGPT Pro tab.
3. Require ChatGPT to begin with `workspace_overview`, inspect the smallest relevant code through the private App, and return a scoped `PLAN` with acceptance criteria, file-level intent, risks, and proposed verification. The browser message carries only task/state identifiers and the workspace basename; ChatGPT obtains code through the MCP.
4. Validate the PLAN against the user's request and local evidence. If it is unsafe, speculative, out of scope, or relies on unavailable evidence, return a bounded correction request or report `BLOCKED`; never execute it blindly.
5. Enter `EXECUTING`. Codex performs all authorized edits with its native local file tools and runs proportionate project-local tests, builds, type checks, or linters. ChatGPT and the Tunnel never write or run commands.
6. Send `EXECUTED` with only the protocol identifiers and the statement that the current authorized attempt is ready for review. Do not paste filenames, code, diff, logs, commands, absolute paths, or secrets. Ask ChatGPT to retrieve the actual diff and verification evidence using `review_changes`, `verification_report`, or `review_packet`.
7. Accept `DONE` only after a marker-verified `state: REVIEW` with `outcome: DONE` finds no material remaining issue. `outcome: PLAN` after iteration 1 may start the bounded second execution. Another requested PLAN after iteration 2 ends the current task as `BLOCKED`; separately authorized further repair starts a new `task_id` at iteration 1.

For a review-only request, set `mode: review_only`, send `INIT` with `expected_next: REVIEW`, and require the protocol's marker-verified `state: REVIEW` response. Do not request an initial implementation PLAN and never enter `EXECUTING`. Return findings first, ordered by severity. If ChatGPT returns `outcome: PLAN`, report that remediation as `BLOCKED` pending separately authorized repair work; the read-only request itself grants no mutation authority.

## Ownership And Evidence

- ChatGPT owns architecture, PLAN, and REVIEW. It may suggest code shapes, but it cannot claim to have changed files, executed commands, or passed tests.
- Codex owns the actual implementation, local commands, test interpretation, and final status report. It must verify ChatGPT's material claims rather than treating them as authority.
- The remote MCP is the source for ChatGPT's workspace evidence. `verification_report` is advisory evidence about recorded/local state; it does not prove that ChatGPT or the MCP executed tests.
- Keep one task ID and enforce every iteration, message ID, reply marker, and replay check from the C2C protocol. Never execute the same PLAN twice.

## Explicit `local-only` Mode

Use this section only when the user explicitly requests `local-only` or no ChatGPT. Do not enter it merely because one or all permitted website control surfaces failed.

1. Resolve the compatible local-only MCP named in the user's private configuration from [setup.md](setup.md), enter its `local-agent` mode, and begin with `workspace_overview`. If no compatible server is configured, report `BLOCKED`.
2. Inspect with `list_files`, `search_code`, `read_snippet`, `review_changes`, `verification_report`, and `review_packet` as needed.
3. For an authorized edit, call `preview_file_change` for one exact text file. Inspect the complete preview, target path, proposed SHA-256, and expiry; plans over 20,000 preview characters must be split rather than truncated.
4. Apply only through `apply_file_change` with the returned `changeId`, `path` as `expectedPath`, and `proposedSha256` as `expectedProposedSha256`, subject to the Codex write approval gate.
5. Re-read the change and run tests through Codex's native project tools. The MCP has no arbitrary command tool.

The local profile cannot delete, rename, install, commit, push, publish, deploy, or operate accounts. Keep one workspace and one text-file plan at a time; do not use absolute paths, traversal, symlinks, blocked secrets, binary data, or files over fixed limits. State explicitly in the result that ChatGPT Pro did not participate.

## Boundaries

- The ChatGPT-facing Tunnel stays `remote-review`; never expose the four local-only tools through it.
- A failed Tunnel, final permitted website exchange, marker, or App call blocks or errors the default route. The default surface ladder is in-app browser → Chrome extension → final Computer Use; after it is exhausted, do not auto-fallback to `local-only`, an API, or manual transfer.
- A review-only request remains read-only. Implementation does not authorize deletion, commit, push, deployment, publication, or account operations.
- Do not weaken workspace, secret, symlink, size, or approval checks to make an operation pass.

## Deliverable

Report the accepted ChatGPT PLAN, files Codex actually changed, exact checks Codex actually ran, and the final marker-verified ChatGPT REVIEW verdict. Distinguish implementation, verification, review, commit, push, deployment, and publication. If `local-only` was explicitly used, identify that exception and do not attribute any work to ChatGPT.
