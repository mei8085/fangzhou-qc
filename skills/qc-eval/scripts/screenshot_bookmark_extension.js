#!/usr/bin/env node
// Screenshot 24期 Chrome bookmark-extension sidepanel tasks with a mocked
// chrome.bookmarks/chrome.storage runtime.
// Usage: node skills/qc-eval/scripts/screenshot_bookmark_extension.js <TASK_ID>

const { chromium } = require('playwright');
const fs = require('fs');
const http = require('http');
const path = require('path');

const HERE = __dirname;
const REPO_ROOT = path.resolve(HERE, '..', '..', '..');

const SAMPLE_BOOKMARKS = [
  { id: '101', title: 'React 官方文档', url: 'https://react.dev/' },
  { id: '102', title: 'Vite 构建指南', url: 'https://vitejs.dev/guide/' },
  { id: '103', title: 'Chrome Extensions MV3', url: 'https://developer.chrome.com/docs/extensions/' },
  { id: '104', title: 'Web 性能优化清单', url: 'https://web.dev/performance/' },
  { id: '105', title: 'TypeScript Handbook', url: 'https://www.typescriptlang.org/docs/' },
  { id: '106', title: 'Zustand 状态管理', url: 'https://zustand-demo.pmnd.rs/' },
];

function storageSeed(code) {
  const map = {
    '101': ['React', '前端'],
    '102': ['构建工具', '前端'],
    '103': ['扩展开发', '浏览器'],
    '104': ['性能优化', '前端'],
    '105': ['TypeScript', '前端'],
    '106': ['状态管理', 'React'],
  };
  if (code === 'C16BS') return { 'bookmark-tags-storage': map };
  if (code === 'LA21H') {
    const tags = [
      { id: 't_react', name: 'React', color: '#3b82f6' },
      { id: 't_frontend', name: '前端', color: '#22c55e' },
      { id: 't_perf', name: '性能优化', color: '#f97316' },
      { id: 't_ext', name: '扩展开发', color: '#8b5cf6' },
      { id: 't_ts', name: 'TypeScript', color: '#0ea5e9' },
    ];
    return {
      bookmark_tags_definitions: tags,
      bookmark_tags_mapping: {
        '101': ['t_react', 't_frontend'],
        '102': ['t_frontend'],
        '103': ['t_ext'],
        '104': ['t_perf', 't_frontend'],
        '105': ['t_ts', 't_frontend'],
        '106': ['t_react'],
      },
    };
  }
  if (code === '1PFMT') return { 'bookmark-tags': map };
  return { bookmark_tags: map };
}

function mockChromeScript(seed) {
  return `
(() => {
  const store = ${JSON.stringify(seed)};
  const listeners = new Set();
  const sampleBookmarks = ${JSON.stringify(SAMPLE_BOOKMARKS)};
  const tree = [{
    id: '0',
    title: '',
    children: [{
      id: '1',
      title: '书签栏',
      children: sampleBookmarks.map((b, index) => ({ ...b, parentId: '1', index, dateAdded: Date.now() - index * 10000 }))
    }]
  }];
  const asResult = (keys) => {
    if (keys == null) return { ...store };
    if (typeof keys === 'string') return { [keys]: store[keys] };
    if (Array.isArray(keys)) {
      const out = {};
      for (const k of keys) out[k] = store[k];
      return out;
    }
    if (typeof keys === 'object') {
      const out = {};
      for (const [k, v] of Object.entries(keys)) out[k] = store[k] === undefined ? v : store[k];
      return out;
    }
    return {};
  };
  window.chrome = {
    runtime: { lastError: null, getURL: (p) => p },
    storage: {
      onChanged: {
        addListener: (fn) => listeners.add(fn),
        removeListener: (fn) => listeners.delete(fn)
      },
      local: {
        get: (keys, cb) => {
          const out = asResult(keys);
          if (typeof cb === 'function') cb(out);
          return Promise.resolve(out);
        },
        set: (items, cb) => {
          const changes = {};
          for (const [k, v] of Object.entries(items || {})) {
            changes[k] = { oldValue: store[k], newValue: v };
            store[k] = v;
          }
          for (const fn of listeners) fn(changes, 'local');
          if (typeof cb === 'function') cb();
          return Promise.resolve();
        },
        remove: (keys, cb) => {
          for (const k of Array.isArray(keys) ? keys : [keys]) delete store[k];
          if (typeof cb === 'function') cb();
          return Promise.resolve();
        }
      }
    },
    bookmarks: {
      getTree: (cb) => {
        const cloned = JSON.parse(JSON.stringify(tree));
        if (typeof cb === 'function') cb(cloned);
        return Promise.resolve(cloned);
      },
      search: (query, cb) => {
        const q = typeof query === 'string' ? query.toLowerCase() : String(query?.title || query?.url || '').toLowerCase();
        const hits = sampleBookmarks.filter((b) => b.title.toLowerCase().includes(q) || b.url.toLowerCase().includes(q));
        if (typeof cb === 'function') cb(hits);
        return Promise.resolve(hits);
      },
      update: (id, changes, cb) => {
        const b = sampleBookmarks.find((x) => x.id === id) || { id };
        Object.assign(b, changes);
        if (typeof cb === 'function') cb(b);
        return Promise.resolve(b);
      },
      create: (node, cb) => {
        const b = { id: String(Date.now()), title: node.title, url: node.url, parentId: node.parentId || '1' };
        sampleBookmarks.push(b);
        tree[0].children[0].children.push(b);
        if (typeof cb === 'function') cb(b);
        return Promise.resolve(b);
      },
      move: (id, dest, cb) => {
        const b = sampleBookmarks.find((x) => x.id === id) || { id };
        b.parentId = dest.parentId;
        if (typeof cb === 'function') cb(b);
        return Promise.resolve(b);
      },
      remove: (id, cb) => {
        if (typeof cb === 'function') cb();
        return Promise.resolve();
      }
    }
  };
})();
`;
}

