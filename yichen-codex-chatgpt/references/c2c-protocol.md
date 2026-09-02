# Codex ↔ ChatGPT C2C Protocol

This protocol makes ChatGPT Pro the architect and reviewer while Codex remains the only code writer and command runner.

```text
ChatGPT Pro: research when needed, inspect through remote-review, produce PLAN, review the implemented state
Codex: validate the PLAN, edit local files, run checks, and apply one remediation PLAN when needed
Website control ladder: exchange short control messages and completed responses through in-app, Chrome, or final Computer Use
Secure Tunnel + remote-review MCP: give ChatGPT bounded, read-only access to the true workspace state
```

The browser composer is never a substitute for the MCP. Do not paste code, diffs, patches, test logs, secrets, full local paths, or Tunnel details into ChatGPT.

## Fixed State Machine

```text
build:
PRECHECK → INIT → PLAN → EXECUTING → EXECUTED → REVIEW
                                                   ├─ DONE
                                                   ├─ PLAN → EXECUTING (next authorized iteration)
                                                   ├─ BLOCKED
                                                   └─ ERROR

review_only:
PRECHECK → INIT → REVIEW
                    ├─ DONE
                    ├─ BLOCKED (including a proposed remediation PLAN)
                    └─ ERROR
```

State meanings:

| State | Owner | Meaning |
| --- | --- | --- |
| `PRECHECK` | Codex | Prove the single workspace, Tunnel health, permitted website-control ladder and active surface, Chat/聊天 selected, active Pro model route, intended account, and private App before disclosure. |
| `INIT` | Codex → ChatGPT | Send one bounded task request and ask ChatGPT to inspect the real workspace and return the mode-appropriate PLAN or REVIEW. |
| `PLAN` | ChatGPT | Provide an evidence-based architecture or remediation plan. The first accepted PLAN is iteration 1. |
| `EXECUTING` | Codex | Verify the plan, make only authorized local changes, and run project-local checks. |
| `EXECUTED` | Codex → ChatGPT | Announce that one execution attempt is ready for independent inspection; transmit no implementation payload. |
| `REVIEW` | ChatGPT | Inspect current code, available change evidence, and verification evidence through `remote-review`, then choose a terminal result or a next PLAN. |
| `DONE` | ChatGPT, verified by Codex | No material defect remains and Codex's final local verification passed. |
| `BLOCKED` | Either | Progress requires user action, missing authority, unavailable evidence, or exceeds the default iteration budget. |
| `ERROR` | Either | A protocol, website-control, Tunnel, or tool failure prevents a trustworthy result. |

`mode` is fixed as `build` or `review_only` at PRECHECK. Review-only mode never enters `EXECUTING`: a review that finds a material defect returns `outcome: PLAN`, but Codex reports it as `BLOCKED` pending a separately authorized repair task.

Only the transitions in this table are valid. Every omitted transition fails closed and cannot advance the task.

| Current state | Event or guard | Next state | Fail-closed result |
| --- | --- | --- | --- |
| `PRECHECK` | All workspace, Tunnel, seven-tool profile, control-surface ladder, Chat UI, Pro model, account, App, and website checks pass | `INIT` | After surface routing resolves: Work/工作, Chat Pro proven absent, authentication, permission, account choice, unavailable App, declined required Computer Use confirmation, or user-resolvable workspace mismatch → `BLOCKED`; final-surface control failure, unproven exactly-once handoff, a message already sent from Work, runtime, profile, or protocol-integrity failure → `ERROR` |
| `INIT` | The one outbound message is visibly accepted | Wait for `PLAN` in `build`; wait for `REVIEW` in `review_only` | A proven-unsent browser-client message may be retried once with the same IDs; Computer Use never retries after its first Send click; repeated/ambiguous send failure → `ERROR`; auth, App permission, or declined required Computer Use confirmation → `BLOCKED` |
| `INIT` | Valid completed response to the current message | `PLAN` in `build`; `REVIEW` in `review_only` | Malformed, stale, conflicting, or unevidenced response → `ERROR`; explicit user/evidence dependency → `BLOCKED` |
| `PLAN` | Plan is valid, in scope, evidence-based, and its iteration is authorized | `EXECUTING` | Scope/authority/evidence needed → `BLOCKED`; protocol or integrity mismatch → `ERROR` |
| `EXECUTING` | Authorized edit attempt finishes and its verification evidence is recorded, whether checks pass or fail | `EXECUTED` | Missing authority or required user action → `BLOCKED`; writer/tool failure that leaves the actual state untrustworthy → `ERROR` |
| `EXECUTED` | Message is visibly accepted | `REVIEW` | A proven-unsent browser-client message may retry once with the same IDs; Computer Use never retries after its first Send click; repeated or ambiguous failure → `ERROR`; auth/permission or declined required Computer Use confirmation → `BLOCKED` |
| `REVIEW` | Valid response with `outcome: DONE`, plus Codex final checks pass | `DONE` | A completed failing check → `ERROR` because it contradicts DONE; a check that requires user action → `BLOCKED` |
| `REVIEW` | `outcome: PLAN`, mode is `build`, and `next_iteration` is within the default budget | `PLAN`, then `EXECUTING` | `next_iteration` beyond the budget → `BLOCKED`; invalid next iteration → `ERROR` |
| `REVIEW` | `outcome: PLAN`, mode is `review_only` | `BLOCKED` | The plan is advisory only; never edit under review-only authority |
| `REVIEW` | `outcome: BLOCKED` | `BLOCKED` | No automatic fallback |
| `REVIEW` | `outcome: ERROR`, or completed review cannot be trusted | `ERROR` | No automatic fallback |
| Any nonterminal state | User stops the task or required current-turn authority is absent | `BLOCKED` | Preserve evidence; perform no further write or send |
| `DONE`, `BLOCKED`, `ERROR` | Any event | No transition | Start a separately authorized task instead of reviving a terminal task |

