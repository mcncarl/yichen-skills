---
name: chatgpt-web-research
description: Use the user's already signed-in official ChatGPT website account, especially GPT-5.5 Pro / ChatGPT Pro, to perform product research, market research, competitor research, second-opinion analysis, or any request that says ChatGPT 官网, ChatGPT 网页版, GPT-5.5 Pro, 5.5 Pro, 用官网调研, 产品调研, 市场调研, or avoid API cost. Prefer the Chrome plugin/extension route; if it is unavailable or cannot attach, fall back to Computer Use on the real visible Chrome window/profile. This skill must control the real ChatGPT web page in the intended Chrome account/profile; it must not open a different free-account window, use OpenAI API, use web search alone, use generic Playwright, or use the deprecated chatgpt-web MCP.
---

# ChatGPT Web Research

## Hard Rule

Use the official ChatGPT web page through the user's already signed-in Chrome account/profile as the source of truth.

Do not create or use a separate free ChatGPT window/account. If the intended Pro / GPT-5.5 Pro account is not visibly available through either the Chrome plugin-controlled page or the Computer Use visible Chrome page, stop and ask the user to open or switch to that logged-in ChatGPT account in Chrome.

Do not answer from the OpenAI API, local model output, ordinary web search, the deprecated `chatgpt-web` MCP, old task files, or memory. If the Chrome plugin route is unavailable in the current thread, use Computer Use as the fallback when it can operate the user's real visible ChatGPT page. If neither route can operate that page, stop and report that the required ChatGPT website route is unavailable.

When the task is product or market research, the deliverable is not complete until the ChatGPT web response is visibly complete, extracted from the page, saved as Markdown, and verified.

## Required Routes

Before browser-plugin work, load and follow `chrome:control-chrome`. Before Computer Use fallback work, load and follow `computer-use:computer-use`.

- Load `chrome:control-chrome` from the current environment skill registry. Do not hard-code user-specific local plugin paths.
- Load `computer-use:computer-use` from the current environment skill registry before Computer Use fallback. Do not hard-code user-specific local plugin paths.
- If the Chrome skill body was included verbatim in the current user message, it does not need to be re-read.
- Prefer the Chrome skill's `node_repl` / browser-client route when available.
- Do not blindly use `agent.browsers.get("extension")` when more than one Chrome extension instance/profile is available. First call `agent.browsers.list()`, inspect only the returned metadata such as profile name / last-used flag, and choose the Chrome extension instance that matches the user's specified account/profile.
- Start by inspecting Chrome tabs through the selected browser's `browser.user.openTabs()` and claiming a real ChatGPT tab from the user's existing Chrome session whenever one is available. This is the safest way to stay in the user's intended logged-in ChatGPT account.
- Do not inspect cookies, local storage, passwords, browser profiles, or session stores.
- If `node_repl` is not visible, use tool discovery for `node_repl js`. If it still is not available, switch to Computer Use fallback.
- Treat `Browser is not available: extension`, `Browser is not available: iab`, an empty `agent.browsers.list()`, or an inability to claim the visible ChatGPT tab as Chrome-plugin failure. Do not run diagnostics unless the user asks; continue with Computer Use fallback.

## Computer Use Fallback

Use this path only after the Chrome plugin route is unavailable or cannot attach, or when the user explicitly asks for `@电脑`.

- Control the user's already-open Chrome window/profile. Prefer the window whose title, profile button, and tab strip match the intended account/profile, for example `Chrome - <profile-name>`.
- It is acceptable to open a new ChatGPT tab in the same verified Chrome window/profile when the user approves or the current verified tab is unsuitable. Do not open a different Chrome profile or a separate account window.
- Use only visible page information for account/model checks. Do not open or inspect session/status endpoints, cookies, local storage, passwords, browser profiles, or session stores.
- If a sensitive session/API tab is already open, ignore it and do not quote or extract its contents.
- Confirm GPT-5.5 / Pro by opening the visible model/menu when needed and checking labels such as `GPT-5.5`, `Pro`, `Pro 扩展`, or an equivalent paid-route indicator. If Pro status cannot be confirmed and the user explicitly requested Pro, stop before sending.
- Use the visible ChatGPT composer to paste or set the prompt. Verify the unique completion marker appears in the composer before sending.
- Use the same completion criteria as the Chrome route: wait until the page is no longer generating and the visible response contains the marker.
- Prefer the page's `复制回复` button for extraction, but verify the system clipboard contains non-empty assistant text with the marker. If the page shows `Failed to copy to clipboard`, the clipboard is empty, or the clipboard contains the wrong text, extract from the Computer Use accessibility tree and reconstruct readable Markdown, explicitly noting that extraction method in the saved report header.
- If Computer Use focus lands on unrelated tabs, switch back by exact ChatGPT tab title/URL and do not read unrelated private content.

