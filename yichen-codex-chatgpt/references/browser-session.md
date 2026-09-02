# ChatGPT Pro Website Session

Use this reference whenever a `code`, `hybrid`, or `review` C2C route needs to exchange control messages with the user's signed-in ChatGPT Pro website. Pure `research` follows [research.md](research.md) and does not apply the private-App gate below. The website UI is only the control plane: it starts a ChatGPT turn and retrieves the completed response. Local code, diffs, and verification evidence travel through the private `remote-review` MCP, not through the composer.

Read [c2c-protocol.md](c2c-protocol.md) before starting a browser session.

## Control Surface

1. Read and follow [browser-surface-ladder.md](browser-surface-ladder.md). It owns initial in-app selection, bounded recovery, Chrome activation, final Computer Use activation, action-time confirmation, and exactly-once handoff.
2. On an in-app or Chrome browser-client surface, use that surface's installed Browser Skill, persistent binding, complete runtime documentation, and documented DOM/Playwright interface. On Computer Use, first read `computer-use:computer-use` completely and use its documented `node_repl` plus `@oai/sky` workflow.
3. Keep one task tab or visible app window on the active surface. A pre-send cross-browser fallback may use a fresh conversation only under the ladder's empty/cleared-draft rules; any post-send fallback must visibly prove the same conversation and exact message identifiers before continuing.
4. Computer Use must prefer fresh accessibility element actions. Coordinates may only assist opening, focusing, or scrolling when accessibility data is insufficient; they may not activate Send, prove Chat/Pro/Work gates, or extract a response. Fetch fresh complete app state after every state-changing action. Screenshots are never an authoritative response source.
5. If all surfaces permitted by the current-run policy are exhausted, use the terminal classification from the ladder. Do not substitute an API, a free or unrelated ChatGPT account, another browser/profile, generic Playwright, an unofficial wrapper, or implicit `local-only`.

## Mandatory Chat UI + Pro Precheck

Before composing any hybrid-research prompt, `INIT`, or `EXECUTED` message for a `code`, `hybrid`, or `review` C2C task:

1. At C2C task start, open one fresh ChatGPT conversation rather than reusing a Work conversation. Before later messages under the same `task_id`, reuse that same conversation and rerun the checks below.
2. Inspect the visible interface selector and require Chat/聊天 to be selected. If Work/工作 is selected, switch to Chat before continuing.
3. Run [chat-pro-selection.md](chat-pro-selection.md). If the active model label is not already `Pro`, Codex must try the direct Pro option and then the selector's semantic maximum before treating Pro as unavailable. Do not ask the user to perform routine model selection.
4. Recheck the active semantic UI state immediately before sending: DOM on browser-client surfaces or a fresh complete accessibility state on Computer Use. Rerun automatic Pro selection if the active model drifted, and require the same inspection to show Chat/聊天 selected, an active model label containing `Pro`, and no checked Work/工作 selector, 工作 conversation label, task-progress/subagent work panel, or other visible Work surface.

Do not type or send until all four checks pass. A selector-control or broader control failure on a non-final permitted surface may advance the ladder without terminating PRECHECK. A proven missing Pro route, unavailable private App, authentication screen, or account ambiguity is `BLOCKED` on the current intended surface and does not trigger fallback. Unreliable final-surface control becomes `ERROR`. Never switch to Work to obtain the App. If a message was already sent from Work, stop the visible generation when possible, record the attempt as `ERROR`, and require a new task ID after a fresh Chat Pro precheck.

## Account, App, And Authentication

- Confirm the intended ChatGPT account and the mandatory Chat UI + Pro model route only from visible page labels. Do not inspect cookies, local storage, passwords, browser profiles, session endpoints, or authentication files.
- Before `INIT`, confirm that the private App named by `<PRIVATE_CHATGPT_APP_NAME>` in [setup.md](setup.md) is visibly available in the same account and that the runtime precheck has proven the matching `remote-review` workspace.
- If multiple visible accounts or workspaces remain ambiguous, stop and ask the user to choose.
- Login, CAPTCHA, 2FA, account selection, connector authorization, permission grants, and reauthentication belong to the user. They are not control-surface failures and do not trigger Chrome or Computer Use fallback. Keep the current intended tab open, record `BLOCKED`, and tell the user exactly which visible step must be completed. Resume only after the user says it is ready and visible state confirms it.
- Never display, copy, log, or screenshot a Runtime Key, authorization URL, connector identifier, token, email address, or other account credential.

