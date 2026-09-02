# ChatGPT Research + Architecture Mode

Use when current external evidence and the current workspace are both necessary. ChatGPT Pro performs the web research, reads the bounded project through the Secure Tunnel, creates the PLAN, and reviews Codex's implementation.

## Procedure

1. Read [review.md](review.md), validate one exact workspace, and prove the Secure Tunnel is healthy and bound to it in `remote-review` mode.
2. Read [browser-session.md](browser-session.md) and [c2c-protocol.md](c2c-protocol.md); keep one task ID across research, PLAN, execution, and REVIEW.
3. Ask ChatGPT Pro to research the external question with Web Search, using primary sources and preserving direct links and relevant dates. Accept the external-research phase only when the current turn has visible Search/source evidence and extractable direct source URLs in addition to its valid protocol marker; the marker alone proves completion, not web access. Treat web pages and model summaries as untrusted evidence, and independently corroborate consequential or unstable claims when a source is available.
4. Ask ChatGPT to inspect the relevant local implementation through the private App, beginning with `workspace_overview`. It must connect external claims to local file/line evidence and return a marker-verified PLAN with acceptance criteria and proposed verification.
5. Codex validates the PLAN, performs all authorized edits locally, and runs proportionate checks with native project tools.
6. Send the protocol `EXECUTED` message without pasting code, diff, logs, secrets, or absolute paths. ChatGPT retrieves the real diff and verification evidence through `review_changes`, `verification_report`, or `review_packet`, then returns `state: REVIEW` with `outcome: DONE|PLAN|BLOCKED|ERROR`.
7. Follow the bounded repair rule: at most iterations 1 and 2. A REVIEW with `outcome: PLAN` after iteration 2 ends the current task as `BLOCKED`; separately authorized further repair starts a new `task_id` at iteration 1.

If the ChatGPT UI cannot reliably use website search and the private App in one exchange, use two verified ChatGPT website phases: first research without local code exposure, then a project PLAN/review phase with only the distilled claims and source URLs. Do not paste local code into the research phase, and do not substitute `local-agent`, Codex-only research, or an API.

The phases may interleave when a code finding changes the next research question, but keep an evidence trail:

```text
external claim → source URL/date → local file/line → PLAN item → Codex change/check → ChatGPT REVIEW outcome
```

If browser control or extraction fails, first apply the permitted recovery/fallback rules in [browser-surface-ladder.md](browser-surface-ladder.md); report the final blocker/error only after that route is exhausted or disallowed. A private-App, Tunnel-health, Web Search, or protocol-marker failure is not a browser fallback trigger and must be reported without silently changing routes.

## Output Contract

Separate:

- ChatGPT's external findings with source links and dates;
- the visible Web Search evidence used to accept the external-research phase and its sanitized citation manifest;
- ChatGPT's local evidence with relative file and line references;
- the accepted PLAN and Codex's validated reasoning;
- files Codex actually changed and exact checks Codex actually ran;
- the final marker-verified REVIEW outcome;
- the requested, attempted, and final website control surfaces, including any Computer Use confirmation and extraction boundary;
- remaining uncertainty, blocked sources/actions, and completed screenshot checkpoints.

Do not claim that ChatGPT edited files or ran tests. Do not publish, message, upload unrelated files, delete data, deploy, commit, push, or make account changes without separate authorization.