A stale response cannot move the state machine. A failed local test is useful review evidence rather than automatically an `ERROR`, provided Codex can prove the resulting workspace state and record the failed check for ChatGPT to inspect.

## Execution Budget

- `iteration` is always a positive integer and starts at `1` for the initial PLAN or review-only review.
- By default, Codex may enter `EXECUTING` at most twice: iteration 1 is the initial implementation and iteration 2 is one remediation attempt. This is an automatic execution budget for one `task_id`, not a technical limit on how many times the project may ever be repaired.
- A REVIEW after iteration 1 may return PLAN for iteration 2 only when it identifies a confirmed material defect. Optional polish does not justify another execution.
- The budget bounds a model-review-to-local-write feedback loop before it can drift in scope, repeatedly reinterpret acceptance criteria, consume unbounded time, or mix stale PLAN/REVIEW messages with newer evidence. A material defect still present after the remediation attempt is a signal to reassess the plan, scope, evidence, environment, or authority rather than continue automatically.
- If REVIEW after iteration 2 requests more changes, record the outstanding findings and transition to terminal `BLOCKED` as a deliberate user checkpoint, not a permanent abandonment. This protocol chooses the new-task approach: further repair requires the user's explicit authorization in a later/current turn and starts a new `task_id` at iteration 1, re-establishing current scope and fresh message/marker identities. Never execute iteration 3 under the old task ID.
- A control-surface recovery or fallback does not consume an execution iteration; a completed Codex code-and-check attempt does.

## Identity And Message Envelope

Generate one random UUID `task_id` at PRECHECK and keep it for the entire loop. Every browser control message gets a new random UUID `message_id` and a unique random reply marker. An outbound message's deduplication key is `(task_id, message_id)`. Use this format without adding code or evidence payloads:

```text
C2C/1 REQUEST
task_id: <task UUID>
mode: <build or review_only>
iteration: <current positive integer>
message_id: <message UUID>
state: <INIT or EXECUTED>
expected_next: <PLAN or REVIEW>
workspace: <basename only>
reply_marker: [[C2C_REPLY_<task-id>_I<iteration>_<random-nonce>]]

<short task or state instruction>

End your complete response with the reply_marker exactly and use the response envelope below. Do not omit fields; use the literal `NONE` when a field has no value.
```

ChatGPT has exactly one valid response envelope:

```text
C2C/1 RESPONSE
task_id: <same task UUID>
mode: <same mode>
iteration: <current positive integer>
response_id: <new response UUID>
in_reply_to: <control message UUID>
state: <PLAN, REVIEW, BLOCKED, or ERROR>
outcome: <DONE, PLAN, BLOCKED, ERROR, or NONE>
next_iteration: <positive integer or NONE>
evidence_used: <single-line JSON array, or NONE>
findings_or_plan: <single-line JSON string/object/array, or NONE>
risks: <single-line JSON array, or NONE>
verification_request: <single-line JSON array, or NONE>

[[exact requested reply marker]]
```

The final marker is a completion sentinel, not an identity or deduplication key. The inbound deduplication key is `(task_id, response_id)`, and only one response may be consumed for a given `(task_id, in_reply_to)`.

Envelope rules:

- `iteration` always names the current iteration. It never advances inside a response. An initial response uses `iteration: 1`; the response to `EXECUTED(i)` uses `iteration: i`.
- For `INIT` in build mode, `state` is `PLAN`, `BLOCKED`, or `ERROR`; `outcome` and `next_iteration` are `NONE`.
- For `INIT` in review-only mode, `state` is `REVIEW`, `BLOCKED`, or `ERROR`; a REVIEW has an `outcome` of `DONE`, `PLAN`, `BLOCKED`, or `ERROR`.
- For `EXECUTED(i)`, `state` is `REVIEW`, `iteration` remains `i`, and `outcome` is `DONE`, `PLAN`, `BLOCKED`, or `ERROR`.
- `next_iteration` has a value only when `state: REVIEW` and `outcome: PLAN`. It must equal `iteration + 1`. In every other response it is `NONE`.
- `outcome` is never inferred: it is `NONE` outside `state: REVIEW` and one of the four declared outcomes in a REVIEW.
- Every field shown above must be present even when its value is `NONE`. JSON-valued fields stay on their named line so nested content cannot be mistaken for a new field. Additional top-level fields invalidate the envelope unless a later protocol version defines them.

Codex validates the exact response in process memory before advancing. Every accepted `PLAN`, and every `REVIEW` with `outcome: DONE` or `outcome: PLAN` that depends on local evidence, must have actual private-App tool-call status/control evidence in that same assistant turn. An `evidence_used` field or assistant-prose claim naming `remote-review` tools is not proof that the App ran. A validated `BLOCKED` or `ERROR` may omit a successful tool call when the missing App/evidence is itself the declared reason. Codex may persist only the sanitized, public-safe envelope and summary described in [browser-session.md](browser-session.md), not private code, raw accessibility state, or the raw response.

Codex enters the local `REVIEW` waiting state as soon as `EXECUTED` is visibly submitted. The completed `state: REVIEW` response selects the next transition through its outcome.

## PRECHECK

Before sending `INIT`, Codex must verify and record:

- one canonical, non-symlink project root passed the workspace validator;
- the Tunnel reports `running_managed`, its live workspace exactly matches that root, and health, readiness, and control-plane polling are all successful;
- the remote profile exposes exactly the seven read-only tools: `workspace_overview`, `list_files`, `search_code`, `read_snippet`, `review_changes`, `verification_report`, and `review_packet`;
- after the automatic selection procedure in [chat-pro-selection.md](chat-pro-selection.md), a fresh conversation visibly has Chat/聊天 selected, its active model control contains `Pro`, and no Work/工作 surface is active;
- the intended signed-in ChatGPT account and the private App configured as `<PRIVATE_CHATGPT_APP_NAME>` in [setup.md](setup.md) are visibly available;
- the current website control surface satisfies [browser-session.md](browser-session.md);
- [browser-surface-ladder.md](browser-surface-ladder.md) records the current-run requested surface, primary/attempted/active surfaces, sanitized fallback reasons, same-conversation proof when required, and any Computer Use AX/confirmation evidence.

The in-app surface may activate bounded Chrome and final Computer Use fallbacks while PRECHECK remains open when the resolved current-run policy permits them. A missing Chrome extension is a technical transition to Computer Use on the default ladder; it is `BLOCKED` only when no later surface is permitted. After the permitted ladder, stop at `BLOCKED` for Work/工作 before send, Chat Pro proven absent, an App unavailable in Chat Pro, authentication, permission grants, ambiguous account choice, declined required Computer Use confirmation, or a user-resolvable workspace mismatch. Routine model selection is not a user-action blocker. Stop at `ERROR` if final-surface control cannot establish trustworthy state, exactly-once handoff cannot be proven, a message was already sent from Work, or for a foreign listener, unhealthy runtime, seven-tool profile mismatch, or another integrity failure. Do not rebind or restart a live Tunnel underneath a task.

## INIT, Initial PLAN, And Review-Only

The `INIT` body may contain only:

- the user's goal and material constraints;
- the current date when freshness matters;
- the workspace basename;
- the requested deliverable and acceptance criteria;
- an instruction to use the private App for local evidence and Web Search only when current external evidence is needed.

The entire control message, including its envelope and marker, must be at most 2,000 Unicode characters; its body must be at most 1,000 characters. Never split one protocol request across multiple ChatGPT turns. If the goal cannot be represented safely within the limit, stop at `BLOCKED` and ask the user to narrow it.

If Computer Use will send `INIT`, prepare and verify the exact message, then stop immediately before the unique semantic Send action and obtain action-time confirmation for that `message_id`. Broad earlier approval does not replace this confirmation.

Tell ChatGPT to begin with `workspace_overview`, then use the other `remote-review` tools as needed. It must not infer the codebase from the control message. A valid PLAN should distinguish verified local facts, external evidence, assumptions, risks, implementation steps, and checks Codex should run. ChatGPT may propose code-level changes but does not write files or claim to have run commands.

In `review_only` mode, send `INIT` with `expected_next: REVIEW` and ask ChatGPT to inspect the existing implementation without requesting any Codex edit. `outcome: DONE` means no material defect was found. `outcome: PLAN` carries a proposed remediation plan but transitions locally to `BLOCKED`; it grants no repair authority.

