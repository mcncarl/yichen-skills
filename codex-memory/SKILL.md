---
name: codex-memory
description: Install, upgrade, inspect, and maintain the public Codex Memory system from the mcncarl/codex-memory repository. Use when the user asks to install a Markdown/Obsidian-first Codex memory vault, migrate or sanitize an existing memory system, configure SQLite/FTS or optional Zvec semantic retrieval, run memory search, closeout, audit, or troubleshoot Codex memory scripts and templates.
---

# Codex Memory

## Overview

Use this skill to help a user install or operate the public Codex Memory system. Treat the GitHub repository as the product source, and treat this skill as the Agent-facing runbook for setup, maintenance, and troubleshooting.

Repository: `https://github.com/mcncarl/codex-memory`

## Safety Rules

- Never copy a user's real memory vault into a public repository.
- Never commit `.env`, SQLite databases, Zvec/vector stores, model caches, logs, API keys, cookies, tokens, passwords, private chat logs, customer data, or personal absolute paths.
- When migrating an existing memory system, migrate structure, scripts, and sanitized patterns only.
- Before publishing or pushing, run leak checks and inspect the diff.
- If a task involves deleting files, ask for explicit user permission first and use Trash, not permanent deletion.

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
```

5. Tell the user the final vault path, state database path, and the command to run at the end of future important tasks:

```bash
python3 scripts/codex_memory_closeout.py --dry-run
python3 scripts/codex_memory_closeout.py --commit
```

## Daily Operations

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

Closeout discovers changed memory files, checks structure and leaks, performs postwrite reconcile, refreshes SQLite, optionally refreshes Zvec, refreshes Agent evolution when needed, piggybacks audit when due, logs the run, and can commit only processed memory files.

Run audit manually when asked:

```bash
python3 scripts/codex_memory_audit.py
python3 scripts/codex_memory_audit.py --ignore FINDING_ID --note "reason"
python3 scripts/codex_memory_audit_autorun.py --reason manual --json
```

Audit findings are prompts for review. Do not let audit directly rewrite Markdown facts unless the user asks for that update.

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
rg -n "/Users/|sk-[A-Za-z0-9]|token|secret|cookie|password|\\.sqlite|\\.db|zvec" .
```

5. Inspect `git diff` before committing.
6. Commit and push only after the leak check is clean or every match is confirmed to be a harmless example or warning.

## Troubleshooting

- If search says the SQLite index is missing, run `codex_memory_index.py --init --scan --report`.
- If closeout cannot find changes, check `CODEX_MEMORY_ROOT` and `CODEX_MEMORY_GIT_ROOT`.
- If commit is skipped, read the warnings; `MERGE_REQUIRED`, `ASK_USER`, deleted files, or failed checks need user review.
- If Zvec is slow or unavailable, use `--no-zvec` for search/reconcile or `--skip-zvec` for closeout.
- If audit repeats the same finding, record a decision with `--ignore`, `--resolve`, or `--snooze`.
