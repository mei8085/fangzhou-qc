#!/usr/bin/env node
// FastAPI dashboard screenshot helper：起每个模型的 uvicorn server，
// 各截 2 张：01_initial（首页加载完）、02_query_or_history（尽力调一次 NL query 或 history 接口后再截一次）。
//
// 用法：node screenshot_fastapi.js <TASK_ID> [--only COL] [--base-port 8100] [--keep-existing]

const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { preferredPortBase } = require('./lib/concurrency');

const HERE = __dirname;
const REPO_ROOT = path.resolve(HERE, '..', '..', '..');

function parseArgs(argv) {
  const out = { id: null, only: null, basePort: null, keep: false };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--only') out.only = argv[++i];
    else if (a === '--base-port') out.basePort = parseInt(argv[++i], 10);
    else if (a === '--keep-existing') out.keep = true;
    else out.id = a;
  }
  if (!out.id) {
    console.error('usage: screenshot_fastapi.js <TASK_ID> [--only COL] [--base-port 8100]');
    process.exit(2);
  }
  return out;
}

function sanitize(s) { return s.replace(/[^A-Za-z0-9._-]+/g, '_'); }

function findEntryDir(taskId, code) {
  const root = path.join(REPO_ROOT, 'tasks', taskId, 'extracted', code);
  const sub = path.join(root, 'ai-data-dashboard');
  if (fs.existsSync(path.join(sub, 'main.py'))) return sub;
  return root;
}

async function waitForHttp(url, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const r = await fetch(url, { method: 'GET' });
      if (r.status < 500) return true;
    } catch (e) {}
    await new Promise(r => setTimeout(r, 500));
  }
  return false;
}

function killTree(pid) {
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/F', '/T', '/PID', String(pid)]);
  } else {
    try { process.kill(-pid, 'SIGKILL'); } catch (e) {}
  }
}

async function screenshotOne(taskId, col, code, port, outDir) {
  const cwd = findEntryDir(taskId, code);
  if (!fs.existsSync(path.join(cwd, 'main.py'))) {
    console.error(`  [${col}] no main.py in ${cwd}, skipping`);
    return false;
  }
  console.error(`  [${col}] starting uvicorn on :${port}  cwd=${cwd}`);
  const python = process.platform === 'win32' ? 'python' : 'python3';
  const child = spawn(python, ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(port)], {
    cwd, stdio: ['ignore', 'pipe', 'pipe'], shell: false,
    detached: process.platform !== 'win32',
  });
  let logBuf = '';
  child.stdout.on('data', d => { logBuf += d.toString(); });
  child.stderr.on('data', d => { logBuf += d.toString(); });

  const ok = await waitForHttp(`http://127.0.0.1:${port}/`, 30000);
  if (!ok) {
    console.error(`  [${col}] server did not come up. last:\n${logBuf.slice(-800)}`);
    killTree(child.pid);
    return false;
  }
  await new Promise(r => setTimeout(r, 1200));

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: 'networkidle', timeout: 20000 });
  } catch (e) {
    console.error(`  [${col}] page.goto error: ${e.message}`);
  }
  await new Promise(r => setTimeout(r, 1500));
  const p1 = path.join(outDir, `${sanitize(col)}_01_initial.png`);
  await page.screenshot({ path: p1, fullPage: true });
  console.error(`  [${col}] saved ${path.basename(p1)}`);

  let p2 = null;
  try {
    const histResp = await page.evaluate(async () => {
      try {
        const r = await fetch('/api/history');
        return { ok: r.ok, status: r.status, body: (await r.text()).slice(0, 500) };
      } catch (e) { return { ok: false, error: String(e) }; }
    });
    p2 = path.join(outDir, `${sanitize(col)}_02_api.png`);
    await page.evaluate(({ resp }) => {
      const pre = document.createElement('pre');
      pre.textContent = 'GET /api/history -> ' + JSON.stringify(resp, null, 2);
      pre.style.cssText = 'position:fixed;left:8px;top:8px;background:#111;color:#0f0;padding:12px;font:12px/1.5 monospace;z-index:99999;max-width:560px;border:1px solid #0f0;';
      document.body.appendChild(pre);
    }, { resp: histResp });
    await page.screenshot({ path: p2, fullPage: true });
    console.error(`  [${col}] saved ${path.basename(p2)}`);
  } catch (e) {
    console.error(`  [${col}] api probe failed: ${e.message}`);
  }
  await browser.close();
  killTree(child.pid);
  await new Promise(r => setTimeout(r, 500));
  return true;
}

async function main() {
  const args = parseArgs(process.argv);
  const taskId = args.id;
  const mapPath = path.join(REPO_ROOT, 'tasks', taskId, 'model_map.json');
  const map = JSON.parse(fs.readFileSync(mapPath, 'utf-8'));
  const outDir = path.join(REPO_ROOT, 'delivery', taskId, 'screenshots');
  fs.mkdirSync(outDir, { recursive: true });

  const entries = Object.entries(map.models).filter(([col]) => !args.only || col === args.only);
  const basePort = args.basePort ?? preferredPortBase(taskId, 'screenshot-fastapi', 8);
  let i = 0;
  for (const [col, info] of entries) {
    const port = basePort + i;
    i++;
    try {
      await screenshotOne(taskId, col, info.code, port, outDir);
    } catch (e) {
      console.error(`  [${col}] ERROR ${e.message}`);
    }
  }
}

main().catch(e => { console.error(e); process.exit(1); });
