#!/usr/bin/env node
// AEA9V1 迷你仓 H5 复测截图：每个模型起 next dev，截首页 / 订仓（仓库列表）/ 仓库详情 / 我的（用户详情）4 张图。
// 用法：node _shot_aea9v1.js [--base-port 5290]

const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const HERE = __dirname;
const REPO_ROOT = path.resolve(HERE, '..', '..', '..');
const TASK_ID = 'AEA9V1';

const MODELS = [
  { col: '30B-0616E-OPD',              code: '5SIDV', proj: 'mini-storage-h5' },
  { col: '30B-Release-Merge-0616E-29', code: '6U7Q4', proj: 'mini-storage-h5' },
  { col: '30B-Merge-0618B-AA',         code: '9G5OO', proj: 'mini-storage-h5' },
  { col: 'Opus 4.7',                   code: 'PDCOF', proj: 'mini-cang' },
];

const OUT = path.join(REPO_ROOT, 'delivery', TASK_ID, 'screenshots');
fs.mkdirSync(OUT, { recursive: true });

function stripAnsi(s) { return s.replace(/\x1b\[[0-9;]*m/g, ''); }
function sanitize(s) { return s.replace(/[^A-Za-z0-9._-]+/g, '_'); }
function killTree(pid) {
  if (!pid) return;
  if (process.platform === 'win32') spawnSync('taskkill', ['/F', '/T', '/PID', String(pid)], { stdio: 'ignore' });
  else { try { process.kill(-pid); } catch {} try { process.kill(pid); } catch {} }
}

async function waitForReady(child, port, timeoutMs = 120000) {
  return new Promise((resolve, reject) => {
    let buf = '';
    const t = setTimeout(() => reject(new Error(`next dev timeout on :${port}\n${buf.slice(-1000)}`)), timeoutMs);
    const on = (chunk) => {
      buf += chunk.toString();
      const clean = stripAnsi(buf);
      if (/Ready in|compiled|started server on/i.test(clean) && /localhost/.test(clean)) {
        setTimeout(() => resolve(`http://localhost:${port}`), 800);
      }
    };
    child.stdout.on('data', on); child.stderr.on('data', on);
    child.on('exit', code => { clearTimeout(t); reject(new Error(`next dev exited ${code}\n${buf.slice(-1000)}`)); });
  });
}

async function waitForHttp(url, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await new Promise((resolve, reject) => {
        const req = http.get(url, res => { res.resume(); res.on('end', resolve); });
        req.on('error', reject); req.setTimeout(2000, () => req.destroy(new Error('t')));
      });
      return;
    } catch { await new Promise(r => setTimeout(r, 500)); }
  }
  throw new Error('http wait timeout ' + url);
}

async function clickByText(page, texts) {
  for (const t of texts) {
    for (const sel of [`button:has-text("${t}")`, `[role="button"]:has-text("${t}")`, `text=${t}`]) {
      const el = page.locator(sel).first();
      try {
        if (await el.count() > 0 && await el.isVisible({ timeout: 500 })) {
          await el.click({ timeout: 3000 });
          return `${t}(${sel})`;
        }
      } catch {}
    }
  }
  return null;
}

async function clickTabByIndex(page, idx) {
  const w = 390, h = 844;
  const x = w * (idx + 0.5) / 4;
  const y = h - 30;
  await page.mouse.click(x, y);
}

