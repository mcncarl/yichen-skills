---
name: xianyu-roi-qa
description: |
  QA and fix Xianyu rental ROI web apps, especially React/Vite + Node/SQLite projects with product refresh APIs, investment calculators, Recharts dashboards, and local source-tree confusion.
  Use when the user asks to test, debug, optimize, or make refreshable a Xianyu/second-hand rental ROI website.
---

# Xianyu ROI QA

Use this skill to test and harden Xianyu rental ROI apps end to end: find the real source tree, verify refreshable market data, test investment calculations, and catch frontend chart/layout bugs.

## When To Use

- The user mentions 闲鱼, 咸鱼, 二手租赁, 投资回报率, ROI, IRR, 选品, or rental product dashboards.
- The project has a React/Vite frontend plus Node/Express backend.
- Data should refresh by clicking a button or through scheduled backend updates.
- Charts use Recharts or similar responsive chart containers.
- The visible project folder may be an empty wrapper rather than the real editable source.

## Workflow

1. Find the real source tree.
   - Check the current directory first: `pwd`, `find . -maxdepth 2 -name package.json`.
   - If it is an empty wrapper, search likely user folders for `package.json`, `vite.config.*`, `backend/package.json`, and files such as `investmentCalculator`.
   - Do not edit wrapper folders unless they contain the real app.
2. Read project docs and state.
   - Read `AGENTS.md`, `README*`, `tasks.md`, `package.json`, `backend/package.json`, `vite.config.*`, and route/service files around products and calculations.
   - Run `git status -sb` if the source tree is a Git repo.
3. Establish the runtime.
   - If backend depends on `better-sqlite3`, prefer Node 22. Check `.nvmrc`, `.node-version`, `engines`, and the actual `node --version`.
   - Avoid killing unrelated dev servers. Check ports with `lsof -nP -iTCP:<port> -sTCP:LISTEN`.
4. Run static checks and builds.
   - Typical commands: `npm run lint`, `npx tsc -b --pretty false`, `cd backend && npm run build`, `npm run build`.
   - Treat Browserslist stale data as maintenance unless it blocks the build.
5. Start local services.
   - Backend usually runs on `3001`; frontend on Vite `5173` or the next free port.
   - If `5173` is occupied by another project, use `5174`.
6. Probe data refresh.
   - Use `scripts/qa_probe.py` to check repo shape and running endpoints.
   - Manually test `GET /api/products`, `GET /api/products/refresh/status`, and `POST /api/products/refresh` when safe.
   - Confirm the UI refresh button updates status text and does not leave stale calculations.
7. Browser-test the core flow.
   - Load market table and confirm products render.
   - Click refresh and wait for success status.
   - Change budget, hold years, risk level, and funding/reinvestment settings.
   - Open portfolio and analysis tabs.
   - Check for failed requests, console errors, `NaN`, blank charts, and mobile overflow.
8. Fix bugs in small patches.
   - Preserve existing app patterns.
   - Keep calculation fixes covered by type/build/browser verification.
   - For Recharts inside Tabs, ensure active chart panels have explicit nonzero dimensions.
9. Retest and summarize.
   - Rerun the relevant checks.
   - Stop local test servers before finishing unless the user wants a running URL.
   - Report cause, files changed, verification, and remaining risks.

## Common Bugs And Fix Patterns

### Recharts renders blank inside Tabs

Symptoms:
- Chart title is visible, but no chart SVG is rendered.
- Console warns that chart width or height is `0`.

Fix:
- Give the active chart panel explicit height and prevent flex shrink.
- Add a minimum height to `ResponsiveContainer`.

Example:

```tsx
const chartPanelClassName = 'h-[350px] min-h-[350px] flex-none';

<TabsContent value="yearly" className={chartPanelClassName}>
  <ResponsiveContainer width="100%" height="100%" minHeight={350}>
    {/* chart */}
  </ResponsiveContainer>
</TabsContent>
```

### `better-sqlite3` native module mismatch

Symptoms:
- Backend crashes with a `NODE_MODULE_VERSION` mismatch.
- TypeScript build may pass, but runtime fails.

Fix:
- Use the Node major version that compiled the native module, usually Node 22 for this project family.
- Add or verify `.nvmrc`, `.node-version`, and `package.json` engines.

### Refresh works in backend but UI stays stale

Check:
- `POST /api/products/refresh` returns the refreshed product list and metadata.
- Frontend replaces `products`, updates refresh metadata, and recalculates portfolio from current config.
- Comparison calculations receive the full current config, not only budgets.

### Hold-year labels are wrong

Check:
- Net profit labels should follow selected hold years, for example `2年净利润`.
- Residual value should be applied at the selected exit year, not always year 3 unless the model intentionally does that.

## Probe Script

Run from the skill repository or copy the script path:

```bash
python3 xianyu-roi-qa/scripts/qa_probe.py --root /path/to/app --backend-url http://127.0.0.1:3001 --frontend-url http://127.0.0.1:5174
```

Useful options:

```bash
python3 xianyu-roi-qa/scripts/qa_probe.py --root /path/to/app --post-refresh
python3 xianyu-roi-qa/scripts/qa_probe.py --root /path/to/app --json
```

The script does not install dependencies, start servers, or modify files. It only inspects local files and reachable HTTP endpoints.

## Final Report Shape

When finishing a QA/fix task, use concise Chinese headings when the user writes in Chinese:

- `问题原因`
- `我做了哪些改动`
- `改动后效果`
- `建议下一步`

Include exact commands/checks run and mention any checks that were skipped or blocked.