## Exactly-Once Message Handling

For each `INIT` or `EXECUTED` message, use the envelope defined in [c2c-protocol.md](c2c-protocol.md).

1. Populate the composer through the active semantic interface and verify the exact `task_id`, `iteration`, `message_id`, and `reply_marker` before sending. Browser-client surfaces use DOM controls. Computer Use uses fresh complete accessibility state and `set_value` or `paste`; never use `type_text` with newlines or `Return` to submit.
2. Re-verify Chat/聊天 selected, automatically restore Pro through [chat-pro-selection.md](chat-pro-selection.md) if needed, and require no visible Work surface. Capture sanitized pre-send evidence. If Computer Use will send, stop immediately before the send action and obtain action-time confirmation for this exact `message_id`; after confirmation fetch fresh complete app state with `disableDiff: true` and re-verify the entire exact draft/identifiers, active conversation, every Chat/Pro/Work gate, and the unique semantic Send element. Do not send if the user or page already did. Any required-state change invalidates the old confirmation; re-establish the state and obtain a new action-time confirmation before the one allowed Send click.
3. If the send outcome is uncertain, inspect the same conversation for that exact `message_id` or marker. Never create a second ID or resend merely because the UI is slow, a click timed out, or one accessibility snapshot omits the outbound message.
4. On a browser-client surface, retry an immediate page error at most once, using the same message ID and marker, and only after visible evidence proves the first message was not submitted. Computer Use never performs a second send action after its first Send click, even when the UI action times out or the outbound message is not visible. A repeated or ambiguous failure becomes `ERROR`.
5. While the page exposes a stop control, streaming state, or incomplete tool call, keep waiting. Do not treat partial text as a protocol response.
6. Accept a reply only when generation has stopped, its envelope matches the current task and expected transition, and its final line is the exact requested marker. Ignore stale, mismatched, or already-consumed replies.

Keep each complete control message at or below 2,000 Unicode characters and its body at or below 1,000 characters. Do not split one `INIT` or `EXECUTED` request into multiple turns.

## Waiting And Stuck Pages

- Use bounded waits of at most 30 seconds, re-inspecting visible DOM state or fresh Computer Use app state between waits. While work continues, provide the user a concise status update at least once every 60 seconds.
- Treat a visible stop control, streaming text growth, changing tool status, or another visible generation indicator as progress. Do not resend while any such signal exists.
- If there is no meaningful semantic UI change for 120 seconds, inspect the composer, latest user message, assistant container, and page error state without sending anything. If a streaming/stop indicator is present but unchanged for 180 seconds, treat the page as suspected stuck rather than complete.
- On a suspected stuck page, record a sanitized manifest event and reload the same conversation at most once. After reload, search for the exact `message_id` and marker. If the outbound message exists, never resend it; continue waiting for its response. On a browser-client surface only, if it is visibly absent and pre-send evidence proves it was never submitted, retry once with the same ID and marker. Computer Use never retries after its first Send click.
- If the same page remains stuck but its semantic UI still exposes streaming/progress, treat it as a page/backend timeout under this section; do not change surfaces. Apply the ladder only when the permitted recovery leaves the current non-final control surface unable to observe or operate the same conversation. After submission, any later permitted surface may continue only with visible same-conversation and exact-message proof and may never resend. If handoff proof fails, the outbound state remains ambiguous after recovery, or the submitted request has no trustworthy completed response, transition to `ERROR`. A selected-surface login, CAPTCHA, authorization, or permission screen transitions to `BLOCKED` instead.
- A single ChatGPT turn may wait up to 12 minutes when visible progress continues. Beyond that, pause at `BLOCKED` and ask the user whether to continue waiting; do not loop indefinitely or open a replacement conversation.

## Response Extraction

On browser-client surfaces, prefer the response's visible copy control, then verify the copied text against the current assistant response DOM; if copy is unavailable, extract from that DOM. Under Computer Use, call `get_app_state({app, disableDiff: true})` and scope extraction to the latest assistant-response container linked to the exact outbound message. Accept only when generation and tool activity have visibly stopped, two consecutive fresh complete app states contain the same whole response, and the exact envelope from [c2c-protocol.md](c2c-protocol.md) validates without missing, duplicate, extra, truncated, merged, or ambiguous fields; the exact marker must be that container's final line. Do not search globally, splice across messages, invent an undocumented clipboard-read method, or return to an earlier surface for extraction. Screenshot OCR and visual transcription are never response sources.

