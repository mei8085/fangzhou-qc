#!/usr/bin/env node
// 起每个模型的 dev server，截各自的 vite 报错 overlay 作为复测证据。
//
// 适用场景：source 包自带 env 残缺（缺脚手架目录、缺主题/i18n 插件注册、
// 锁版本与源码 import 路径漂移），离线起 dev 报错。这种情况下不要硬修源码包，
// 直接用这个脚本给每个模型截一张 vite 报错 overlay，作为「项目跑不起来」的证据，
// 评估走代码读路线，备注里写明「项目跑不起来与本题代码无关」。
//
// 输出：delivery/<TASK_ID>/screenshots/<COL>_01_blocker.png
//
// 用法：
//   node screenshot_blocker.js <TASK_ID> [--only COL] [--base-port 5190]
//                              [--route /#/dashboard/index]
//                              [--overlay-timeout 30000]
//
// 注意：每个模型起独立 vite dev server，端口逐 1 递增；测完会 kill 进程树。

const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const REPO_ROOT = path.resolve(HERE, '..', '..', '..');

function parseArgs(argv) {
  const out = {
    id: null, only: null, basePort: 5190,
    route: '/#/dashboard/index', overlayTimeout: 30000,
  };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--only') out.only = argv[++i];
    else if (a === '--base-port') out.basePort = parseInt(argv[++i], 10);
    else if (a === '--route') out.route = argv[++i];
    else if (a === '--overlay-timeout') out.overlayTimeout = parseInt(argv[++i], 10);
    else out.id = a;
  }
  if (!out.id) {
    console.error('usage: screenshot_blocker.js <TASK_ID> [--only COL] [--base-port N] [--route PATH] [--overlay-timeout MS]');
    process.exit(2);
  }
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
    const onData = (chunk) => {
      buf += chunk.toString();
      const m = stripAnsi(buf).match(/Local:\s*(https?:\/\/[^\s]+?\/)/);
      if (m) {
        child.stdout.off('data', onData);
        child.stderr.off('data', onErr);
        resolve(m[1]);
      }
    };
    const onErr = (chunk) => { buf += chunk.toString(); };
    child.stdout.on('data', onData);
    child.stderr.on('data', onErr);
    const t = setTimeout(() => {
      reject(new Error(`vite did not print Local: URL within ${timeoutMs}ms. last:\n${buf.slice(-600)}`));
    }, timeoutMs);
    child.on('exit', code => {
      clearTimeout(t);
      reject(new Error(`vite exited with code ${code}. last:\n${buf.slice(-600)}`));
    });
  });
}

function pickViteBin(entryDir) {
  const cand = process.platform === 'win32'
    ? ['vite.CMD', 'vite.cmd']
    : ['vite'];
  for (const name of cand) {
    const p = path.join(entryDir, 'node_modules', '.bin', name);
    if (fs.existsSync(p)) return p;
  }
  throw new Error(`no vite shim in ${entryDir}/node_modules/.bin — run pnpm install first`);
}

async function captureOne(browser, col, info, port, outDir, taskId, route, overlayTimeout) {
  const tag = sanitize(col);
  const out = path.join(outDir, `${tag}_01_blocker.png`);
  const entry = info.entry || '.';
  const entryDir = path.join(REPO_ROOT, 'tasks', taskId, 'extracted', info.code, entry === '.' ? '' : entry);
  console.log(`==> ${col} (${info.code}) port=${port}`);

  let viteBin;
  try { viteBin = pickViteBin(entryDir); }
  catch (e) { console.error(`   [skip] ${e.message}`); return; }

  const cmd = `"${viteBin}" --port ${port} --strictPort`;
  const child = spawn(cmd, { cwd: entryDir, shell: true, windowsHide: true });
  let url;
  try {
    url = await waitForViteUrl(child);
  } catch (e) {
    console.error(`   [err] dev start: ${e.message.slice(0, 400)}`);
    killTree(child.pid);
    return;
  }
  console.log(`   vite up at ${url}`);

  const ctx = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 1,
  });
  const page = await ctx.newPage();
  page.on('pageerror', e => console.log(`   [pageerror] ${e.message.slice(0, 200)}`));
  try {
    const targetUrl = `${url.replace(/\/$/, '')}${route}`;
    await page.goto(targetUrl, { waitUntil: 'load', timeout: 60000 });
    let captured = false;
    try {
      await page.waitForSelector('vite-error-overlay', { timeout: overlayTimeout });
      await page.waitForTimeout(1500);
      await page.screenshot({ path: out, fullPage: false });
      console.log(`   saved ${path.basename(out)} (vite overlay)`);
      captured = true;
    } catch {}
    if (!captured) {
      // 没有 vite overlay 也截一张，可能是浏览器侧 runtime 报错（白屏 + console 报错）
      await page.waitForTimeout(2500);
      await page.screenshot({ path: out, fullPage: false });
      console.log(`   saved ${path.basename(out)} (fallback, no overlay)`);
    }
  } catch (e) {
    console.error(`   [err] capture: ${e.message.slice(0, 200)}`);
    try {
      await page.screenshot({ path: out, fullPage: false });
      console.log(`   saved ${path.basename(out)} (fallback after err)`);
    } catch {}
  } finally {
    await ctx.close();
    killTree(child.pid);
    await new Promise(r => setTimeout(r, 1500));
  }
}

async function main() {
  const args = parseArgs(process.argv);
  const mapPath = path.join(REPO_ROOT, 'tasks', args.id, 'model_map.json');
  if (!fs.existsSync(mapPath)) { console.error(`no ${mapPath}`); process.exit(2); }
  const map = JSON.parse(fs.readFileSync(mapPath, 'utf8'));
  const outDir = path.join(REPO_ROOT, 'delivery', args.id, 'screenshots');
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  let port = args.basePort;
  for (const [col, info] of Object.entries(map.models)) {
    if (args.only && col !== args.only) continue;
    await captureOne(browser, col, info, port, outDir, args.id, args.route, args.overlayTimeout);
    port += 1;
  }
  await browser.close();
}
main().catch(e => { console.error(e); process.exit(1); });
