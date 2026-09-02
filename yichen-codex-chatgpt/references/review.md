# Secure Tunnel Preflight For ChatGPT PLAN And REVIEW

Use for every default `code`, `hybrid`, or local-project `review` route. It exposes one validated project to the user's signed-in ChatGPT Pro through the private read-only App so ChatGPT can architect from real code and independently review Codex's implementation.

## Pure Research Does Not Use The Tunnel

For a task with no local code, follow [research.md](research.md). Do not start, inspect, or attach the code Tunnel, and do not disclose local paths or workspace metadata.

## Fixed Components

- Runtime project: `<CODEX_CHATGPT_RUNTIME_ROOT>`, supplied by the user's private local configuration in [setup.md](setup.md)
- Runtime control: `<CODEX_CHATGPT_RUNTIME_ROOT>/scripts/tunnel-runtime.zsh`
- Workspace validator/launcher: `<CODEX_CHATGPT_RUNTIME_ROOT>/scripts/mcp-workspace-launcher.zsh`
- Private ChatGPT App: `<PRIVATE_CHATGPT_APP_NAME>`; `Codex × ChatGPT Review Loop` is only an example

The public Skill repository does not ship these runtime files. If the runtime root, private App name, or required seven-tool MCP contract is missing, stop at `BLOCKED`; never guess a path, create a public endpoint, or weaken the profile.

This remote MCP profile exposes exactly `workspace_overview`, `list_files`, `search_code`, `read_snippet`, `review_changes`, `verification_report`, and `review_packet`. It has no web-search, write, delete, install, arbitrary-command, commit, push, publish, deployment, or account tool. Never switch the Tunnel to `local-agent`, including for hybrid tasks or after a browser failure.

## 1. Resolve And Confirm One Workspace

Prefer an explicit path. Otherwise, when the current directory is inside a Git worktree, use its Git top level; for a non-Git project use its explicit project root.

Validate the proposed root without changing runtime state:

```bash
"$CODEX_CHATGPT_RUNTIME_ROOT/scripts/mcp-workspace-launcher.zsh" --check-root "<PROJECT_ROOT>"
```

Show the canonical path before exposure. The validator rejects symbolic-link targets, broad roots, sensitive user directories, and directories without a recognized project marker. Do not weaken those checks to make a target pass.

## 2. Reuse Or Stop Safely

Inspect the configured target and runtime state:

```bash
"$CODEX_CHATGPT_RUNTIME_ROOT/scripts/tunnel-runtime.zsh" current
"$CODEX_CHATGPT_RUNTIME_ROOT/scripts/tunnel-runtime.zsh" status
```

- `running_managed`: reuse only when `live_workspace` exactly equals the confirmed target and all three health fields are `true`; then run `health` for a fresh proof.
- `stopped`: select the target if needed, run `doctor`, then start `run` in a visible foreground terminal.
- `running_untracked`, `running_managed_unhealthy`, `running_managed_workspace_mismatch`, `running_managed_state_invalid`, a different target, unknown state, or a foreign listener: stop. Ask the user to press `Ctrl-C` in the original Tunnel terminal. Never call `kill`, `pkill`, silently restart, or rewrite the target underneath a running process.

When an already configured compatible runtime is stopped, show the canonical workspace and ask for explicit confirmation immediately before the first exposure or any rebind. After confirmation, select and validate; this starts the existing runtime and does not provision or publish a new Tunnel:

```bash
"$CODEX_CHATGPT_RUNTIME_ROOT/scripts/tunnel-runtime.zsh" select "<PROJECT_ROOT>"
"$CODEX_CHATGPT_RUNTIME_ROOT/scripts/tunnel-runtime.zsh" doctor
"$CODEX_CHATGPT_RUNTIME_ROOT/scripts/tunnel-runtime.zsh" run
```

`run` stays in the foreground. In another terminal, completion of runtime preflight requires `health`, `ready`, and a successful control-plane poll.

The Runtime Key remains in the operating system's secure credential store, such as macOS Keychain. Never print, copy, log, screenshot, or move it into the Skill, profile, environment files, prompts, or reports.

