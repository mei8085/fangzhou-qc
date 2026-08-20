#!/usr/bin/env node
// NSQV41 - start each model's backend + frontend, login, capture dashboard.

const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const HERE = __dirname;
const SKILL_DIR = path.resolve(HERE, '..');
const REPO_ROOT = path.resolve(SKILL_DIR, '..', '..');

const TASK_ID = process.argv[2];
if (!TASK_ID) { console.error('usage: screenshot_fullstack.js <TASK_ID>'); process.exit(2); }

const mapPath = path.join(REPO_ROOT, 'tasks', TASK_ID, 'model_map.json');
const map = JSON.parse(fs.readFileSync(mapPath, 'utf-8'));
const outDir = path.join(REPO_ROOT, 'delivery', TASK_ID, 'screenshots');
fs.mkdirSync(outDir, { recursive: true });

const CREDS = {
  '30B-0616E-OPD': { user: 'admin', pass: 'admin123' },
  '30B-Release-Merge-0616E-29': { user: 'admin', pass: 'admin123' },
  '30B-Merge-0618B-AA': { user: 'admin', pass: 'admin123' },
  'Opus 4.7': { user: 'admin', pass: 'admin@123' },
};

const BACKENDS = {
  '30B-0616E-OPD': { cwd: 'delivery_tools/backend', mod: 'app.main:app' },
  '30B-Release-Merge-0616E-29': { cwd: 'network-automation-platform/backend', mod: 'app.main:app' },
  '30B-Merge-0618B-AA': { cwd: 'netauto-platform/backend', mod: 'app.main:app' },
  'Opus 4.7': { cwd: 'delivery_tools/webapp/backend', mod: 'app.main:app' },
};

function sanitize(s) { return s.replace(/[^A-Za-z0-9._-]+/g, '_'); }
function stripAnsi(s) { return s.replace(/\x1b\[[0-9;]*m/g, ''); }

async function waitForViteUrl(child, timeoutMs = 90000) {
  return new Promise((resolve, reject) => {
    let buf = '';
    const t = setTimeout(() => reject(new Error('vite timeout: ' + buf.slice(-500))), timeoutMs);
    const on = (chunk) => {
      buf += chunk.toString();
      const m = stripAnsi(buf).match(/Local:\s*(https?:\/\/[^\s]+?\/)/);
      if (m) { clearTimeout(t); resolve(m[1]); }
    };
    child.stdout.on('data', on); child.stderr.on('data', on);
  });
}

async function waitForHttp(url, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await new Promise((resolve, reject) => {
        const req = http.get(url, (res) => { res.resume(); res.on('end', resolve); });
        req.on('error', reject);
        req.setTimeout(2000, () => req.destroy(new Error('t')));
      });
      return true;
    } catch { await new Promise((r) => setTimeout(r, 1500)); }
  }
  return false;
}

function killTree(pid) {
  if (!pid) return;
  if (process.platform === 'win32') {
    try { spawnSync('taskkill', ['/PID', String(pid), '/F', '/T'], { stdio: 'ignore' }); } catch {}
  } else {
    try { process.kill(-pid, 'SIGTERM'); } catch {}
  }
}

async function processOne(col, code, entry, viteport, backendPort) {
  const tag = sanitize(col);
  const feDir = path.join(REPO_ROOT, 'tasks', TASK_ID, 'extracted', code, entry, 'frontend');
  const be = BACKENDS[col];
  const beDir = path.join(REPO_ROOT, 'tasks', TASK_ID, 'extracted', code, be.cwd);
  console.log(`\n=== ${col} (${code}) fe:${viteport} be:${backendPort} ===`);

  const beChild = spawn('python', ['-m', 'uvicorn', be.mod, '--host', '127.0.0.1', '--port', String(backendPort)], {
    cwd: beDir, shell: true, detached: process.platform !== 'win32',
  });
  let beBuf = '';
  beChild.stdout.on('data', d => beBuf += d.toString());
  beChild.stderr.on('data', d => beBuf += d.toString());

  const beOk = await waitForHttp(`http://127.0.0.1:${backendPort}/docs`, 25000);
  if (!beOk) {
    console.error(`  backend failed; tail:\n${beBuf.slice(-800)}`);
    killTree(beChild.pid);
    await new Promise(r => setTimeout(r, 1000));
    return { beOk: false };
  }
  console.log('  backend up');

  const viteCfg = path.join(feDir, 'vite.config.js');
  const viteCfgTs = path.join(feDir, 'vite.config.ts');
  const cfgFile = fs.existsSync(viteCfg) ? viteCfg : (fs.existsSync(viteCfgTs) ? viteCfgTs : null);
  let origCfg = null;
  if (cfgFile) {
    origCfg = fs.readFileSync(cfgFile, 'utf-8');
    const patched = origCfg
      .replace(/localhost:8000/g, `127.0.0.1:${backendPort}`)
      .replace(/127\.0\.0\.1:8000/g, `127.0.0.1:${backendPort}`);
    fs.writeFileSync(cfgFile, patched);
  }

  const feChild = spawn('npm', ['run', 'dev', '--', '--port', String(viteport), '--strictPort'], {
    cwd: feDir, shell: true, detached: process.platform !== 'win32',
  });
  let url;
  try { url = await waitForViteUrl(feChild); }
  catch (e) {
    console.error(`  vite: ${e.message}`);
    killTree(beChild.pid); killTree(feChild.pid);
    if (cfgFile && origCfg !== null) fs.writeFileSync(cfgFile, origCfg);
    await new Promise(r => setTimeout(r, 1200));
    return { beOk: true, feOk: false };
  }
  console.log(`  vite up: ${url}`);
  await new Promise(r => setTimeout(r, 2500));

  const browser = await chromium.launch();
  try {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const page = await ctx.newPage();
    try { await page.goto(url, { waitUntil: 'load', timeout: 20000 }); } catch (e) { console.error('  goto: ', e.message); }
    await page.waitForTimeout(1500);
    const creds = CREDS[col];
    try {
      await page.locator('input').first().fill(creds.user);
      await page.locator('input[type="password"]').first().fill(creds.pass);
      const btns = ['button:has-text("登录")', 'button:has-text("Login")', 'button[type="submit"]'];
      for (const s of btns) {
        try { await page.locator(s).first().click({ timeout: 2500 }); break; } catch {}
      }
      await page.waitForTimeout(4500);
      const dashPng = path.join(outDir, `${tag}_02_dashboard.png`);
      await page.screenshot({ path: dashPng, fullPage: true });
      console.log(`  ${path.basename(dashPng)}`);
    } catch (e) {
      console.error(`  login flow: ${e.message}`);
    }
  } finally {
    await browser.close();
    killTree(beChild.pid);
    killTree(feChild.pid);
    if (cfgFile && origCfg !== null) fs.writeFileSync(cfgFile, origCfg);
    await new Promise(r => setTimeout(r, 1500));
  }
  return { beOk: true, feOk: true };
}

(async () => {
  let viteport = 5200, bport = 8200;
  for (const [col, info] of Object.entries(map.models)) {
    try { await processOne(col, info.code, info.entry, viteport, bport); }
    catch (e) { console.error(`  fatal: ${e.message}`); }
    viteport += 1; bport += 1;
  }
})();
