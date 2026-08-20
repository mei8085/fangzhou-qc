#!/usr/bin/env node
// Start each model's Umi frontend and capture a real browser screenshot.
// This is for React/Umi projects where the runnable app lives under ui/.

const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const REPO_ROOT = path.resolve(HERE, '..', '..', '..');

function parseArgs(argv) {
  const out = { id: null, route: '/user/login', timeout: 180000 };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--route') out.route = argv[++i];
    else if (a === '--timeout') out.timeout = Number(argv[++i]);
    else out.id = a;
  }
  if (!out.id) {
    console.error('usage: screenshot_umi_runtime.js <TASK_ID> [--route /user/login]');
    process.exit(2);
  }
  return out;
}

function stripAnsi(s) {
  return s.replace(/\x1b\[[0-9;]*m/g, '');
}

function tagOf(col) {
  return col.replace(/ /g, '_');
}

function killTree(pid) {
  if (!pid) return;
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/F', '/T', '/PID', String(pid)], { stdio: 'ignore' });
  } else {
    try { process.kill(-pid); } catch {}
    try { process.kill(pid); } catch {}
  }
}

function findUiDir(taskId, code, entry) {
  const base = path.join(REPO_ROOT, 'tasks', taskId, 'extracted', code, entry || '.');
  const direct = path.join(base, 'package.json');
  const nested = path.join(base, 'ui', 'package.json');
  if (fs.existsSync(direct)) return base;
  if (fs.existsSync(nested)) return path.join(base, 'ui');
  return null;
}

function waitForUrl(child, timeoutMs) {
  return new Promise((resolve, reject) => {
    let buf = '';
    const timer = setTimeout(() => {
      reject(new Error(`dev server did not become ready within ${timeoutMs}ms\n${stripAnsi(buf).slice(-2000)}`));
    }, timeoutMs);
    const onData = (chunk) => {
      buf += chunk.toString();
      const clean = stripAnsi(buf);
      const m = clean.match(/Local:\s*(http:\/\/(?:localhost|127\.0\.0\.1):\d+\/?)/i);
      if (m) {
        clearTimeout(timer);
        resolve(m[1].replace(/\/$/, ''));
      }
    };
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
    child.on('exit', (code) => {
      clearTimeout(timer);
      reject(new Error(`dev server exited with ${code}\n${stripAnsi(buf).slice(-2000)}`));
    });
  });
}

async function captureOne(browser, taskId, col, info, route, timeout) {
  const outDir = path.join(REPO_ROOT, 'delivery', taskId, 'screenshots');
  fs.mkdirSync(outDir, { recursive: true });
  const routeTag = route.replace(/^\/+/, '').replace(/[\\/:*?"<>|]+/g, '_') || 'home';
  const out = path.join(outDir, `${tagOf(col)}_01_runtime_${routeTag}.png`);
  if (info.artifact_missing) {
    console.log(`==> ${col}: skip, artifact missing`);
    return;
  }
  const uiDir = findUiDir(taskId, info.code, info.entry || '.');
  if (!uiDir) {
    console.log(`==> ${col}: skip, no package.json`);
    return;
  }
  console.log(`==> ${col} (${info.code}) cwd=${path.relative(REPO_ROOT, uiDir)}`);
  const child = spawn('npm.cmd run start:no-mock', {
    cwd: uiDir,
    shell: true,
    windowsHide: true,
  });
  try {
    const url = await waitForUrl(child, timeout);
    const ctx = await browser.newContext({ viewport: { width: 1365, height: 768 }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    const target = `${url}${route.startsWith('/') ? route : `/${route}`}`;
    await page.goto(target, { waitUntil: 'load', timeout: 90000 }).catch(async () => {
      await page.waitForLoadState('domcontentloaded', { timeout: 30000 }).catch(() => {});
    });
    await page.waitForFunction(
      () => !document.body?.innerText?.includes('Bundling'),
      { timeout: 180000 }
    ).catch(() => {});
    await page.waitForTimeout(2000);
    await page.screenshot({ path: out, fullPage: false });
    await ctx.close();
    console.log(`   saved ${path.relative(REPO_ROOT, out)}`);
  } catch (e) {
    console.error(`   [err] ${e.message}`);
  } finally {
    killTree(child.pid);
    await new Promise((r) => setTimeout(r, 1000));
  }
}

async function main() {
  const args = parseArgs(process.argv);
  const mapPath = path.join(REPO_ROOT, 'tasks', args.id, 'model_map.json');
  const mm = JSON.parse(fs.readFileSync(mapPath, 'utf8'));
  const browser = await chromium.launch({ headless: true });
  for (const col of mm.sheet_columns || Object.keys(mm.models)) {
    if (!mm.models[col]) continue;
    await captureOne(browser, args.id, col, mm.models[col], args.route, args.timeout);
  }
  await browser.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
