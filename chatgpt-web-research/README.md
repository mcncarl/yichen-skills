# ChatGPT Web Research

Use the official ChatGPT website, through the user's already signed-in Chrome profile, to run research tasks and save verified Markdown reports.

## What It Does

- Uses the real ChatGPT web page as the source of truth
- Prefers the Chrome extension/browser-control route when available
- Falls back to visible Computer Use only when Chrome control cannot attach
- Requires the response to finish and include a unique completion marker
- Extracts the answer from the page, saves a raw Markdown copy, and saves a readable report

## Privacy Notes

- This public version does not include personal local paths, account names, cookies, tokens, or browser storage
- The skill explicitly forbids inspecting cookies, local storage, passwords, browser profiles, or session stores
- Report paths use `<WORKSPACE>/reports/` placeholders; adapt them to your own workspace
- Profile names are represented as `<profile-name>` placeholders

## Requirements

- A supported Claude Code / Codex environment with `chrome:control-chrome`
- `computer-use:computer-use` available for fallback
- A Chrome profile already signed in to the intended ChatGPT account
- User-visible confirmation of paid or Pro model status when a task explicitly requires it

## Typical Use

```text
Use $chatgpt-web-research to research Anthropic through the official ChatGPT web page and save a verified Markdown report.
```

The skill is intentionally strict: if it cannot operate the intended real ChatGPT page, it stops instead of substituting an API call, web search, or a different account.
