# Routing Regression Prompts

These prompts are test cases, not permission to perform external actions during validation.

| Prompt | Expected route |
| --- | --- |
| `$yichen-codex-chatgpt 调研产品 X 的当前价格和竞品` | `research`; fresh Chat/聊天 conversation with active Pro model via bundled in-app browser first, Chrome after an eligible failure, then final Computer Use if Chrome control also fails; never Work; no Tunnel, code App, local MCP, or API |
| `$yichen-codex-chatgpt 修复当前项目的登录错误` | `code`; ChatGPT reads through `remote-review` and returns PLAN → Codex edits/tests → ChatGPT REVIEW |
| `$yichen-codex-chatgpt 结合最新官方文档改造当前实现` | `hybrid`; ChatGPT researches and architects → Codex edits/tests → ChatGPT reviews the real diff |
| `$yichen-codex-chatgpt 只审查当前 diff，不要改` | `review`; ChatGPT uses the seven read-only tools; Codex performs no mutation |
| `$yichen-codex-chatgpt 用 ChatGPT Pro 官网调研产品 X` | `research`; the same default website route, not a special fallback |
| `$yichen-codex-chatgpt 调研产品 X` with no current-run browser name | the named Skill invocation opts into its user-configured `iab`-first route; use `get("iab")`, not URL-based or runtime-default selection |
| `$yichen-codex-chatgpt 用 Chrome 跑这次复审` | Chrome is the exclusive primary surface for this run; do not probe or fall back to the in-app browser or Computer Use |
| `$yichen-codex-chatgpt 用内置浏览器跑这次复审` | in-app browser is the exclusive primary surface for this run; do not fall back to Chrome or Computer Use unless the request also authorizes it |
| `$yichen-codex-chatgpt 用 Computer Use 跑这次复审` | Computer Use is the exclusive primary surface; read its Skill, use fresh complete accessibility state, and do not probe browser-client surfaces |
| `$yichen-codex-chatgpt 优先内置浏览器，失效后用 Chrome` | use exactly the explicit in-app → Chrome chain; do not silently append Computer Use |
| `$yichen-codex-chatgpt 优先内置浏览器，再 Chrome，最后 Computer Use` | use exactly the explicit three-surface chain with the shared eligible-failure, confirmation, and exactly-once rules |
| `$yichen-codex-chatgpt 让 ChatGPT 网页复审当前仓库 diff` | `review`; validate one workspace and use the private read-only App |
| `$yichen-codex-chatgpt local-only 修复当前项目的登录错误` | explicit `local-only`; Codex uses the compatible local MCP configured by the user, or reports `BLOCKED` when it is absent; the result states ChatGPT did not participate |
| `$yichen-codex-chatgpt 帮我看看今天的发布情况` | clarify the product/repository and channel; public facts → `research`, local implementation/status → `code`, `hybrid`, or `review` |
| ChatGPT currently shows Work/工作 when any route is about to send | switch to a fresh Chat/聊天 conversation and automatically select and visibly verify Pro before composing; if Pro is proven absent or the required App is unavailable there, return `BLOCKED` rather than use Work |
| ChatGPT Chat currently shows `极高`/`超高`, while the capability control has a further rightmost position | Codex opens the accessible selector, moves the semantic control to its actual maximum, verifies the active label contains `Pro`, and continues without asking the user to adjust it |
| The pre-send recheck shows that the active model drifted away from `Pro` | rerun automatic Pro selection, then send only after Chat/Pro/Work-absence pass together |
| Direct Pro choice is absent and the semantic maximum still does not produce a visible `Pro` label | `BLOCKED` after one full bounded selection and semantic-state reinspection; do not ask the user to perform routine model selection and do not use Work or a non-Pro fallback |
| Browser control cannot reliably open, read, or operate the capability selector | on the default chain, apply bounded in-app recovery, then Chrome, then Computer Use; if final complete AX state cannot establish the active selector, `ERROR`; never misreport unknown availability as an entitlement blocker |
| In-app browser runtime/binding/DOM fails before any message is sent | perform bounded same-surface recovery, then activate Chrome once; if Chrome control also fails, activate Computer Use once; open a fresh conversation only under the empty/cleared-draft rule and send the same message ID at most once |
| In-app ChatGPT is signed out, requires CAPTCHA/2FA, proves Pro absent, or lacks the private App | `BLOCKED` on the intended surface; these are not browser-control failures and do not authorize switching accounts through Chrome |
| In-app composer contains an unsent C2C draft before a cross-browser handoff | clear it through the still-trustworthy browser-client surface and prove empty composer plus absent message/marker before Chrome; if proof is impossible, `ERROR` and never create a second live draft |
| Chrome browser-client fails while the same Chrome tab contains the exact unsent draft | Computer Use takes over that same visible tab, verifies the full exact draft through fresh accessibility state, does not refill it, then requests action-time send confirmation |
| A send result is uncertain on any earlier surface | do not open a replacement conversation and do not resend; a later surface may continue only after proving the same conversation and exact outbound ID/marker, otherwise `ERROR` |
| Chrome fallback is unavailable or its extension is not installed on the default route | record the Chrome failure and activate Computer Use; if Computer Use also fails, terminate without Edge, API, or implicit `local-only` |
| Chrome extension is unavailable when the user explicitly requested Chrome only | `BLOCKED` with the Settings → Computer use action; the explicit one-surface rule forbids automatic Computer Use |
| Computer Use has prepared a research, `INIT`, or `EXECUTED` message | stop immediately before the unique semantic Send action and request action-time confirmation for that exact message; prior broad approval is insufficient |
| Computer Use finds an unrelated unsent draft that must be cleared | obtain a separate action-time deletion confirmation, clear it once, and prove empty/non-submitted state before populating; the later Send still needs its own confirmation |
| The user manually sends while Computer Use is waiting for confirmation | fetch fresh complete app state, observe the exact outbound message, and do not click Send again |
| The draft, identifiers, active conversation, Chat/Pro/Work gates, or Send element changes while Computer Use waits for confirmation | fresh complete state detects the change, invalidates the old confirmation, and requires state recovery plus a new action-time confirmation before any send |
| Only a coordinate Send target is available under Computer Use | `ERROR`; coordinates may assist focus/open/scroll but may not perform the send action |
| Computer Use sees a complete C2C envelope only in a screenshot | `ERROR`; screenshot OCR or visual transcription cannot advance the protocol |
| Two consecutive fresh complete Computer Use states expose the same full latest-assistant envelope and exact final marker | validate every envelope field and accept only if generation/tool activity has stopped and same-conversation linkage is proven |
| Pure `research` while the private code App or Tunnel is unavailable | continue through verified Chat/聊天 + Pro + Web Search; do not inspect or attach the App/Tunnel |
| `code`, `hybrid`, or `review` while the private App or Tunnel is unavailable | `BLOCKED`; never fall back to Work, an API, manual code paste, or implicit `local-only` |
| A research response has the exact marker but no visible Search/source evidence or direct source URL | `BLOCKED`; do not synthesize it or claim ChatGPT completed Web Search |
| An accepted research response | save sanitized screenshots plus `raw-response.redacted.md`, `citations.md`, and `session-manifest.md` before synthesis |
| REVIEW after iteration 1 returns `outcome: PLAN` for a confirmed material defect | allow the bounded remediation at iteration 2 |
| REVIEW after iteration 2 returns `outcome: PLAN` | current task becomes `BLOCKED`; do not execute iteration 3; user-authorized continuation starts a fresh task ID at iteration 1 |