async function shootOne(browser, m, port) {
  const projDir = path.join(REPO_ROOT, 'tasks', TASK_ID, 'extracted', m.code, m.proj);
  console.log(`\n[${m.col}] cwd=${projDir}  port=${port}`);
  const isWin = process.platform === 'win32';
  const env = { ...process.env, PORT: String(port), NODE_ENV: 'development' };
  const nextBin = path.join(projDir, 'node_modules', 'next', 'dist', 'bin', 'next');
  if (!fs.existsSync(nextBin)) {
    console.log(`  [${m.code}] next binary missing — running npm install ...`);
    const inst = spawnSync(isWin ? 'npm.cmd' : 'npm', ['install', '--no-audit', '--no-fund'], { cwd: projDir, stdio: 'inherit', shell: isWin });
    if (inst.status !== 0) throw new Error(`npm install failed`);
  }
  const child = spawn(process.execPath, [nextBin, 'dev', '-p', String(port)], {
    cwd: projDir, env, shell: false, detached: !isWin,
  });
  child.stdout.on('data', d => process.stdout.write(`  [${m.code}] ${d}`));
  child.stderr.on('data', d => process.stderr.write(`  [${m.code}!] ${d}`));

  try {
    await waitForReady(child, port, 120000);
    const base = `http://localhost:${port}`;
    await waitForHttp(base + '/', 25000);

    const ctx = await browser.newContext({
      viewport: { width: 390, height: 844 }, deviceScaleFactor: 2,
      isMobile: true, hasTouch: true, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)',
    });
    const page = await ctx.newPage();
    page.on('pageerror', err => console.log(`  [${m.code}] pageerror: ${err.message}`));

    const safe = sanitize(m.col);

    // 1. 首页
    await page.goto(base + '/', { waitUntil: 'networkidle', timeout: 30000 }).catch(e => console.log('goto home:', e.message));
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(OUT, `${safe}_01_home.png`), fullPage: false });

    // 2. 订仓列表页 — PDCOF 走 URL, 其它点 tab（用坐标点 tab index=1）
    if (m.code === 'PDCOF') {
      await page.goto(base + '/booking', { waitUntil: 'networkidle', timeout: 20000 }).catch(() => {});
    } else {
      const clicked = await clickByText(page, ['订仓', '仓库', '预订', 'Booking']);
      if (!clicked) await clickTabByIndex(page, 1);
    }
    await page.waitForTimeout(2000);
    await page.screenshot({ path: path.join(OUT, `${safe}_02_booking_list.png`), fullPage: false });
    const btnCount = await page.locator('button').count();
    const bookBtnCount = await page.locator('button:has-text("立即订仓")').count();
    console.log(`  [${m.col}] after step2: buttons=${btnCount}, 立即订仓=${bookBtnCount}`);

    // 3. 订仓详情页 — 点最后一张卡片 / 立即订仓（第一张可能被 sticky header 遮挡）
    let clicked = null;
    const storeButtonTexts = ['立即订仓', '立即预订', '预订', '查看详情', '查看'];
    for (const t of storeButtonTexts) {
      const loc = page.locator(`button:has-text("${t}")`);
      const n = await loc.count().catch(() => 0);
      if (n === 0) continue;
      for (let idx = Math.min(n - 1, 1); idx < n; idx++) {
        try {
          const el = loc.nth(idx);
          await el.scrollIntoViewIfNeeded({ timeout: 2000 }).catch(() => {});
          await page.waitForTimeout(300);
          const box = await el.boundingBox();
          if (box) {
            await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
            clicked = `${t} idx=${idx} via mouse`;
            break;
          }
        } catch (e) { console.log(`  [${m.col}] ${t}[${idx}] err: ${e.message.split('\n')[0]}`); }
      }
      if (clicked) break;
    }
    console.log(`  [${m.col}] store click: ${clicked}`);
    if (!clicked && m.code === 'PDCOF') {
      await page.goto(base + '/store/s001', { waitUntil: 'networkidle', timeout: 15000 }).catch(() => {});
    }
    await page.waitForTimeout(2500);
    await page.screenshot({ path: path.join(OUT, `${safe}_03_store_detail.png`), fullPage: false });

    // 4. 我的（用户详情）
    if (m.code === 'PDCOF') {
      await page.goto(base + '/profile', { waitUntil: 'networkidle', timeout: 20000 }).catch(() => {});
    } else {
      // 直接坐标点 tab index=3
      await clickTabByIndex(page, 3);
    }
    await page.waitForTimeout(1200);
    await page.screenshot({ path: path.join(OUT, `${safe}_04_profile.png`), fullPage: false });

    await ctx.close();
    console.log(`  [${m.col}] ok`);
  } catch (err) {
    console.error(`  [${m.col}] FAIL: ${err.message}`);
    try {
      const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
      const page = await ctx.newPage();
      await page.goto(`http://localhost:${port}/`, { timeout: 8000 }).catch(() => {});
      await page.waitForTimeout(500);
      await page.screenshot({ path: path.join(OUT, `${sanitize(m.col)}_01_home.png`) });
      await ctx.close();
    } catch {}
  } finally {
    killTree(child.pid);
    await new Promise(r => setTimeout(r, 500));
  }
}

(async () => {
  const args = process.argv.slice(2);
  let basePort = 5290;
  let only = null;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--base-port') basePort = parseInt(args[++i], 10);
    else if (args[i] === '--only') only = args[++i];
  }

  const browser = await chromium.launch();
  try {
    let i = 0;
    for (const m of MODELS) {
      if (only && m.col !== only && m.code !== only) continue;
      await shootOne(browser, m, basePort + i);
      i++;
    }
  } finally {
    await browser.close();
  }
})();