## 3. Prove Browser And Protocol Readiness

Read [c2c-protocol.md](c2c-protocol.md), [browser-session.md](browser-session.md), and its [browser-surface-ladder.md](browser-surface-ladder.md). Generate one task ID, resolve the current-run requested/primary surface (explicit in-app, Chrome, Computer Use, or an explicit chain when named; otherwise in-app with eligible Chrome and final Computer Use fallbacks), claim the intended signed-in ChatGPT tab/window, open a fresh Chat/聊天 conversation when no message has been sent, automatically select and visibly confirm `Pro`, confirm that no Work/工作 surface is active, confirm that `<PRIVATE_CHATGPT_APP_NAME>` is usable from that Chat Pro conversation, and create the sanitized evidence directory and manifest required by the website-session procedure.

Before sending `INIT`, record that:

- the canonical workspace passed `--check-root`;
- `status` reports `running_managed`, the live workspace exactly matches it, and `health`, `ready`, and control-plane polling all succeed;
- the remote profile is the exact seven-tool read-only set;
- Chat/聊天 is visibly selected, the active model route visibly contains `Pro`, and Work/工作 is absent;
- the intended signed-in account and private App are visibly available;
- account data, credentials, private URLs, full paths, code, diffs, and logs are absent from prompts and screenshots.

While PRECHECK remains open, an eligible technical control failure may advance only through the resolved ladder: in-app, then Chrome, then final Computer Use by default. A Work/工作 surface, Pro proven absent, permission grant, authentication step, ambiguous account, unavailable App, or other user-resolvable mismatch transitions to `BLOCKED` without surface fallback; final-surface control failure, unproven exactly-once handoff, unsafe evidence, or Tunnel integrity failure transitions to `ERROR`. Computer Use must still prove the real private-App tool-call UI state and obey its per-message action-time send confirmation. Neither outcome authorizes a Work, non-Pro Chat, local-only, or API fallback.

## 4. Run PLAN → Codex Execution → REVIEW

Follow [c2c-protocol.md](c2c-protocol.md) as the authoritative message and state contract:

1. `INIT`: send the bounded goal, constraints, acceptance criteria, date when relevant, and workspace basename. Require ChatGPT to begin with `workspace_overview`, inspect through the private App, and return a marker-verified PLAN.
2. `PLAN`: Codex validates material claims and scope. ChatGPT may specify code-level intent, risks, and proposed checks, but cannot write files or claim command execution.
3. `EXECUTING`: Codex alone performs authorized edits and local checks. Do not send implementation evidence through the browser composer.
4. `EXECUTED`: announce only that the current authorized attempt is ready for independent inspection. ChatGPT must obtain the actual diff and verification evidence through `review_changes`, `review_packet`, targeted read tools, and `verification_report`.
5. `REVIEW`: require findings ordered by severity and separated into confirmed defects, uncertainty, and optional improvements. The response must use `state: REVIEW` and one of `outcome: DONE|PLAN|BLOCKED|ERROR`.

`DONE` requires the exact reply marker, visible private-App tool evidence, a complete extracted response, successful final Codex verification, and no remaining material defect. A screenshot by itself is not proof.

Codex may execute iterations 1 and 2 only. `outcome: PLAN` after iteration 1 may drive the bounded second attempt; another requested PLAN after iteration 2 ends the current task as `BLOCKED`. If the user separately authorizes further repair, start a new `task_id` at iteration 1 rather than reviving the terminal task or using iteration 3.

For review-only work, use the separate `review_only` branch: send `INIT` with `expected_next: REVIEW`, let ChatGPT inspect the current project through the seven read-only tools, and accept only a marker-verified `state: REVIEW`. Codex must not request an initial implementation PLAN or enter a mutating execution phase. `outcome: DONE` closes the read-only review; `outcome: PLAN` is only an advisory remediation proposal and becomes local `BLOCKED` until the user separately authorizes a repair task with a new `task_id`.

For implementation, keep PLAN acceptance, edits, verification, REVIEW, commit, push, deployment, and publication as separately reported states.
