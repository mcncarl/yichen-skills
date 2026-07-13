---
name: agent-memory
description: Install, upgrade, inspect, and maintain the public Agent Memory Vault system from the mcncarl/agent-memory-vault repository, including a shared Claude Code and Codex setup. Use when the user asks to install a Markdown/Obsidian-first memory vault, connect Claude Code and Codex to one fact source, configure SQLite/FTS or optional Zvec semantic retrieval, run search, closeout, audit, or troubleshoot memory scripts and hooks.
---

# Agent Memory Vault

## Overview

Use this skill to help a user install or operate the public Agent Memory Vault system. The vault can be shared by Claude Code and Codex: Markdown remains the single fact source, while each host keeps a thin rule and hook adapter. Treat the GitHub repository as the product source, and treat this skill as the Agent-facing runbook for setup, maintenance, and troubleshooting.

Repository: `https://github.com/mcncarl/agent-memory-vault`

## Safety Rules

- Never copy a user's real memory vault into a public repository.
- Never commit `.env`, SQLite databases, Zvec/vector stores, model caches, logs, API keys, cookies, tokens, passwords, private chat logs, customer data, or personal absolute paths.
- When migrating an existing memory system, migrate structure, scripts, and sanitized patterns only.
- Before publishing or pushing, run leak checks and inspect the diff.
- If a task involves deleting files, ask for explicit user permission first and use Trash, not permanent deletion.
- Never point Claude Code auto-memory at the formal vault. Either disable it or treat it as non-authoritative scratch memory.
- Shared cookies and tokens belong in a private config outside the vault and Git, with owner-only permissions; Agents should inject selected values into commands instead of printing the whole file.

## Install Workflow

1. Clone or update the repository:

```bash
git clone https://github.com/mcncarl/agent-memory-vault.git
cd agent-memory-vault
```

2. Create a local private vault from the template:

```bash
python3 scripts/bootstrap.py --memory-root "$HOME/agent-memory-vault" --write-env
source .env
```

3. For a stable shared runtime, install the repository's canonical scripts and create a private TOML config:

```bash
python3 scripts/install_runtime.py --config-root "$HOME/.config/agent-memory"
cp config/agent-memory.example.toml "$HOME/.config/agent-memory/config/agent-memory.toml"
# Edit memory_root, git_root, and state_db. Never commit this private file.
"$HOME/.config/agent-memory/scripts/install_runtime.py" \
  --config-root "$HOME/.config/agent-memory" --verify --json
```

Treat the public repository as the only core-script source. The installer preserves unknown local adapters and private config while recording file hashes in `runtime-manifest.json`.

4. Optionally initialize Git for the private vault:

```bash
git -C "$AGENT_MEMORY_GIT_ROOT" init
```

5. Build indexes and validate:

```bash
python3 scripts/agent_memory_evolution.py --init --scan --report
python3 scripts/agent_memory_index.py --init --scan --report
python3 scripts/agent_memory_check.py
python3 scripts/agent_memory_doctor.py
```

6. Tell the user the final vault path, state database path, and the claim/closeout commands for future important tasks:

```bash
memoryctl --actor codex claim --file "/absolute/path/to/changed-memory.md"
memoryctl --actor codex closeout --dry-run
memoryctl --actor codex closeout
```

## Daily Operations

When the neutral wrapper is installed, prefer it from both hosts:

```bash
memoryctl --actor codex search "query" --limit 5
memoryctl --actor claude prewrite "summary of the memory to write"
memoryctl --actor claude claim --file "/absolute/path/to/changed-memory.md"
memoryctl --actor claude closeout
```

Use only `memoryctl` and the `agent_memory_*` entrypoints. Compatibility wrappers are intentionally not installed; update every Hook, scheduler, shell alias, and custom script before removing an older installation.

Use the unified search entrypoint by default:

```bash
python3 scripts/agent_memory_search.py "query" --limit 5
python3 scripts/agent_memory_search.py "query" --track project
python3 scripts/agent_memory_search.py "query" --memory-type workflow
```

