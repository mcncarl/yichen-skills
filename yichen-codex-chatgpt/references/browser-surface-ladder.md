# ChatGPT Website Control Surface Ladder

Use this reference for every ChatGPT website route. When the current request does not explicitly name a control surface, the default order is:

```text
1. bundled in-app browser (`iab`)
   └─ one bounded same-surface recovery
2. user's Chrome through the installed browser extension
3. Computer Use over the currently visible official ChatGPT UI
4. terminal `BLOCKED` or `ERROR`
```

Fallback changes only the website interaction mechanism. Every surface must independently satisfy Chat/聊天 selected, active `Pro`, Work/工作 absent, intended visible account, and the route's App/Tunnel/protocol/evidence requirements.

This Skill defines a standing non-exclusive multi-surface chain. Invoking the named `yichen-codex-chatgpt` Skill without a current-run surface name opts into `requested_surface: configured_default`. This is an explicit ordered chain—not an exclusive single-browser choice—so its first step explicitly selects `iab` with `agent.browsers.get("iab")`, while its later Chrome and Computer Use steps remain separately authorized by the same Skill policy. Do not use `getForUrl(...)` or `getDefault()` for this route. This configured choice comes from the named Skill policy, not ambient in-app-browser context. A current-run surface name still overrides it.

## Current-Run Surface Override

Apply an explicit current-run surface choice before the default ladder:

- a request that names the in-app browser selects `requested_surface: in_app` and `primary_surface: in_app`; do not try Chrome or Computer Use unless that request also explicitly authorizes fallback;
- a request that names Chrome selects `requested_surface: chrome` and `primary_surface: chrome`; resolve/read `chrome:control-chrome`, obtain the stable Chrome-family binding, read that binding's complete documentation before its first action, and do not probe the in-app browser or Computer Use;
- a request that names Computer Use selects `requested_surface: computer_use` and `primary_surface: computer_use`; resolve and read `computer-use:computer-use` completely before its first action, and do not probe either browser-client surface;
- a request that explicitly states a preference or fallback chain follows exactly that stated order rather than silently appending omitted surfaces; Computer Use may appear only as the final control surface, so pause for clarification rather than silently reordering a chain that places it earlier;
- none of these rules requires the word “only.”

## Default Or In-App Primary Surface

Run this section only when the resolved primary surface is in-app. Skip it for an explicit Chrome or Computer Use primary.

1. Resolve the currently installed `browser:control-in-app-browser` Skill from the runtime catalog and read its `SKILL.md` completely. Do not hard-code its versioned path.
2. Initialize its documented `browser-client` runtime once. Because the named `yichen-codex-chatgpt` Skill explicitly opts into this ordered multi-surface route, obtain or reuse the persistent `iab` binding with `agent.browsers.get("iab")`, read that binding's complete documentation before first use, and obtain a tab from that binding. This is not an exclusive single-browser request; later fallback steps are explicitly authorized by the same configured chain. Do not call `getForUrl(...)` or `getDefault()` for this configured-default route.
3. Reuse the in-app binding and its task tab while they remain trustworthy. A stale or cleaned-up tab requires a fresh tab from the same binding, not a browser switch.
4. Apply the Browser Skill's documented bootstrap troubleshooting and one bounded same-surface recovery before declaring an eligible in-app failure. Do not probe Chrome while the in-app route is healthy.

If a current request explicitly names one surface without also authorizing a fallback, do not switch away from it without new approval.

## Eligible Chrome Fallback

Chrome may be tried once when the in-app surface cannot complete a trustworthy browser exchange because:

- its Skill/runtime/module or persistent binding is unavailable or explicitly disconnected;
- tab creation, recovery, navigation, or documented DOM interaction still fails after bounded same-surface recovery;
- browser control cannot reliably operate or inspect the model selector, composer, conversation DOM, or response controls after bounded recovery;
- after a submitted message, the in-app control surface can no longer observe the conversation following its permitted reload, and Chrome can potentially prove access to that exact conversation without resending. Visible streaming/progress or a merely slow/stuck ChatGPT generation is not a control-surface failure.