Codex must validate each material PLAN claim against the workspace before execution. ChatGPT advice is not authority to broaden scope, delete, publish, send messages, change accounts, or perform other external actions.

## EXECUTING And EXECUTED

During `EXECUTING`, Codex is the sole writer. It applies only changes authorized by the user, runs proportionate project-local checks, and keeps actual code, diff, and logs out of the website control message.

After the attempt, send a fresh `EXECUTED` envelope whose body says only that the authorized implementation and local verification for the named iteration are ready for review. Do not summarize the patch or paste filenames, code, diffs, test output, commands, or absolute paths. If Computer Use will perform the send, prepare the exact envelope, then obtain a fresh action-time confirmation immediately before its one semantic Send click; every `EXECUTED` requires its own confirmation. Enter `REVIEW` immediately after the message is accepted by the page.

In REVIEW, instruct ChatGPT to obtain the real evidence itself:

1. use `review_changes` when Git evidence is available;
2. use `review_packet` and targeted `read_snippet` or `search_code` to verify behavior and context;
3. use `verification_report` to inspect Codex-recorded check evidence without claiming ChatGPT ran those checks;
4. order findings by severity and separate confirmed defects, uncertainty, and optional improvements.

If the workspace is not a Git repository, or Git change evidence is otherwise unavailable, `review_changes` cannot prove the patch or history. ChatGPT must instead inspect every affected file directly with `read_snippet`/`search_code`, use `review_packet` and `verification_report`, and state `git_diff_evidence: unavailable` inside `evidence_used`. `DONE` is still possible only when that direct inspection covers the affected surface and Codex records the boundary; neither side may claim that a diff, commit, or history was reviewed.

A `state: REVIEW` response returns one outcome:

- `DONE` only when no material defect remains;
- `PLAN` only for confirmed defects that require another authorized implementation attempt;
- `BLOCKED` when evidence or user action is required;
- `ERROR` when a trustworthy review cannot be completed.

## Duplicate, Stale, And Partial Responses

Maintain a task-local manifest containing the current state, iteration, outbound message IDs, expected markers, and consumed response IDs/markers. Exact private response text may remain only in process memory for parsing and comparison.

- Never execute a PLAN whose `in_reply_to`, task ID, iteration, or marker does not match the currently expected transition.
- Reject a reused `(task_id, response_id)`. If the same response ID appears with different content, transition to `ERROR`.
- Accept at most one response for `(task_id, in_reply_to)`. A second response for an already-consumed request is ignored; conflicting unconsumed responses are an ambiguous `ERROR`.
- Mark an accepted response ID and its `in_reply_to` as consumed before entering `EXECUTING`. Never execute the same PLAN twice, including after refresh, extraction retry, or app restart.
- Ignore duplicate or previously consumed assistant messages; record them as ignored evidence.
- If sending is uncertain, inspect the visible conversation for the exact message ID and marker. A browser-client surface may retry only after trustworthy proof that submission never occurred; Computer Use never retries after its first Send click. Never generate a replacement ID merely to make progress.
- A control-surface switch after an uncertain or proven send may inspect only the visibly proven same conversation. It never authorizes a replacement conversation or resend. A Computer Use takeover must use a fresh complete accessibility state and may never treat a missing item in one snapshot as proof that it was not sent.
- Partial streaming text, a missing final marker, malformed envelopes, or claims without `remote-review` evidence cannot advance the state.
- One safely proven-unsent browser-client retry may reuse the same message ID and marker. Computer Use never retries after its first Send click. A repeated or ambiguous failure is `ERROR`.

## Stop Conditions And Reporting

Use `BLOCKED` on the selected intended surface for user-resolvable conditions such as login, CAPTCHA, 2FA, account choice, App authorization, missing permission, a declined required Computer Use confirmation, a workspace mismatch that requires stopping the original Tunnel, or exhausted iteration budget. A missing Chrome extension is `BLOCKED` only when Computer Use is not permitted later in the resolved ladder. Use `ERROR` for final-surface control failure, unproven exactly-once handoff, invalid protocol output, unavailable MCP tools, or a runtime failure that prevents reliable evidence.

On every terminal state, report:

- task ID, final state, and executions actually performed;
- whether ChatGPT visibly used `remote-review` for PLAN and final REVIEW;
- files Codex actually changed and checks Codex actually ran;
- whether Git diff evidence was available and, if not, which direct-file review boundary was used;
- requested/attempted/final control surfaces, each sanitized fallback reason, exactly-once handoff result, and any Computer Use target/method/confirmation/send-count/extraction result;
- remaining findings, uncertainty, or required user action;
- the saved sanitized evidence directory.

Never claim `DONE` merely because Codex finished editing, ChatGPT produced prose, or a screenshot exists. Completion requires the website-session and evidence conditions in [browser-session.md](browser-session.md).
