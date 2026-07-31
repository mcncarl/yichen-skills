const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export function xiaohongshuNoteId(href) {
  if (typeof href !== "string") return null;
  const patterns = [
    /\/user\/profile\/[0-9a-f]{24}\/([0-9a-f]{24})(?:[/?#]|$)/i,
    /\/explore\/([0-9a-f]{24})(?:[/?#]|$)/i,
    /\/discovery\/item\/([0-9a-f]{24})(?:[/?#]|$)/i,
  ];
  for (const pattern of patterns) {
    const match = href.match(pattern);
    if (match) return match[1].toLowerCase();
  }
  return null;
}

export function douyinItem(href) {
  if (typeof href !== "string") return null;
  const match = href.match(/^https?:\/\/(?:www\.)?douyin\.com\/(video|note)\/(\d+)(?:[/?#]|$)|^\/(video|note)\/(\d+)(?:[/?#]|$)/i);
  if (!match) return null;
  const type = (match[1] || match[3]).toLowerCase();
  const id = match[2] || match[4];
  return { id, type, url: `https://www.douyin.com/${type}/${id}` };
}

function positiveInteger(value, fallback) {
  return Number.isInteger(value) && value > 0 ? value : fallback;
}

function boundedNumber(value, fallback, min, max) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, number));
}

export async function collectXiaohongshuBookmarks(tab, options = {}) {
  if (!tab?.playwright || !tab?.cua) throw new Error("A Chrome tab with playwright and cua is required");
  const stableBottomRounds = positiveInteger(options.stableBottomRounds, 4);
  const maxIterations = positiveInteger(options.maxIterations, 80);
  const scrollStep = boundedNumber(options.scrollStep, 550, 100, 1200);
  const scrollWaitMs = boundedNumber(options.scrollWaitMs, 450, 100, 5000);
  const bottomWaitMs = boundedNumber(options.bottomWaitMs, 1200, 200, 10000);
  const topWaitMs = boundedNumber(options.topWaitMs, 150, 50, 2000);
  const seen = new Map();
  const trace = [];
  let stable = 0;
  let labelCount = null;

  if (options.rewind !== false) {
    let rewound = false;
    for (let attempt = 0; attempt < 50; attempt += 1) {
      const position = await tab.playwright.evaluate(() => ({
        scrollTop: scrollY,
        viewportWidth: innerWidth,
        viewportHeight: innerHeight,
      }));
      if (position.scrollTop <= 1) {
        rewound = true;
        break;
      }
      await tab.cua.scroll({
        x: Math.max(1, Math.floor(position.viewportWidth / 2)),
        y: Math.max(1, Math.floor(position.viewportHeight * 0.5)),
        scrollX: 0,
        scrollY: -Math.min(1200, Math.max(100, position.scrollTop)),
      });
      await sleep(topWaitMs);
    }
    if (!rewound) throw new Error("Could not rewind the Xiaohongshu collection to the top");
  }

  for (let index = 0; index < maxIterations && stable < stableBottomRounds; index += 1) {
    const batch = await tab.playwright.evaluate(() => {
      const panels = [...document.querySelectorAll(".feeds-tab-container .transform-container > .tab-content-item")];
      const ranked = panels
        .map((panel) => {
          const rect = panel.getBoundingClientRect();
          const intersection = Math.max(0, Math.min(rect.right, innerWidth) - Math.max(rect.left, 0));
          return { panel, rect, intersection };
        })
        .filter((entry) => entry.rect.height > 10)
        .sort((a, b) => b.intersection - a.intersection);
      const panel = ranked[0]?.panel || document;
      const items = [];
      const patterns = [
        /\/user\/profile\/[0-9a-f]{24}\/([0-9a-f]{24})(?:[/?#]|$)/i,
        /\/explore\/([0-9a-f]{24})(?:[/?#]|$)/i,
        /\/discovery\/item\/([0-9a-f]{24})(?:[/?#]|$)/i,
      ];
      for (const anchor of panel.querySelectorAll("a[href]")) {
        const raw = anchor.getAttribute("href") || "";
        let id = null;
        for (const pattern of patterns) {
          const match = raw.match(pattern);
          if (match) {
            id = match[1].toLowerCase();
            break;
          }
        }
        if (!id) continue;
        const url = raw.startsWith("http") ? raw : `https://www.xiaohongshu.com${raw}`;
        items.push({ id, url });
      }
      const label = [...panel.querySelectorAll("div,span")]
        .map((element) => element.innerText?.trim() || "")
        .find((text) => /^笔记[・·]\d+$/.test(text)) || "";
      const labelMatch = label.match(/(\d+)$/);
      return {
        items,
        label,
        labelCount: labelMatch ? Number(labelMatch[1]) : null,
        url: location.href,
        scrollTop: scrollY,
        scrollHeight: document.documentElement.scrollHeight,
        clientHeight: innerHeight,
        viewportWidth: innerWidth,
        viewportHeight: innerHeight,
      };
    });

    for (const item of batch.items) seen.set(item.id, item.url);
    if (batch.labelCount !== null) labelCount = batch.labelCount;
    const atBottom = batch.scrollTop + batch.clientHeight >= batch.scrollHeight - 5;
    trace.push({
      iteration: index,
      scrollTop: batch.scrollTop,
      scrollHeight: batch.scrollHeight,
      batchCount: new Set(batch.items.map((item) => item.id)).size,
      totalCount: seen.size,
      atBottom,
    });

    if (atBottom) {
      stable += 1;
      await sleep(bottomWaitMs);
    } else {
      stable = 0;
      await tab.cua.scroll({
        x: Math.max(1, Math.floor(batch.viewportWidth / 2)),
        y: Math.max(1, Math.floor(batch.viewportHeight * 0.75)),
        scrollX: 0,
        scrollY: scrollStep,
      });
      await sleep(scrollWaitMs);
    }
  }

  const urls = [...seen.values()];
  return {
    platform: "xiaohongshu",
    count: urls.length,
    labelCount,
    countMismatch: labelCount === null ? null : labelCount - urls.length,
    completed: stable >= stableBottomRounds,
    stableBottomRounds: stable,
    urls,
    trace,
  };
}

export async function collectDouyinFavorites(tab, options = {}) {
  if (!tab?.playwright || !tab?.cua) throw new Error("A Chrome tab with playwright and cua is required");
  const stableBottomRounds = positiveInteger(options.stableBottomRounds, 4);
  const maxIterations = positiveInteger(options.maxIterations, 120);
  const scrollStep = boundedNumber(options.scrollStep, 750, 100, 1500);
  const scrollWaitMs = boundedNumber(options.scrollWaitMs, 400, 100, 5000);
  const bottomWaitMs = boundedNumber(options.bottomWaitMs, 1200, 200, 10000);
  const topWaitMs = boundedNumber(options.topWaitMs, 150, 50, 2000);
  const seen = new Map();
  const trace = [];
  let stable = 0;

  if (options.rewind !== false) {
    let rewound = false;
    for (let attempt = 0; attempt < 80; attempt += 1) {
      const position = await tab.playwright.evaluate(() => {
        const containers = [...document.querySelectorAll("div.route-scroll-container")]
          .map((container) => {
            const rect = container.getBoundingClientRect();
            const area = Math.max(0, Math.min(rect.right, innerWidth) - Math.max(rect.left, 0))
              * Math.max(0, Math.min(rect.bottom, innerHeight) - Math.max(rect.top, 0));
            return { container, rect, area };
          })
          .sort((a, b) => b.area - a.area);
        const selected = containers[0];
        if (!selected?.container) return { error: "route-scroll-container not found" };
        const visibleLeft = Math.max(1, selected.rect.left);
        const visibleRight = Math.min(innerWidth - 2, selected.rect.right);
        const visibleTop = Math.max(1, selected.rect.top);
        const visibleBottom = Math.min(innerHeight - 2, selected.rect.bottom);
        return {
          scrollTop: selected.container.scrollTop,
          targetX: Math.floor((visibleLeft + visibleRight) / 2),
          targetY: Math.floor(visibleTop + (visibleBottom - visibleTop) * 0.5),
        };
      });
      if (position.error) throw new Error(position.error);
      if (position.scrollTop <= 1) {
        rewound = true;
        break;
      }
      await tab.cua.scroll({
        x: Math.max(1, position.targetX),
        y: Math.max(1, position.targetY),
        scrollX: 0,
        scrollY: -Math.min(1500, Math.max(100, position.scrollTop)),
      });
      await sleep(topWaitMs);
    }
    if (!rewound) throw new Error("Could not rewind the Douyin collection to the top");
  }

  for (let index = 0; index < maxIterations && stable < stableBottomRounds; index += 1) {
    const batch = await tab.playwright.evaluate(() => {
      const containers = [...document.querySelectorAll("div.route-scroll-container")]
        .map((container) => {
          const rect = container.getBoundingClientRect();
          const area = Math.max(0, Math.min(rect.right, innerWidth) - Math.max(rect.left, 0))
            * Math.max(0, Math.min(rect.bottom, innerHeight) - Math.max(rect.top, 0));
          return { container, rect, area };
        })
        .sort((a, b) => b.area - a.area);
      const selected = containers[0];
      if (!selected?.container) return { error: "route-scroll-container not found" };
      const items = [];
      for (const anchor of selected.container.querySelectorAll('a[href^="/video/"],a[href^="/note/"]')) {
        const raw = anchor.getAttribute("href") || "";
        const match = raw.match(/^\/(video|note)\/(\d+)(?:[/?#]|$)/i);
        if (!match) continue;
        const type = match[1].toLowerCase();
        const id = match[2];
        items.push({ id, type, url: `https://www.douyin.com/${type}/${id}` });
      }
      const rect = selected.rect;
      const visibleLeft = Math.max(1, rect.left);
      const visibleRight = Math.min(innerWidth - 2, rect.right);
      const visibleTop = Math.max(1, rect.top);
      const visibleBottom = Math.min(innerHeight - 2, rect.bottom);
      return {
        items,
        scrollTop: selected.container.scrollTop,
        scrollHeight: selected.container.scrollHeight,
        clientHeight: selected.container.clientHeight,
        targetX: Math.floor((visibleLeft + visibleRight) / 2),
        targetY: Math.floor(visibleTop + (visibleBottom - visibleTop) * 0.75),
      };
    });
    if (batch.error) throw new Error(batch.error);

    for (const item of batch.items) seen.set(`${item.type}:${item.id}`, item);
    const atBottom = batch.scrollTop + batch.clientHeight >= batch.scrollHeight - 5;
    trace.push({
      iteration: index,
      scrollTop: batch.scrollTop,
      scrollHeight: batch.scrollHeight,
      batchCount: new Set(batch.items.map((item) => `${item.type}:${item.id}`)).size,
      totalCount: seen.size,
      atBottom,
    });

    if (atBottom) {
      stable += 1;
      await sleep(bottomWaitMs);
    } else {
      stable = 0;
      await tab.cua.scroll({
        x: Math.max(1, batch.targetX),
        y: Math.max(1, batch.targetY),
        scrollX: 0,
        scrollY: scrollStep,
      });
      await sleep(scrollWaitMs);
    }
  }

  const items = [...seen.values()];
  return {
    platform: "douyin",
    count: items.length,
    typeCounts: {
      video: items.filter((item) => item.type === "video").length,
      note: items.filter((item) => item.type === "note").length,
    },
    completed: stable >= stableBottomRounds,
    stableBottomRounds: stable,
    urls: items.map((item) => item.url),
    trace,
  };
}

export async function writeUrlFile(filePath, urls, options = {}) {
  if (typeof filePath !== "string" || !filePath.trim()) throw new Error("filePath is required");
  if (!Array.isArray(urls)) throw new Error("urls must be an array");
  const unique = [...new Set(urls.filter((url) => typeof url === "string" && url.trim()).map((url) => url.trim()))];
  const { mkdir, writeFile } = await import("node:fs/promises");
  const { dirname } = await import("node:path");
  await mkdir(dirname(filePath), { recursive: true });
  await writeFile(filePath, `${unique.join("\n")}\n`, { encoding: "utf8", flag: options.overwrite ? "w" : "wx" });
  return { filePath, count: unique.length };
}
