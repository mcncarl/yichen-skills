---
name: codex-memory
description: Install, upgrade, inspect, and maintain the public Codex Memory system from the mcncarl/codex-memory repository, including a shared Claude Code and Codex setup. Use when the user asks to install a Markdown/Obsidian-first memory vault, connect Claude Code and Codex to one fact source, configure SQLite/FTS or optional Zvec semantic retrieval, run search, closeout, audit, or troubleshoot memory scripts and hooks.
---

# Codex Memory

## Overview

Use this skill to help a user install or operate the public Codex Memory system. The vault can be shared by Claude Code and Codex: Markdown remains the single fact source, while each host keeps a thin rule and hook adapter. Treat the GitHub repository as the product source, and treat this skill as the Agent-facing runbook for setup, maintenance, and troubleshooting.

Repository: `https://github.com/mcncarl/codex-memory`

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
git clone https://github.com/mcncarl/codex-memory.git
cd codex-memory
```

2. Create a local private vault from the template:

```bash
python3 scripts/bootstrap.py --memory-root "$HOME/codex-memory-vault" --write-env
source .env
```

3. Optionally initialize Git for the private vault:

```bash
git -C "$CODEX_MEMORY_GIT_ROOT" init
```

4. Build indexes and validate:

```bash
python3 scripts/codex_agent_evolution.py --init --scan --report
python3 scripts/codex_memory_index.py --init --scan --report
python3 scripts/codex_memory_check.py
python3 scripts/codex_memory_doctor.py
```

5. Tell the user the final vault path, state database path, and the command to run at the end of future important tasks:

```bash
python3 scripts/codex_memory_closeout.py --dry-run
python3 scripts/codex_memory_closeout.py --commit
```

## Daily Operations

When the neutral wrapper is installed, prefer it from both hosts:

```bash
memoryctl --actor codex search "query" --limit 5
memoryctl --actor claude prewrite "summary of the memory to write"
memoryctl --actor claude closeout
```

The original script names remain supported for compatibility.

Use the unified search entrypoint by default:

```bash
python3 scripts/codex_memory_search.py "query" --limit 5
python3 scripts/codex_memory_search.py "query" --track project
python3 scripts/codex_memory_search.py "query" --memory-type workflow
```

Before writing a new formal memory, run prewrite reconcile:

```bash
python3 scripts/codex_memory_closeout.py --prewrite "summary of the memory to write"
```

Allowed reconcile actions:

- `ADD`: create a new memory.
- `UPDATE`: update an existing memory.
- `NOOP`: do not write.
- `MARK_OUTDATED`: mark old information outdated without deleting it.
- `MERGE_REQUIRED`: stop and ask the user to merge or choose.
- `ASK_USER`: ask before sensitive, destructive, account, credential, cost, or uncertain actions.

At the end of an important task, run closeout:

```bash
python3 scripts/codex_memory_closeout.py --dry-run
python3 scripts/codex_memory_closeout.py --commit
```

Closeout discovers dirty memory files and also recovers changes committed by an external backup tool since the last successful `git_observed_through` baseline. It checks structure and leaks, performs postwrite reconcile, refreshes SQLite, optionally refreshes Zvec, refreshes Agent evolution when needed, piggybacks audit when due, logs the run, and can commit only processed memory files.

Closeout uses a process lock. Its compaction messages are non-blocking advisories, while failed checks or unresolved semantic duplicates still block the normal commit path.

Run audit manually when asked:

```bash
python3 scripts/codex_memory_audit.py
python3 scripts/codex_memory_audit.py --ignore FINDING_ID --note "reason"
python3 scripts/codex_memory_audit_autorun.py --reason manual --json
python3 scripts/codex_memory_doctor.py
```

Audit findings are prompts for review. Do not let audit directly rewrite Markdown facts unless the user asks for that update.

`doctor` is read-only by default. Use `--repair-derived` only when the user wants SQLite/FTS and Zvec rebuilt; it must never rewrite Markdown facts.

## Optional Semantic Retrieval

After installing `requirements-vector.txt`, build and validate Zvec with:

```bash
python3 scripts/codex_memory_zvec_index.py --scan --prune
python3 scripts/codex_memory_zvec_index.py --report
```

The unified search runs SQLite and Zvec in parallel, applies all filters after merging, and discards semantic neighbors beyond the configured distance threshold. Search hits are candidates; always read the Markdown source before treating a claim as true.

## Optional Automation

Only install global Codex hooks or a macOS LaunchAgent after the user has asked for automation.

- Stop is turn-scoped in both hosts, so the memory hook must be gated and quiet when there are no pending memory changes.
- A shared setup may run full closeout from Stop only after the Agent has written formal memory and only when dirty Markdown or unobserved Git history exists.
- Claude Stop should block completion when closeout returns an error or unresolved merge; SessionEnd can be a non-blocking fallback.
- Keep one global closeout lock, one Git baseline, one audit scheduler, one SQLite database, and one Zvec index across both hosts.
- Let `codex_memory_audit_autorun.py --min-interval-days 7` decide whether audit is due.
- The weekly LaunchAgent must not use `--force`; otherwise closeout, hook, and launchd can run duplicate audits inside the same seven-day window.
- Merge the memory command into existing `~/.codex/hooks.json`; never overwrite unrelated hooks.
- After changing a hook command, tell the user Codex may ask them to review/trust the new hook hash.

## Upgrade Or Publish Workflow

When updating the public template repository:

1. Work in the `codex-memory` repository.
2. Add or update only public-safe scripts, templates, docs, and fake examples.
3. Keep real user memory in the private vault.
4. Run:

```bash
python3 -m compileall scripts
python3 scripts/codex_memory_index.py --init --scan --report
python3 scripts/codex_memory_check.py --skip-state-db
python3 scripts/codex_memory_doctor.py
rg -n "/Users/|sk-[A-Za-z0-9]|token|secret|cookie|password|\\.sqlite|\\.db|zvec" .
```

5. Inspect `git diff` before committing.
6. Commit and push only after the leak check is clean or every match is confirmed to be a harmless example or warning.

## Troubleshooting

- If search says the SQLite index is missing, run `codex_memory_index.py --init --scan --report`.
- If closeout cannot find changes, check `CODEX_MEMORY_ROOT` and `CODEX_MEMORY_GIT_ROOT`.
- If commit is skipped, read the warnings; `MERGE_REQUIRED`, `ASK_USER`, deleted files, or failed checks need user review.
- If Zvec is slow or unavailable, use `--no-zvec` for search/reconcile or `--skip-zvec` for closeout.
- If Zvec parity fails, run `codex_memory_zvec_index.py --scan --prune` and then `--report`.
- If audit repeats the same finding, record a decision with `--ack`, `--ignore`, `--resolve`, or `--snooze`; finding IDs must remain stable as counts change.
- If doctor reports `mtime_fallback`, do not fabricate a verification date. Re-verify that fact, then add an explicit `verified_at` and suitable `review_after_days`.
