#!/usr/bin/env node
// FM95FU 课程报名系统前端 — 每个模型截 3 张：login / admin dashboard / course list
// 用法：node _shot_fm95fu.cjs <COL_LABEL> <ENTRY_DIR> <OUT_DIR> <PORT>
const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');

function stripAnsi(s) { return s.replace(/\x1b\[[0-9;]*m/g, ''); }
function sanitize(s) { return s.replace(/[^A-Za-z0-9._-]+/g, '_'); }

function killTree(pid) {
  if (!pid) return;
  if (process.platform === 'win32') spawnSync('taskkill', ['/F', '/T', '/PID', String(pid)], { stdio: 'ignore' });
  else { try { process.kill(-pid); } catch {} try { process.kill(pid); } catch {} }
}

async function waitForViteUrl(child, timeoutMs = 120000) {
  return new Promise((resolve, reject) => {
    let buf = '';
    const onData = (chunk) => {
      buf += chunk.toString();
      const m = stripAnsi(buf).match(/Local:\s*(https?:\/\/[^\s]+?\/)/);
      if (m) { child.stdout.off('data', onData); child.stderr.off('data', onErr); resolve(m[1]); }
    };
    const onErr = (chunk) => { buf += chunk.toString(); };
    child.stdout.on('data', onData);
    child.stderr.on('data', onErr);
    const t = setTimeout(() => { reject(new Error(`no Local URL. tail:\n${buf.slice(-1000)}`)); }, timeoutMs);
    child.on('exit', code => { clearTimeout(t); reject(new Error(`vite exited ${code}. tail:\n${buf.slice(-800)}`)); });
  });
}

async function startDev(entry, port) {
  const viteBin = process.platform === 'win32'
    ? path.join(entry, 'node_modules', '.bin', 'vite.CMD')
    : path.join(entry, 'node_modules', '.bin', 'vite');
  const child = spawn(`"${viteBin}" --port ${port} --strictPort`, { cwd: entry, shell: true, windowsHide: true });
  const url = await waitForViteUrl(child).catch(e => { killTree(child.pid); throw e; });
  return { child, url };
}

async function main() {
  const [ , , label, entry, outDir, portStr ] = process.argv;
  if (!label || !entry || !outDir || !portStr) { console.error('usage: shot <label> <entry> <outDir> <port>'); process.exit(2); }
  const port = parseInt(portStr, 10);
  fs.mkdirSync(outDir, { recursive: true });
  const tag = sanitize(label);
  const p1 = path.join(outDir, `${tag}_01_login.png`);
  const p2 = path.join(outDir, `${tag}_02_dashboard.png`);
  const p3 = path.join(outDir, `${tag}_03_courses.png`);

  let dev;
  try {
    dev = await startDev(entry, port);
  } catch (e) {
    console.error(`[dev fail] ${label}: ${e.message}`);
    // render blocker page
    const browser = await chromium.launch();
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    await page.setContent(`<html><body style="background:#111;color:#f88;font:16px monospace;padding:24px;white-space:pre-wrap">DEV SERVER FAILED — ${label}\n\n${e.message.slice(-3000)}</body></html>`);
    await page.screenshot({ path: p1, fullPage: true });
    await browser.close();
    process.exit(0);
  }
  const url = dev.url.replace(/\/$/, '');
  console.log(`[dev up] ${label} @ ${url}`);

  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errs = [];
  page.on('pageerror', e => { errs.push(e.message); console.log(`[pageerror] ${e.message.slice(0, 400)}`); });
  page.on('console', m => { if (m.type() === 'error') console.log(`[console.error] ${m.text().slice(0, 400)}`); });

  try {
    // detect history mode
    await page.goto(`${url}/`, { waitUntil: 'load', timeout: 60000 });
    await page.waitForTimeout(2000);
    const useHash = await page.evaluate(() => location.hash.includes('/') || location.pathname === '/');
    // fetch login route: try hash first, fallback to path
    const loginUrl1 = `${url}/#/login`;
    const loginUrl2 = `${url}/login`;
    await page.goto(loginUrl1, { waitUntil: 'load', timeout: 60000 }).catch(()=>{});
    await page.waitForTimeout(1500);
    if (!(await page.locator('input[type=password]').count())) {
      await page.goto(loginUrl2, { waitUntil: 'load', timeout: 60000 }).catch(()=>{});
      await page.waitForTimeout(1500);
    }
    await page.waitForTimeout(3500);
    // dismiss vite overlay if any
    await page.evaluate(() => { const ov = document.querySelector('vite-error-overlay'); if (ov) ov.remove(); }).catch(()=>{});
    await page.screenshot({ path: p1, fullPage: true });
    console.log(`[shot] ${path.basename(p1)}`);

    // 02 login as admin -> dashboard: use Playwright fill for proper Vue reactivity
    const inputCount = await page.locator('input').count();
    console.log(`[login] input count=${inputCount}`);
    try {
      const userInput = page.locator('input:not([type=password])').first();
      const passInput = page.locator('input[type=password]').first();
      await userInput.click({ timeout: 5000 });
      await userInput.fill('wangfang');
      await passInput.click({ timeout: 5000 });
      await passInput.fill('123456');
      console.log(`[login] fill ok`);
    } catch (e) {
      console.log(`[login] fill err: ${e.message}`);
    }
    await page.waitForTimeout(500);
    // click login button
    const clicked = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button, .el-button'));
      const t = btns.find(b => /登录|登 录|Log ?in|Sign in/i.test(b.textContent || ''));
      if (t) { t.click(); return true; }
      if (btns.length) { btns[btns.length - 1].click(); return 'last'; }
      return false;
    });
    console.log(`[login] clicked=${clicked}`);
    await page.waitForTimeout(6000);
    await page.evaluate(() => { const ov = document.querySelector('vite-error-overlay'); if (ov) ov.remove(); }).catch(()=>{});
    // if still on login, force-inject fake session and retry (so dashboard skeleton is visible even with broken mock)
    if (page.url().includes('/login')) {
      console.log(`[login] failed, injecting fake session`);
      await page.evaluate(() => {
        const fakeUser = { id: 1, username: 'wangfang', realName: '王芳', name: '王芳', role: 'admin', firstLogin: false, status: 'active' };
        localStorage.setItem('token', 'mock-token-1-forced');
        localStorage.setItem('mock_token', 'mock-token-1-forced');
        localStorage.setItem('user', JSON.stringify(fakeUser));
        localStorage.setItem('mock_user', JSON.stringify(fakeUser));
        localStorage.setItem('userInfo', JSON.stringify(fakeUser));
      });
      await page.goto(`${url}/dashboard`, { waitUntil: 'load', timeout: 30000 }).catch(()=>{});
      await page.waitForTimeout(3000);
      if (page.url().includes('/login')) {
        await page.goto(`${url}/#/dashboard`, { waitUntil: 'load', timeout: 30000 }).catch(()=>{});
        await page.waitForTimeout(3000);
      }
    }
    await page.screenshot({ path: p2, fullPage: true });
    console.log(`[shot] ${path.basename(p2)} url=${page.url()}`);

    // 03 courses - click sidebar 课程管理 rather than URL nav (works for both hash and history mode)
    const clickedCourses = await page.evaluate(() => {
      const links = Array.from(document.querySelectorAll('a, .el-menu-item, li, span, div'));
      const t = links.find(el => /课程管理|课程列表/.test((el.textContent || '').trim().slice(0, 10)));
      if (t) { t.click(); return t.textContent.trim().slice(0, 20); }
      return false;
    });
    console.log(`[nav courses] clicked=${clickedCourses}`);
    await page.waitForTimeout(3500);
    // if still on dashboard, try direct URL
    if (!/courses/.test(page.url())) {
      await page.goto(`${url}/courses`, { waitUntil: 'load', timeout: 30000 }).catch(()=>{});
      await page.waitForTimeout(2000);
      if (!/courses/.test(page.url())) {
        await page.goto(`${url}/#/courses`, { waitUntil: 'load', timeout: 30000 }).catch(()=>{});
        await page.waitForTimeout(2000);
      }
    }
    await page.evaluate(() => { const ov = document.querySelector('vite-error-overlay'); if (ov) ov.remove(); }).catch(()=>{});
    await page.screenshot({ path: p3, fullPage: true });
    console.log(`[shot] ${path.basename(p3)} url=${page.url()}`);

    if (errs.length) console.log(`[errs] ${errs.length}: ${errs[0].slice(0, 200)}`);
  } catch (e) {
    console.error(`[shot err] ${label}: ${e.message}`);
  } finally {
    await browser.close();
    killTree(dev.child.pid);
  }
}

main().catch(e => { console.error(e); process.exit(1); });
