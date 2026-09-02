# ChatGPT Chat Pro Automatic Selection

Use this procedure for every ChatGPT website route before composing and again immediately before sending. Its required outcome is a fresh Chat/聊天 conversation whose active model control visibly contains `Pro`, with no Work/工作 surface active. Browser-client surfaces inspect DOM/ARIA; Computer Use inspects a fresh complete accessibility state. A `Pro` string elsewhere in a prompt, conversation, sidebar, or account-plan badge does not satisfy the gate.

Routine model selection belongs to Codex. Do not ask the user to click Pro. User action is reserved for genuine user-bound steps such as login, CAPTCHA, 2FA, account choice, connector authorization, or permission grants.

## Semantic Selection Procedure

1. Inspect the current semantic UI state for the Chat/聊天 and Work/工作 selectors, the unique active model or capability control, and its accessible label, value, and ordinal status when exposed. Under Computer Use, call `get_app_state({app, disableDiff: true})` and bind the evidence to the relevant interactive elements rather than searching the whole accessibility tree for words.
2. If Work/工作 is selected, switch to Chat/聊天 and open a fresh conversation before touching the model control.
3. If the active model label already contains `Pro`, record `selection_path: already_pro` and continue.
4. Otherwise open the model or capability selector through its accessible semantic control. Prefer a visible, enabled option whose label contains `Pro`; select it and record `selection_path: direct_option`.
5. If no direct Pro option is exposed, locate the selector's semantic capability control, such as a slider or focusable menu item with `aria-valuenow`/`aria-valuemax`, an accessible item ordinal, or a changing status label. Increase it to the actual maximum through semantic keyboard or DOM interaction:
   - derive the target from `aria-valuemax` or a visible “item N of M” status when available;
   - otherwise move right/increase in a bounded loop, re-reading the semantic value after each step, and stop when the value no longer increases;
   - never assume that one `ArrowRight` is sufficient;
   - on browser-client surfaces, never use screenshot coordinates; under Computer Use, prefer `element_index`, exposed increment actions, or focused semantic keyboard interaction, and use coordinates only to focus/open/scroll when accessibility actions are insufficient—never to activate Send or as proof that Pro is active;
   - cap a metadata-free fallback at 10 increases so UI drift cannot create an unbounded loop.
6. After every state-changing Computer Use action, fetch fresh complete app state and re-derive element indexes. Close the selector if needed and re-read the unique active model control from the current semantic UI. Accept the gate only when that control's visible/accessible label contains `Pro`; reaching a numeric maximum without that label is not enough. Record `selection_path: semantic_max` only after this verification.
7. If the active label still does not contain `Pro`, reopen the selector once and inspect the complete accessible options and terminal status. Repeat a safe direct-option or semantic-maximum selection only when the current semantic UI state proves that it was not already applied. A fully inspectable selector whose terminal position lacks Pro becomes `BLOCKED` on any surface; do not change surfaces merely to seek a different account or entitlement. Unreliable selector control on a non-final surface returns to [browser-surface-ladder.md](browser-surface-ladder.md); on the final permitted surface it becomes `ERROR`. Do not misreport unknown availability as a missing Pro entitlement.

`极高`, `超高`, `High`, `Thinking`, a generic model number, and an account-plan badge do not satisfy the gate. They also do not prove Pro is unavailable: the capability selector can expose Pro only at its rightmost or maximum position.

## Immediate Pre-Send Recheck

Immediately before every research prompt, `INIT`, or `EXECUTED` send:

1. Recheck that Chat/聊天 is selected and no Work/工作 surface is active.
2. Re-read the active model label. If it no longer contains `Pro`, rerun the semantic selection procedure automatically.
3. Do not send until Chat, Pro, and Work-absence all pass in the same fresh semantic inspection. If the composer is already populated, leave its content unchanged while restoring Pro; do not clear, duplicate, or refill it merely to repeat the gate. On the earlier initial gate, do not begin typing until the same three checks pass. Under Computer Use, this gate does not replace the separate action-time confirmation required immediately before the send click.

Persist only sanitized evidence: inspection method (`dom` or `ax`), initial active-control label, selection path, final active-control label, final semantic value or ordinal when visible, pre-send recheck result, and timestamps. Do not persist raw accessibility trees, screenshots containing unrelated history, account identifiers, private conversation URLs, cookies, tokens, or connector identifiers.