function startStaticServer(root) {
  const server = http.createServer((req, res) => {
    const urlPath = decodeURIComponent((req.url || '/').split('?')[0]);
    const rel = urlPath === '/' ? '/src/sidepanel/index.html' : urlPath;
    const target = path.normalize(path.join(root, rel));
    if (!target.startsWith(root)) {
      res.writeHead(403).end('forbidden');
      return;
    }
    fs.readFile(target, (err, data) => {
      if (err) {
        res.writeHead(404).end('not found');
        return;
      }
      const ext = path.extname(target).toLowerCase();
      const type = ext === '.html' ? 'text/html' : ext === '.js' ? 'text/javascript' : ext === '.css' ? 'text/css' : 'application/octet-stream';
      res.writeHead(200, { 'content-type': type });
      res.end(data);
    });
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

async function clickTagsTab(page) {
  const candidates = [
    'button:has-text("标签管理")',
    'button:has-text("标签")',
    'text=标签管理',
    'text=标签',
  ];
  for (const sel of candidates) {
    try {
      const loc = page.locator(sel).first();
      if (await loc.count()) {
        await loc.click({ timeout: 2000 });
        return;
      }
    } catch (_) {}
  }
}

async function shoot(taskId, col, code) {
  const dist = path.join(REPO_ROOT, 'tasks', taskId, 'extracted', code, 'dist');
  if (!fs.existsSync(path.join(dist, 'src', 'sidepanel', 'index.html'))) {
    console.warn(`  [skip] ${col} (${code}) no built sidepanel`);
    return;
  }
  const outDir = path.join(REPO_ROOT, 'delivery', taskId, 'screenshots');
  fs.mkdirSync(outDir, { recursive: true });
  const safe = col.replace(/[^A-Za-z0-9._-]+/g, '_');
  const server = await startStaticServer(dist);
  const port = server.address().port;
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ viewport: { width: 430, height: 920 }, deviceScaleFactor: 1 });
    await context.addInitScript(mockChromeScript(storageSeed(code)));
    const page = await context.newPage();
    await page.goto(`http://127.0.0.1:${port}/src/sidepanel/index.html`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1200);
    await page.screenshot({ path: path.join(outDir, `${safe}_01_home.png`), fullPage: true });
    await clickTagsTab(page);
    await page.waitForTimeout(1200);
    await page.screenshot({ path: path.join(outDir, `${safe}_02_tags.png`), fullPage: true });
    for (const label of ['React', '前端', '性能优化']) {
      try {
        const loc = page.locator(`button:has-text("${label}")`).first();
        if (await loc.count()) {
          await loc.click({ timeout: 1500 });
          break;
        }
      } catch (_) {}
    }
    try {
      const search = page.locator('input[placeholder*="搜索书签"]').first();
      if (await search.count()) {
        await search.fill('React');
      }
    } catch (_) {}
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(outDir, `${safe}_03_filter.png`), fullPage: true });
    await context.close();
  } finally {
    await browser.close();
    server.close();
  }
}

async function main() {
  const taskId = process.argv[2];
  if (!taskId) {
    console.error('usage: screenshot_bookmark_extension.js <TASK_ID>');
    process.exit(2);
  }
  const map = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, 'tasks', taskId, 'model_map.json'), 'utf8'));
  for (const col of map.sheet_columns || Object.keys(map.models)) {
    const info = map.models[col];
    console.log(`  [${col}] ${info.code}`);
    await shoot(taskId, col, info.code);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