Do not activate Chrome merely because the visible session requires login, CAPTCHA, 2FA, account choice, connector authorization, or permission; Pro is proven absent; the private App is proven unavailable; ChatGPT returned an unwanted answer; Web Search found no source; a PLAN/REVIEW was `BLOCKED` or `ERROR`; the Tunnel/workspace is unhealthy; an iteration budget was exhausted; or the user has not authorized the next local mutation. Those are user, capability, task, or protocol outcomes, not browser-surface failures.

## Activate Chrome As Fallback

1. Resolve the installed `chrome:control-chrome` Skill and read its `SKILL.md` completely only when fallback is actually needed. Use the same documented `browser-client` runtime and obtain a persistent Chrome binding with the stable Chrome family selector; do not enumerate opaque browser IDs.
2. Read the Chrome binding's complete documentation before its first action, then obtain a Chrome tab. Do not inspect cookies, local storage, profiles, passwords, or session stores.
3. If Chrome extension setup, installation, or communication is unavailable, first read and follow the Browser runtime's complete `chrome-troubleshooting` documentation. Only after that bounded troubleshooting still fails may the route record the technical failure and continue to Computer Use when the resolved current-run ladder permits it. If no later surface is permitted, record `BLOCKED` and direct the user to **Settings → Computer use**. If Chrome is present but its control channel still fails after documented troubleshooting, continue to Computer Use only when permitted; otherwise record `ERROR`.
4. Re-run the complete visible account, Chat/Pro/Work, and route-specific App/Tunnel precheck in Chrome. Do not assume the in-app account, Pro entitlement, App availability, or conversation state carries over.
5. Attempt Chrome at most once for a website exchange. Do not oscillate between in-app and Chrome.

## Eligible Computer Use Fallback

Computer Use may be tried once only when it is present in the resolved ladder and all earlier permitted browser-client surfaces are unavailable or cannot reliably control the official ChatGPT UI after their documented bounded recovery. Eligible causes include an unavailable Chrome extension, failed browser binding/tab/DOM operations, or inability to operate or inspect the selector, composer, conversation, or response controls through the earlier semantic interfaces.

Computer Use is not triggered by login, CAPTCHA, 2FA, account choice, connector authorization, permission prompts, a proven missing Pro route, a missing private App, Tunnel/workspace failure, unavailable Web Search, an unwanted ChatGPT answer, protocol `BLOCKED`/`ERROR`, iteration exhaustion, or missing mutation authority. A slow or visibly progressing ChatGPT generation is not a control-surface failure. Computer Use must not solve a CAPTCHA, bypass a browser or website safety interstitial, change account/profile, inspect secrets or browser storage, or lower any capability/evidence gate.

## Activate Computer Use As Final Fallback

1. Resolve the installed `computer-use:computer-use` Skill and read its `SKILL.md` completely only when this surface is selected. Use its documented `node_repl` plus `@oai/sky` workflow; do not substitute AppleScript, `osascript`, System Events, CGEvent synthesis, or another GUI automation route.
2. Take over the currently visible official ChatGPT UI in the already intended browser host. For an explicit Computer Use primary with no named host, use the one unambiguous visible official ChatGPT window; if none or multiple accounts/windows are ambiguous, record `BLOCKED`. Prefer fresh accessibility-tree `element_index` actions. Coordinates may only assist opening, focusing, or scrolling when accessibility actions are insufficient; they may not activate Send, prove Chat/Pro/Work gates, or extract a response. Never use screenshot OCR or visual transcription as the authoritative response payload.
3. Call `get_app_state(...)` before acting and again after every state-changing action. Re-derive element indexes every time; never reuse a stale index. Use `disableDiff: true` for every Chat/Pro/Work gate, handoff check, pre-send/post-send proof, and response extraction. Prefer `set_value` or `paste` for multiline protocol messages. Do not use `type_text` with newlines or press `Return` to send.
4. Re-run the complete visible account, Chat/Pro/Work, and route-specific App/Tunnel precheck. If the UI state is ambiguous, record `ERROR`; do not infer entitlement, account, App, or conversation continuity.
5. Prepare the exact outbound message but stop immediately before the send action. Because a Computer Use click or keypress that sends to ChatGPT is representational communication, obtain a fresh action-time confirmation for every research prompt, `INIT`, and `EXECUTED` message even if the user granted broad permission earlier. After confirmation, fetch fresh complete app state and re-verify the entire exact draft, all identifiers, and the Chat/Pro/Work gates. If the user or page already sent the message, do not click again. Any draft, identifier, gate, active conversation, or Send-element change invalidates the old confirmation; do not send, safely re-establish the complete state, and obtain a new action-time confirmation. Send only through one unique, enabled accessibility element whose semantic role/name is the ChatGPT Send action; if only a coordinate target is available, record `ERROR`.
6. Attempt Computer Use once and do not return to an earlier surface. After it is exhausted, apply the terminal boundary below.