Before writing a new formal memory, run prewrite reconcile:

```bash
python3 scripts/agent_memory_closeout.py --prewrite "summary of the memory to write"
```

Allowed reconcile actions:

- `ADD`: create a new memory.
- `UPDATE`: update an existing memory.
- `NOOP`: do not write.
- `MARK_OUTDATED`: mark old information outdated without deleting it.
- `MERGE_REQUIRED`: stop and ask the user to merge or choose.
- `ASK_USER`: ask before sensitive, destructive, account, credential, cost, or uncertain actions.

Immediately after creating or changing a formal memory, claim it for the current host session:

```bash
memoryctl --actor codex claim --file "/absolute/path/to/changed-memory.md"
memoryctl --actor claude claim --file "/absolute/path/to/changed-memory.md"
```

Codex normally exposes `CODEX_THREAD_ID`. For Claude, configure `agent_memory_session_hook.py --actor claude` under `SessionStart`; it uses Claude Code's official `CLAUDE_ENV_FILE` mechanism to export the hook payload's real `session_id` to later Bash commands and clears any inherited Codex thread ID. Claims are stored in SQLite with only a one-way session hash. At the end of an important task, run closeout:

```bash
python3 scripts/agent_memory_closeout.py --dry-run
python3 scripts/agent_memory_closeout.py --commit
```

Session closeout processes only files claimed by that actor/session and also recovers their changes if an external backup tool committed first. Other sessions' files are excluded. A successful closeout records the processed content hash in `memory_file_observations`; only a matching observation proves that historical content is complete and lets the shared Git baseline advance. Unclaimed dirty memory must be resolved instead of being silently swept into a commit. Human maintenance can use `memoryctl --actor human closeout --global` deliberately.

Closeout uses both a process lock and a session ownership ledger: the lock serializes SQLite/Zvec/Git work, while claims prevent cross-session commits. Its compaction messages are non-blocking advisories, while failed checks or unresolved semantic duplicates still block the normal commit path.

Run audit manually when asked:

```bash
python3 scripts/agent_memory_audit.py
python3 scripts/agent_memory_audit.py --ignore FINDING_ID --note "reason"
python3 scripts/agent_memory_audit_autorun.py --reason manual --json
python3 scripts/agent_memory_doctor.py
```

Audit findings are prompts for review. Do not let audit directly rewrite Markdown facts unless the user asks for that update. Current-fact invariants can detect retired paths/scripts, wrong `agent_scope`, and stale fixed metrics in active summaries.

`doctor` is read-only by default. It also checks for stale session claims, an aging unpushed memory history, and a semantic virtual environment whose base Python disappeared. Use `--repair-derived` only when the user wants SQLite/FTS and Zvec rebuilt; it must never rewrite Markdown facts.

## Optional Semantic Retrieval

Install the tested `requirements-vector.lock`, then build and validate Zvec:

```bash
python3 scripts/agent_memory_zvec_index.py --scan --prune
python3 scripts/agent_memory_zvec_index.py --report
```

For durable offline use, copy or APFS-clone a pinned model snapshot into the private runtime, set `require_local_model = true`, and record a private model manifest with revision, sizes, and hashes. `doctor` should pass the local-model, manifest-integrity, dependency-lock, and real offline-query checks before calling the semantic layer hardened.

The unified search runs SQLite and Zvec in parallel, applies all filters after merging, and discards semantic neighbors beyond the configured distance threshold. Search hits are candidates; always read the Markdown source before treating a claim as true.

## Optional Automation

Only install global Codex hooks or a macOS LaunchAgent after the user has asked for automation.

