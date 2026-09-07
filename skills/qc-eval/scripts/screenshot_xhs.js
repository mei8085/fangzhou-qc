#!/usr/bin/env node
// Task YGKVWF (vue-xiaohongshu 前端高频操作性能优化) 专用：
// 每个模型起独立 vite dev server，截取
//   01_initial  首屏首页
//   02_search   在搜索框输入关键词并回车后
// 需要后端 homefeedsapi 已经在 127.0.0.1:8000 运行（source/main.py + uvicorn）。

const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { preferredPortBase } = require('./lib/concurrency');

const HERE = __dirname;
const REPO_ROOT = path.resolve(HERE, '..', '..', '..');

function parseArgs(argv) {
  const out = { id: null, only: null, basePort: null, keyword: '旅行' };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--only') out.only = argv[++i];
    else if (a === '--base-port') out.basePort = parseInt(argv[++i], 10);
    else if (a === '--keyword') out.keyword = argv[++i];
    else out.id = a;
  }
  if (!out.id) { console.error('usage: screenshot_xhs.js <TASK_ID> [--only COL] [--base-port N] [--keyword KW]'); process.exit(2); }
  return out;
}

function stripAnsi(s) { return s.replace(/\x1b\[[0-9;]*m/g, ''); }
function sanitize(s) { return s.replace(/[^A-Za-z0-9._-]+/g, '_'); }
function killTree(pid) {
  if (!pid) return;
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/F', '/T', '/PID', String(pid)], { stdio: 'ignore' });
  } else {
    try { process.kill(-pid); } catch {}
    try { process.kill(pid); } catch {}
  }
}

async function waitForViteUrl(child, timeoutMs = 90000) {
  return new Promise((resolve, reject) => {
    let buf = '';
    const to = setTimeout(() => { reject(new Error('vite start timeout: ' + buf.slice(-400))); }, timeoutMs);
    const onData = (d) => {
      buf += stripAnsi(d.toString());
      const m = buf.match(/Local:\s+(http:\/\/[^\s]+)/);
      if (m) { clearTimeout(to); resolve(m[1]); }
    };
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
    child.on('exit', code => { clearTimeout(to); reject(new Error('vite exited early code=' + code + '\n' + buf.slice(-400))); });
  });
}

function pickViteBin(entryDir) {
  const cands = [
    path.join(entryDir, 'node_modules', '.bin', process.platform === 'win32' ? 'vite.cmd' : 'vite'),
    path.join(entryDir, 'node_modules', '.bin', 'vite'),
  ];
  for (const c of cands) if (fs.existsSync(c)) return c;
  throw new Error('vite bin not found in ' + entryDir);
}

async function captureOne(browser, col, info, port, outDir, taskId, keyword) {
  const tag = sanitize(col);
  const entry = info.entry === '.' ? '' : `/${info.entry}`;
  const entryDir = path.join(REPO_ROOT, 'tasks', taskId, 'extracted', info.code, info.entry === '.' ? '' : info.entry);

  console.log(`\n==> ${col} (${info.code}) port=${port}`);

  let viteBin;
  try { viteBin = pickViteBin(entryDir); }
  catch (e) { console.error('   [skip] ' + e.message); return; }

  const cmd = `"${viteBin}" --port ${port} --strictPort`;
  const child = spawn(cmd, { cwd: entryDir, shell: true, windowsHide: true });
  let url;
  try { url = await waitForViteUrl(child); }
  catch (e) { console.error('   [err] dev start: ' + e.message.slice(0, 400)); killTree(child.pid); return; }
  console.log('   vite up at ' + url);

  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  page.on('pageerror', e => console.log('   [pageerror] ' + e.message.slice(0, 200)));
  try {
    await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(1500);
    const out1 = path.join(outDir, `${tag}_01_initial.png`);
    await page.screenshot({ path: out1, fullPage: false });
    console.log('   saved ' + path.basename(out1));

    // 输入关键词到搜索框
    const input = await page.$('input.search-input');
    if (input) {
      await input.click();
      await input.fill('');
      await page.keyboard.type(keyword, { delay: 40 });
      await page.waitForTimeout(600);
      await page.keyboard.press('Enter');
      await page.waitForTimeout(2000);
      const out2 = path.join(outDir, `${tag}_02_search.png`);
      await page.screenshot({ path: out2, fullPage: false });
      console.log('   saved ' + path.basename(out2));
    } else {
      console.log('   [warn] search-input not found');
    }
  } catch (e) {
    console.error('   [err] capture: ' + e.message.slice(0, 200));
  } finally {
    await ctx.close();
    killTree(child.pid);
    await new Promise(r => setTimeout(r, 1500));
  }
}

async function main() {
  const args = parseArgs(process.argv);
  const mapPath = path.join(REPO_ROOT, 'tasks', args.id, 'model_map.json');
  if (!fs.existsSync(mapPath)) { console.error('no ' + mapPath); process.exit(2); }
  const map = JSON.parse(fs.readFileSync(mapPath, 'utf8'));
  const outDir = path.join(REPO_ROOT, 'delivery', args.id, 'screenshots');
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  let port = args.basePort ?? preferredPortBase(args.id, 'screenshot-xhs', 8);
  for (const [col, info] of Object.entries(map.models)) {
    if (args.only && col !== args.only) continue;
    await captureOne(browser, col, info, port, outDir, args.id, args.keyword);
    port += 1;
  }
  await browser.close();
}
main().catch(e => { console.error(e); process.exit(1); });