## Workflow

1. Name the browser session, for example `🔎 ChatGPT 调研`.
2. Locate the intended ChatGPT account through the Chrome plugin:
   - Call `agent.browsers.list()` and identify all Chrome extension instances. If the user names an account/profile such as `<profile-name>`, match that name before opening or claiming any ChatGPT page.
   - If multiple Chrome instances are visible and none matches the user's named account/profile, do not fall back to the last-used or default Chrome profile.
   - If the user says the named Chrome profile/window is already open, use `computer-use` only to inspect the visible Chrome window title, profile button, tab strip, and Codex extension presence. If that visible window title/profile identifies the intended profile but Chrome plugin metadata uses a generic name such as `您的 Chrome`, map the plugin instance by matching its open tab list to the visible tab strip before continuing.
   - Call `browser.user.openTabs()` on the selected Chrome instance and look for existing `chatgpt.com` tabs.
   - Prefer a tab whose visible title/account/model indicates the user's paid ChatGPT account.
   - Claim the exact tab object returned by `openTabs()` with `browser.user.claimTab(...)`.
   - Do not use `browser.tabs.new()` as the default first move. Opening a new tab can land in the wrong/free account.
   - If no suitable ChatGPT tab is available, ask the user to open `https://chatgpt.com/` in the already logged-in Chrome account/profile, then continue by claiming that tab.
   - If the Chrome plugin route is unavailable or cannot claim a real tab, switch to Computer Use fallback and locate the visible Chrome tab/window instead.
3. Confirm the page is the intended signed-in account and the composer is usable.
   - If login, CAPTCHA, 2FA, or account selection blocks the task, ask the user to complete it.
   - If a ChatGPT modal blocks the composer, close the modal when it is a normal informational modal. Do not accept permission prompts or account changes without explicit user approval.
   - If the user explicitly requested GPT-5.5 Pro, 5.5 Pro, ChatGPT Pro, or a paid ChatGPT website route, inspect only visible page/account/model labels.
   - If the visible page shows `免费版`, a free account, a non-Pro account, or no usable Pro model route, stop and ask the user to switch/open the intended logged-in ChatGPT account in Chrome. Do not continue in the free account.
   - If Pro status is not visible but the user explicitly requires it, stop and ask the user to make the correct Pro account/model visible. Do not treat an unconfirmed route as Pro.
4. Start a new chat inside the verified account only when needed:
   - Prefer the ChatGPT UI's `新聊天` control or `https://chatgpt.com/` in the already claimed/verified tab.
   - Do not open a new browser window or new tab that could switch profiles/accounts.
5. Build a self-contained prompt. Include:
   - The current date.
   - The exact research target and common confusion terms.
   - Required report sections.
   - Source and uncertainty requirements.
   - A unique completion marker on the last line, for example `[[CHATGPT_WEB_RESEARCH_DONE_<uuid>]]`.
6. Enter the prompt.
   - Prefer the visible textbox.
   - If direct `fill` does not stick, use the tab clipboard to paste the prompt, then verify the marker appears in the textbox before sending.
7. Send the prompt from the real page.
8. Poll every 3 minutes while generation is running.
   - Treat `Pro 思考中`, `正在思考`, `正在整理答案`, a visible stop button, or active generation status as still running.
   - If the page is thinking for an hour, keep waiting if answer text has started appearing.
   - If more than one hour passes with no assistant answer text at all, report the stall instead of stopping early.
   - If the page immediately shows `Something went wrong`, click Retry once on the same chat. If it repeats, open a fresh ChatGPT tab and resubmit once.
   - If the user closes the window or the tab disappears, open a fresh ChatGPT tab and resubmit unless the user told you to stop.