Validate the exact extracted response in process memory. The persisted, public-safe record must include:

- a redacted URL reference such as `https://chatgpt.com/c/[redacted]` and capture time, never the full private conversation URL or ID;
- `task_id`, `iteration`, `in_reply_to`, state, and exact reply marker;
- `response_id`, outcome, and `next_iteration`, using `NONE` where required by the protocol;
- extraction method and visible account/App verification status;
- booleans for `chat_ui_checked`, `pro_mode_checked`, and `work_mode_absent`;
- requested, primary, attempted, and active control surfaces; sanitized fallback reasons; handoff phase; same-conversation proof; Computer Use target app and AX/coordinate method; per-message confirmation status; send action count; and response extraction source;
- a sanitized high-level PLAN, REVIEW outcome, or blocker summary that contains no private code, diff, log, secret, or full private path;
- a note that local evidence was obtained through `remote-review`, or an explicit statement that this could not be verified.

For every accepted `PLAN`, and for every `REVIEW` with `outcome: DONE` or `outcome: PLAN` that depends on local evidence, the same current assistant turn must expose actual private-App tool-call status/control evidence. A tool name, `evidence_used` value, or claim appearing only in assistant prose is not proof that `remote-review` ran. `BLOCKED` or `ERROR` may be accepted without a successful tool call when the declared missing App/evidence is itself the validated blocker/error.

Never save the raw response merely to validate it. Full raw accessibility/app-state text remains in process memory only and must not be written to `outputs/`, the manifest, a log artifact, or a report. Never save cookies, tokens, account identifiers, full private ChatGPT URLs, private Tunnel URLs, private code, raw diffs, raw runtime/test logs, or a browser profile path under `outputs/`.

## Screenshot And Completion Evidence

Save browser evidence under `<EVIDENCE_ROOT>/<task_id>/`, using the external evidence root configured in [setup.md](setup.md). Never place these captures inside a source repository. Use ordered names such as:

```text
00-precheck-ready.png
01-init-ready.png
02-init-sent.png
03-plan-complete.png
04-executed-i1-ready.png
05-executed-i1-sent.png
06-review-i1-complete.png
07-executed-i2-ready.png
08-executed-i2-sent.png
09-review-i2-complete.png
10-final-state.png
session-manifest.md
```

Only create iteration-two images when a second execution actually occurs. Record every visible protocol boundary; do not fabricate a screenshot for an action that did not happen.

For review-only mode, use the shared `00-precheck-ready.png`, `01-init-ready.png`, and `02-init-sent.png` boundaries, then `03-review-only-complete.png` and `04-final-state.png` when safe.

Before each capture, crop or temporarily hide unrelated page chrome and verify that the frame contains no account email, avatar menu, conversation sidebar, full private URL, absolute parent path, private code, raw diff, test log, authorization URL, connector ID, or secret. Prefer a tight evidence view or DOM-element screenshot of the relevant composer, response, App status, or completion marker. If a safe frame cannot be produced, do not capture it. Add a sanitized manifest entry naming the boundary, timestamp, reason capture was unsafe, and the safe semantic UI facts observed instead. This manifest substitution is valid evidence and does not by itself prevent `DONE`.

The manifest is the authoritative evidence index. Record timestamps, state transitions, message IDs, response IDs, consumed markers, screenshot filenames or safe manifest substitutions, the workspace basename, boolean Tunnel health results, extraction method, a redacted URL reference, public-safe local verification summary, Git-evidence availability, and final state. Do not place a full private URL, code, diffs, raw logs, secrets, or full private paths in the manifest.

`DONE` requires all of the following:

- the conversation was sent and completed in Chat/聊天 with the active model route visibly labeled `Pro`, with no Work/工作 surface used;
- the final ChatGPT response is visibly complete and its marker validates;
- visible private-App tool-call evidence in the current assistant turn establishes that ChatGPT inspected the current `remote-review` workspace, and the response record lists the tools actually used; a tool name appearing only in assistant prose is not tool-call evidence;
- Codex's project-local verification succeeded for the final implementation;
- the final review reports no remaining material defect;
- the sanitized public-safe response and manifest were saved, with a safe screenshot or a manifest substitution for each required visible boundary.

Anything less must be reported as `BLOCKED`, `ERROR`, or an unfinished `PLAN`; never describe it as a completed ChatGPT review loop.
