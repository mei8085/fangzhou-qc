#!/usr/bin/env node
// 通用后台管理页复测截图：启动每个模型的 Vite 前端，截登录页和后台功能页。

const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { preferredPortBase } = require('./lib/concurrency');

const HERE = __dirname;
const REPO_ROOT = path.resolve(HERE, '..', '..', '..');

function parseArgs(argv) {
  const out = { id: null, only: null, basePort: null };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--only') out.only = argv[++i];
    else if (a === '--base-port') out.basePort = parseInt(argv[++i], 10);
    else out.id = a;
  }
  if (!out.id) {
    console.error('usage: screenshot_admin_runtime.js <TASK_ID> [--only COL] [--base-port 5373]');
    process.exit(2);
  }
  return out;
}

function sanitize(s) {
  return s.replace(/[\\/:*?"<>|]+/g, '_').replace(/\s+/g, '_');
}

function stripAnsi(s) {
  return String(s || '').replace(/\x1b\[[0-9;]*m/g, '');
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

function findFrontendDir(taskDir, code) {
  const candidates = [
    path.join(taskDir, 'extracted', code, 'ohmytokencom', 'frontend'),
    path.join(taskDir, 'extracted', code, 'frontend'),
    path.join(taskDir, 'extracted', code),
  ];
  for (const p of candidates) {
    if (fs.existsSync(path.join(p, 'package.json'))) return p;
  }
  return null;
}

function hasVite(frontendDir) {
  const vitePkg = path.join(frontendDir, 'node_modules', 'vite', 'package.json');
  const viteCmd = path.join(frontendDir, 'node_modules', '.bin', process.platform === 'win32' ? 'vite.cmd' : 'vite');
  return fs.existsSync(vitePkg) && fs.existsSync(viteCmd);
}

function ensureDeps(frontendDir) {
  if (hasVite(frontendDir)) return;
  console.log(`     npm install in ${frontendDir}`);
  const r = spawnSync('npm install --no-audit --no-fund', {
    cwd: frontendDir,
    shell: true,
    stdio: 'pipe',
    encoding: 'utf8',
    env: { ...process.env, CI: 'true' },
    maxBuffer: 10 * 1024 * 1024,
  });
  if (r.status !== 0) {
    throw new Error(`npm install failed\n${stripAnsi((r.stdout || '') + '\n' + (r.stderr || '')).slice(-4000)}`);
  }
}

function waitForViteUrl(child, timeoutMs = 90000) {
  return new Promise((resolve, reject) => {
    let buf = '';
    let done = false;
    const finish = (fn, v) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      child.stdout.off('data', onData);
      child.stderr.off('data', onData);
      fn(v);
    };
    const onData = (chunk) => {
      buf += chunk.toString();
      const clean = stripAnsi(buf);
      const m = clean.match(/Local:\s*(https?:\/\/[^\s]+?\/)/);
      if (m) finish(resolve, m[1]);
    };
    const timer = setTimeout(() => {
      finish(reject, new Error(`vite did not print Local URL\n${stripAnsi(buf).slice(-3000)}`));
    }, timeoutMs);
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
    child.on('exit', (code) => {
      finish(reject, new Error(`vite exited with code ${code}\n${stripAnsi(buf).slice(-3000)}`));
    });
  });
}

async function renderTextPng(browser, outPath, title, lines) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const safe = (s) => String(s || '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  await page.setContent(`<!doctype html><meta charset="utf-8"><style>
    body{margin:0;background:#111827;color:#d1d5db;font:16px/1.55 "Cascadia Mono","Microsoft YaHei UI","Microsoft YaHei","Segoe UI Symbol",Consolas,monospace}
    pre{white-space:pre-wrap;padding:28px 32px;margin:0}
  </style><pre>${safe(lines)}</pre>`);
  await page.screenshot({ path: outPath, fullPage: true });
  await page.close();
}

async function startDev(frontendDir, port) {
  ensureDeps(frontendDir);
  const viteBin = path.join(frontendDir, 'node_modules', '.bin', process.platform === 'win32' ? 'vite.cmd' : 'vite');
  const cmd = `"${viteBin}" --host 127.0.0.1 --port ${port} --strictPort`;
  console.log(`     starting ${cmd}`);
  const child = spawn(cmd, { cwd: frontendDir, shell: true, windowsHide: true });
  child.on('error', e => console.error(`     spawn error: ${e.message}`));
  const url = await waitForViteUrl(child).catch(e => {
    killTree(child.pid);
    throw e;
  });
  return { child, url: url.replace(/\/$/, '') };
}

async function cleanViteOverlay(page) {
  await page.evaluate(() => {
    document.querySelectorAll('vite-error-overlay').forEach(el => el.remove());
  }).catch(() => {});
}

async function screenshotModel(browser, taskDir, label, info, outDir, port) {
  const code = info.code;
  const tag = sanitize(label);
  const frontendDir = findFrontendDir(taskDir, code);
  const p1 = path.join(outDir, `${tag}_01_admin_login.png`);
  const p2 = path.join(outDir, `${tag}_02_admin_plan.png`);
  const p3Name = fs.existsSync(path.join(frontendDir || '', 'src', 'views', 'admin', 'SseOnlineManage.vue'))
    ? '03_sse_online'
    : '03_admin_news';
  const p3 = path.join(outDir, `${tag}_${p3Name}.png`);
  if (!frontendDir) {
    await renderTextPng(browser, p1, `${label} 缺少前端项目`, `未找到 ${code} 的 package.json`);
    return;
  }

  let dev;
  try {
    dev = await startDev(frontendDir, port);
  } catch (e) {
    await renderTextPng(browser, p1, `${label} 前端启动失败`, e.message);
    return;
  }

  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const consoleLines = [];
  page.on('console', msg => {
    if (['error', 'warning'].includes(msg.type())) consoleLines.push(`[${msg.type()}] ${msg.text()}`);
  });
  page.on('pageerror', err => consoleLines.push(`[pageerror] ${err.message}`));

  try {
    console.log(`     vite up at ${dev.url}`);
    await page.goto(`${dev.url}/admin/login`, { waitUntil: 'networkidle', timeout: 90000 }).catch(async () => {
      await page.waitForLoadState('load', { timeout: 30000 }).catch(() => {});
    });
    await page.waitForTimeout(2000);
    await cleanViteOverlay(page);
    await page.screenshot({ path: p1, fullPage: true });
    console.log(`     ${path.basename(p1)}`);

    await page.evaluate(() => {
      localStorage.setItem('admin-token', 'qc-dummy-token');
      localStorage.setItem('admin-user-info', JSON.stringify({
        id: 1,
        username: 'admin',
        nickname: '质检管理员',
        status: 1
      }));
    });
    await page.goto(`${dev.url}/admin/plan`, { waitUntil: 'load', timeout: 90000 });
    await page.waitForTimeout(4500);
    await cleanViteOverlay(page);
    await page.screenshot({ path: p2, fullPage: true });
    console.log(`     ${path.basename(p2)}`);

    const route = p3Name === '03_sse_online' ? '/admin/sse-online' : '/admin/news';
    await page.goto(`${dev.url}${route}`, { waitUntil: 'load', timeout: 90000 });
    await page.waitForTimeout(4500);
    await cleanViteOverlay(page);
    await page.screenshot({ path: p3, fullPage: true });
    console.log(`     ${path.basename(p3)}`);

    if (consoleLines.length) {
      const logPath = path.join(taskDir, 'logs', `${code}_frontend_console.log`);
      fs.mkdirSync(path.dirname(logPath), { recursive: true });
      fs.writeFileSync(logPath, consoleLines.join('\n'), 'utf8');
    }
  } catch (e) {
    const errPath = path.join(outDir, `${tag}_02_runtime_error.png`);
    await renderTextPng(browser, errPath, `${label} 运行截图失败`, `${e.message}\n\n${consoleLines.slice(-40).join('\n')}`);
    console.error(`   [err] ${label}: ${e.message}`);
  } finally {
    await ctx.close();
    killTree(dev.child.pid);
    await new Promise(r => setTimeout(r, 700));
  }
}

async function main() {
  const args = parseArgs(process.argv);
  const taskDir = path.join(REPO_ROOT, 'tasks', args.id);
  const map = JSON.parse(fs.readFileSync(path.join(taskDir, 'model_map.json'), 'utf8'));
  const outDir = path.join(REPO_ROOT, 'delivery', args.id, 'screenshots');
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  let port = args.basePort ?? preferredPortBase(args.id, 'screenshot-admin-runtime', 8);
  for (const [label, info] of Object.entries(map.models)) {
    if (args.only && args.only !== label && args.only !== info.code) continue;
    console.log(`==> ${label} (${info.code})`);
    await screenshotModel(browser, taskDir, label, info, outDir, port);
    port += 1;
  }
  await browser.close();
}

main().catch(e => {
  console.error(e);
  process.exit(1);
});