## Exactly-Once Handoff

Classify every surface transition before any destination send. Only one surface may remain an active sender:

- **Composer is empty and no send was attempted:** the next permitted surface may open a fresh Chat conversation, preserve the same research/task/message identifiers, populate the same bounded control message once, rerun all pre-send gates, and send exactly once. A Computer Use send still requires its action-time confirmation.
- **An earlier browser-client source contains a draft before a cross-browser handoff and no send was attempted:** clear the source draft and prove through its trustworthy semantic interface that the composer is empty and the exact message ID/marker is absent from the conversation before creating a replacement elsewhere. If clearing or non-submission cannot be proven, do not create a replacement; record `ERROR`.
- **Computer Use takes over the same visible browser UI with an unsent draft:** do not clear, duplicate, or refill it. Fresh complete accessibility state from `disableDiff: true` must prove the entire exact draft and its identifiers. If proof succeeds, rerun all gates and request action-time send confirmation; otherwise record `ERROR`.
- **Computer Use primary encounters an unrelated or incorrect unsent draft:** clearing that GUI draft is deletion and requires its own action-time confirmation. After clearing, fresh complete accessibility state must prove an empty composer and non-submission before the one intended message is populated. The later Send requires a separate action-time confirmation.
- **Submission is uncertain:** do not open a replacement conversation and do not resend. A later surface may inspect only a visibly accessible same conversation. Continue only if the intended visible account and exact `task_id`/research ID, `message_id` when present, and reply marker are all proven in that conversation; otherwise record `ERROR`. Absence from one incomplete accessibility snapshot never proves non-submission.
- **Outbound message was proven submitted:** a later surface may wait, recover, or extract only from the visibly proven same conversation. Finding the exact outbound message forbids resending it. A later `EXECUTED` message under the same task also requires the same conversation; if that continuity cannot be proven, record `ERROR`.

After any Computer Use send click, immediately fetch fresh complete app state with `disableDiff: true` and record `send_action_count: 1`. If the exact outbound message is visible, continue without another send. If the result remains uncertain, inspect only; never click or press a send key again.

For response extraction under Computer Use, call `get_app_state({app, disableDiff: true})` and scope extraction to the latest assistant-response container linked to the exact outbound message. A response may be accepted only when generation/tool activity is visibly stopped, two consecutive fresh complete app states yield the same whole response, every field or requested section required by the active research/C2C protocol is unique and valid, and the exact marker is the final line of that container. Do not search the whole accessibility tree for a marker, combine fragments across messages, invent an undocumented clipboard-read path, or return to an earlier surface for extraction. Screenshots may corroborate state, but screenshot OCR or visual transcription never advances the protocol.

Never copy a full private conversation URL into a prompt, manifest, log, or persisted file. Keep any transient same-conversation locator only in process memory.

## Final Boundary And Evidence

After the final permitted surface is exhausted, do not fall back to Edge, another browser/profile, standalone/generic Playwright, an unofficial wrapper, an API, manual copy/paste, Codex-only reasoning, or implicit `local-only`.

Persist only sanitized routing evidence: `requested_surface: configured_default|in_app|chrome|computer_use|explicit_chain`, `primary_surface`, attempted surface sequence, fallback reason codes, `active_surface`, handoff phase, `send_attempted`, whether a source draft was retained or cleared, outbound visibility, whether same-conversation proof was required/passed, `computer_use_method: ax|coordinates|none`, target app name without profile data, per-message confirmation status/timestamp, send action count, response extraction source, and terminal classification. Full raw accessibility/app-state text remains in process memory only; never write it to `outputs/`, the manifest, a log artifact, or a report. Never persist account identifiers, full private URLs, browser profile paths, connector identifiers, clipboard contents, or credentials.
