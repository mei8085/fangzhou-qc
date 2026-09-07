#!/usr/bin/env node
// Dashboard / 后台管理系统 截图脚本：
//   01_initial    — 进入 /dashboard 等数据加载完
//   02_week       — 点 本周 按钮切换时间范围
//   03_table      — 滚到最下 看订单表 + 分页
//
// 假定项目用 vue-pure-admin 模板：默认有 SSO query string 一键登录的能力
// （/#/permission/page/index?username=sso&roles=admin&accessToken=...）。
// 登录后再 push 到 /dashboard。
//
// 用法：node screenshot_dashboard.js <TASK_ID> [--only COL] [--base-port 5173]

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
    console.error('usage: screenshot_dashboard.js <TASK_ID> [--only COL] [--base-port 5173] [--keep-existing]');
    process.exit(2);
  }
  return out;
}

function sanitize(s) { return s.replace(/[^A-Za-z0-9._-]+/g, '_'); }
function stripAnsi(s) { return s.replace(/\x1b\[[0-9;]*m/g, ''); }

async function waitForViteUrl(child, timeoutMs = 90000) {
  return new Promise((resolve, reject) => {
    let buf = '';
    const onData = (chunk) => {
      buf += chunk.toString();
      const clean = stripAnsi(buf);
      const m = clean.match(/Local:\s*(https?:\/\/[^\s]+?\/)/);
      if (m) {
        const url = m[1];
        child.stdout.off('data', onData);
        child.stderr.off('data', onErr);
        resolve(url);
      }
    };
    const onErr = (chunk) => { buf += chunk.toString(); };
    child.stdout.on('data', onData);
    child.stderr.on('data', onErr);
    const t = setTimeout(() => {
      child.stdout.off('data', onData);
      child.stderr.off('data', onErr);
      reject(new Error(`vite did not print Local: URL within ${timeoutMs}ms. last:\n${buf.slice(-1000)}`));
    }, timeoutMs);
    child.on('exit', code => {
      clearTimeout(t);
      reject(new Error(`vite exited with code ${code}. last:\n${buf.slice(-800)}`));
    });
  });
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

function ensureViteBin(entryDir) {
  // pure-admin 项目用 pnpm 装包；解压时 symlink 全部丢了，vite 找不到兄弟包。
  // 用 pnpm install 恢复 node_modules 结构。
  const viteEntry = path.join(entryDir, 'node_modules', 'vite', 'package.json');
  if (fs.existsSync(viteEntry)) return;
  console.log(`     [bin] pnpm install in ${entryDir}`);
  const r = spawnSync('pnpm install --prefer-offline --reporter=append-only --config.confirmModulesPurge=false', {
    cwd: entryDir, shell: true, stdio: 'inherit', env: { ...process.env, CI: 'true' },
  });
  if (r.status !== 0) throw new Error(`pnpm install failed in ${entryDir}`);
}

async function startDev(entryDir, port) {
  ensureViteBin(entryDir);
  // 不能走 pnpm run dev — pnpm 11 启动前会做 deps-status check 失败。
  // 直接调 node_modules/.bin 里的 vite shim，等同于 package.json 里 dev 的实际命令。
  const viteBin = process.platform === 'win32'
    ? path.join(entryDir, 'node_modules', '.bin', 'vite.CMD')
    : path.join(entryDir, 'node_modules', '.bin', 'vite');
  const cmd = `"${viteBin}" --port ${port} --strictPort`;
  console.log(`     starting "${cmd}" in ${entryDir}`);
  const child = spawn(cmd, { cwd: entryDir, shell: true, windowsHide: true });
  child.on('error', e => console.error('     spawn error:', e.message));
  const url = await waitForViteUrl(child).catch(e => { killTree(child.pid); throw e; });
  return { child, url };
}

async function screenshotModel(browser, label, code, entryDir, outDir, port, keep) {
  const tag = sanitize(label);
  const p1 = path.join(outDir, `${tag}_01_initial.png`);
  const p2 = path.join(outDir, `${tag}_02_week.png`);
  const p3 = path.join(outDir, `${tag}_03_table.png`);
  if (keep && fs.existsSync(p1) && fs.existsSync(p2) && fs.existsSync(p3)) {
    console.log(`   [skip] ${label}: all 3 PNGs exist`);
    return;
  }

  let dev;
  try {
    dev = await startDev(entryDir, port);
  } catch (e) {
    console.error(`   [err] ${label}: dev — ${e.message}`);
    return;
  }
  const url = dev.url.replace(/\/$/, '');
  console.log(`     vite up at ${url}`);

  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  });
  const page = await ctx.newPage();
  const errs = [];
  page.on('pageerror', e => { errs.push(e.message); console.log(`     [pageerror] ${e.message.slice(0, 800)}`); });
  page.on('console', m => {
    if (m.type() === 'error' || m.type() === 'warning') {
      const t = m.text();
      console.log(`     [${m.type()}] ${t.slice(0, 600)}`);
    }
  });
  page.on('response', resp => {
    if (resp.status() >= 400) console.log(`     [http ${resp.status()}] ${resp.url().slice(0, 200)}`);
  });

  // 移除 vite 的报错 overlay（pure-admin 模板某些 scss 在首次编译时会过一会才稳定，
  // 早期的 css 错误覆盖层只是噪音，不代表 dashboard 本身有问题）。
  async function dismissOverlay() {
    await page.evaluate(() => {
      const ov = document.querySelector('vite-error-overlay');
      if (ov && ov.shadowRoot) {
        const close = ov.shadowRoot.querySelector('.close');
        if (close) close.click();
      }
      if (ov) ov.remove();
    }).catch(() => {});
  }

  try {
    // SSO 自动登录：vue-pure-admin sso.ts 接受 username/roles/accessToken 三个参数
    // 注意：pure-admin 的 SSO 写完 token 后会 window.location.replace 跳到目标，
    // 这里直接走带 SSO 参数的 dashboard 路径，让登录完成后落到 dashboard。
    const ssoUrl = `${url}/#/dashboard/index?username=sso&roles=admin&accessToken=eyJhbGciOiJIUzUxMiJ9.admin`;
    await page.goto(ssoUrl, { waitUntil: 'load', timeout: 90000 });
    await page.waitForTimeout(8000);
    // 确认登录后会重定向，再 push 一次 dashboard 路径以便保险
    await page.goto(`${url}/#/dashboard/index`, { waitUntil: 'load', timeout: 90000 });
    // 等到 stat card 或 chart 出现
    await page.waitForFunction(() => {
      const t = document.body && document.body.innerText || '';
      return /总用户数|今日订单|访问趋势|访问量|销售额|数据统计|订单号/.test(t);
    }, null, { timeout: 90000 }).catch(() => {});
    await page.waitForTimeout(4500);
    await dismissOverlay();
    const bodyTextLen = await page.evaluate(() => (document.body && document.body.innerText || '').length).catch(() => 0);
    console.log(`     bodyText len = ${bodyTextLen}`);
    await page.screenshot({ path: p1, fullPage: true });
    console.log(`     ${path.basename(p1)}`);

    // 02 — 点 本周
    const weekClicked = await page.evaluate(() => {
      const all = Array.from(document.querySelectorAll('button, .el-radio-button__inner, label, span'));
      const t = all.find(b => (b.textContent || '').trim() === '本周');
      if (t) { (t.closest('label') || t).click(); return true; }
      return false;
    }).catch(() => false);
    await page.waitForTimeout(2000);
    await dismissOverlay();
    await page.screenshot({ path: p2, fullPage: true });
    console.log(`     ${path.basename(p2)} (clicked week=${weekClicked})`);

    // 03 — 滚到底，截订单表 + 分页
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(1500);
    await dismissOverlay();
    await page.screenshot({ path: p3, fullPage: true });
    console.log(`     ${path.basename(p3)}`);

    if (errs.length) console.log(`     pageerrors: ${errs.length} (first: ${errs[0].slice(0, 200)})`);
  } catch (e) {
    console.error(`   [err] ${label}: ${e.message}`);
  } finally {
    await ctx.close();
    killTree(dev.child.pid);
    await new Promise(r => setTimeout(r, 1000));
  }
}

async function main() {
  const args = parseArgs(process.argv);
  const taskDir = path.join(REPO_ROOT, 'tasks', args.id);
  const mapPath = path.join(taskDir, 'model_map.json');
  if (!fs.existsSync(mapPath)) { console.error(`no ${mapPath}`); process.exit(2); }
  const map = JSON.parse(fs.readFileSync(mapPath, 'utf8'));
  const outDir = path.join(REPO_ROOT, 'delivery', args.id, 'screenshots');
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  let port = args.basePort ?? preferredPortBase(args.id, 'screenshot-dashboard', 8);
  for (const [col, info] of Object.entries(map.models)) {
    if (args.only && col !== args.only) continue;
    const entry = info.entry || '.';
    const entryDir = path.join(taskDir, 'extracted', info.code, entry);
    console.log(`==> ${col} (${info.code})  entry=${entry}`);
    if (!fs.existsSync(path.join(entryDir, 'package.json'))) {
      console.error(`   [skip] no package.json at ${entryDir}`);
      continue;
    }
    await screenshotModel(browser, col, info.code, entryDir, outDir, port, args.keep);
    port += 1;
  }
  await browser.close();
}
main().catch(e => { console.error(e); process.exit(1); });