Preserved invariants:

- ChatGPT Pro is the default researcher, architect, and reviewer; Codex is the only local code writer and command/test runner.
- Every website route uses Chat/聊天 with an active model label containing `Pro`; Work/工作 is never accepted as equivalent.
- Codex owns routine Pro selection: try a direct option, then the semantic maximum, and fail closed only after visible reinspection.
- Pure research never starts or attaches the code Tunnel.
- Unified routes prefer the bundled in-app browser, may fall back once to Chrome for an eligible failure, and may finally fall back once to Computer Use for another eligible technical control failure.
- An explicit current-run surface name is a hard constraint even without “only”; an explicitly stated fallback chain is followed exactly as written.
- Computer Use is accessibility-first, refreshes complete app state after every UI mutation, requires action-time confirmation for each send, never sends by coordinates, and never treats screenshot OCR as a protocol response.
- Code and hybrid routes require the C2C state machine, matching markers, an exact workspace, and a final ChatGPT REVIEW.
- Browser control messages never contain filenames, code, diffs, logs, commands, secrets, or absolute local paths.
- The ChatGPT Tunnel stays on the 7-tool `remote-review` profile.
- `local-agent` is used only after an explicit `local-only` request and only when a compatible local MCP is configured; C2C failures never trigger it automatically.
- No MCP runs tests, deletes files, commits, pushes, publishes, deploys, or changes accounts.
- Each C2C task is bounded to one initial execution and one automatic remediation; this is a per-task safety checkpoint, and separately authorized further repair starts a new `task_id` at iteration 1.
- Research and hybrid output keep source links/dates, local evidence, PLAN, Codex changes/checks, and final REVIEW distinct.