9. Completion requires all of these:
   - The stop button is gone or the page no longer shows a running status.
   - The assistant response contains the unique completion marker.
   - The visible response includes the requested report sections or an explicit explanation of unavailable information.
10. Extract the answer from the real page.
   - Prefer the ChatGPT `复制回复` button and read browser clipboard text.
   - Verify the copied text is the assistant answer, not the user prompt. If copied text lacks the answer sections, starts with the submitted prompt, or is much shorter than the visible response, discard it and use DOM extraction.
   - If no reliable copy button is available, extract from the visible DOM/accessibility tree. Prefer `[data-message-author-role="assistant"]` when the ChatGPT DOM exposes it. With Computer Use, use the accessibility tree text nodes for the assistant response and reconstruct Markdown when needed.
   - Verify the copied/extracted text contains the unique completion marker and matches the visible beginning/end. If only an accessibility-tree reconstruction is possible, preserve the key sections, tables, examples, and links; state this extraction method in the report header.
11. Save the output before finalizing.
    - Save long raw page output to `<WORKSPACE>/reports/YYYY-MM-DD-<topic>-chatgpt-web-raw.md`.
    - Save the readable final Markdown report to `<WORKSPACE>/reports/YYYY-MM-DD-<topic>.md`.
    - Remove the marker from the readable report unless the user asked to preserve raw evidence.
    - Include the ChatGPT conversation URL, save time, extraction method, and verification status near the top.
12. Before ending browser work, call Chrome finalization and keep the completed ChatGPT tab as a deliverable only when useful for user review.
    - When using Computer Use fallback, leave the completed ChatGPT tab open unless the user asks to close it.

## Product Research Prompt

Use this shape for product research. Replace bracketed parts.

```text
今天是 <YYYY-MM-DD>。请联网调研产品 <产品名>（注意不要和 <易混淆对象> 混淆），输出中文 Markdown 产品调研报告。

请包含：
1. 一句话结论
2. 产品定位与核心价值
3. 核心功能
4. 目标用户与典型使用场景
5. 工作流/使用方式
6. 价格、套餐与限制
7. 平台支持与下载渠道
8. 竞品对比（至少 4 个）
9. 用户评价/口碑线索
10. 商业化与增长判断
11. 风险、限制与不确定性
12. 适合/不适合推荐给谁
13. 推广或选题角度建议
14. 参考来源链接

要求：
- 结论先行。
- 区分已核验事实、公开资料推断和你的判断。
- 价格、版本、政策、平台支持等易变信息标注核验日期。
- 无法确认的信息直接写“未确认”。
- 给出可追溯来源名称或链接。
- 回答最后单独一行输出：[[CHATGPT_WEB_RESEARCH_DONE_<uuid>]]
```

## Validation Checklist

Before claiming success, verify and report:

- Old/deprecated routes were not used.
- A real ChatGPT website URL produced the answer through either Chrome plugin control or Computer Use fallback.
- The page belonged to the user's intended already logged-in ChatGPT account/profile; it was not a newly opened different/free-account window.
- If the Chrome plugin route failed, the fallback reason was recorded.
- Visible account/model status was checked. If Pro was requested, visible evidence must prove Pro or the run must stop before submission.
- The final visible response contained the unique marker.
- The copied/extracted text contained the same marker.
- Markdown was saved and read back from disk.
- The saved report path is returned to the user.

## Failure Handling

- If Chrome plugin control tools are unavailable, use Computer Use fallback when it can operate the real visible ChatGPT page. Do not produce a substitute research answer from non-ChatGPT sources.
- If ChatGPT is signed out, blocked by CAPTCHA, or waiting for 2FA, ask the user to finish that browser step.
- If only a free ChatGPT account/window is visible when Pro was requested, stop and ask the user to open or switch to the already logged-in Pro account in Chrome.
- If the page generates an incomplete answer without the marker, keep waiting while it is running. If it stops without the marker, retry once.
- If extraction is uncertain, try the copy button, DOM extraction, and accessibility-tree extraction in that order. If still uncertain, ask the user to copy the response from ChatGPT and compare it before using it as the final source.
- If the user explicitly says to wait, obey that wait policy over default timing.