- Stop is turn-scoped in both hosts, so the memory hook must be gated and quiet when the current session has no claims and all pending files belong to other sessions.
- Claude must have the SessionStart bridge in the live settings and in any settings manager's persistent configuration; verify it alongside Stop and SessionEnd after provider switches.
- A shared setup runs full closeout from Stop only after the Agent has written and claimed formal memory. Unclaimed dirty memory should block silent completion with a concrete claim instruction.
- Both hosts should block normal completion when closeout fails, using their native protocols: Claude returns `decision: block`; Codex exits with code `2` and writes a continuation prompt to stderr. Claude SessionEnd can be a non-blocking fallback; Codex currently has no direct equivalent.
- Keep the outer Stop hook timeout slightly above the closeout timeout. For a 300-second closeout, use at least 320 seconds outside.
- Keep one global closeout lock, one Git baseline, one session-claim table, one audit scheduler, one SQLite database, and one Zvec index across both hosts.
- Let `agent_memory_audit_autorun.py --min-interval-days 7` decide whether audit is due.
- When the interval is due, autorun should run the content audit and then the read-only Doctor, persisting separate `latest-audit.json` and `latest-doctor.json` reports and notifying on either findings or infrastructure health drift.
- The weekly LaunchAgent must not use `--force`; otherwise closeout, hook, and launchd can run duplicate audits inside the same seven-day window.
- Merge the memory command into existing `~/.codex/hooks.json`; never overwrite unrelated hooks.
- After changing a hook command, tell the user Codex may ask them to review/trust the new hook hash.

## Upgrade Or Publish Workflow

When updating the public template repository:

1. Work in the `agent-memory-vault` repository.
2. Add or update only public-safe scripts, templates, docs, and fake examples.
3. Keep real user memory in the private vault.
4. Run:

```bash
python3 -m compileall scripts
python3 scripts/agent_memory_index.py --init --scan --report
python3 scripts/agent_memory_check.py --skip-state-db
python3 scripts/agent_memory_doctor.py
rg -n "/Users/|sk-[A-Za-z0-9]|token|secret|cookie|password|\\.sqlite|\\.db|zvec" .
```

5. Inspect `git diff` before committing.
6. Commit and push only after the leak check is clean or every match is confirmed to be a harmless example or warning.

## Troubleshooting

- If search says the SQLite index is missing, run `agent_memory_index.py --init --scan --report`.
- If closeout cannot find changes, check `AGENT_MEMORY_ROOT` and `AGENT_MEMORY_GIT_ROOT`.
- If commit is skipped, read the warnings; `MERGE_REQUIRED`, `ASK_USER`, deleted files, or failed checks need user review.
- If Zvec is slow or unavailable, use `--no-zvec` for search/reconcile or `--skip-zvec` for closeout.
- If Zvec parity fails, run `agent_memory_zvec_index.py --scan --prune` and then `--report`.
- If audit repeats the same finding, record a decision with `--ack`, `--ignore`, `--resolve`, or `--snooze`; finding IDs must remain stable as counts change.
- If Claude debug reports zero matching hooks after installation, check whether a provider switcher rewrote `~/.claude/settings.json`. Persist the hooks in that manager's common configuration and any live rollback copy, then restart it and verify the loaded matchers again.
- If doctor reports `needs_review` or `mtime_fallback`, do not fabricate a verification date. Classify structural/snapshot documents explicitly, use document dates only as provenance, and add `verified_at` only after checking real evidence.
- If doctor reports Zvec hash mismatch, run closeout for the claimed changed files or run `agent_memory_zvec_index.py --scan --prune`; equal document counts alone do not prove fresh vectors.
- If doctor reports `session_claim_hygiene`, preview with `memoryctl --actor human claims-expire --older-than-hours 24 --json`; add `--apply` only after confirming those sessions are no longer active. This changes the SQLite ownership ledger, not Markdown.
- If doctor reports `memory_remote_backup`, inspect the private-vault diff and leak scan before pushing. A clean local Git baseline is not a remote backup.
- If doctor reports `semantic_python_runtime`, recreate the private venv from the exact dependency lock with an available Python of the same supported minor version, then rerun the offline semantic probe.
