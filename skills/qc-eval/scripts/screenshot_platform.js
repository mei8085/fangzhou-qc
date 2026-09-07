#!/usr/bin/env node
// NSQV41 - per-model screenshot: run vite dev per model, capture login page.
// Purpose-built for network-automation-platform full-stack apps.

const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { preferredPortBase } = require('./lib/concurrency');

const HERE = __dirname;
const SKILL_DIR = path.resolve(HERE, '..');
const REPO_ROOT = path.resolve(SKILL_DIR, '..', '..');

const TASK_ID = process.argv[2];
if (!TASK_ID) { console.error('usage: screenshot_platform.js <TASK_ID>'); process.exit(2); }

const mapPath = path.join(REPO_ROOT, 'tasks', TASK_ID, 'model_map.json');
const map = JSON.parse(fs.readFileSync(mapPath, 'utf-8'));
const outDir = path.join(REPO_ROOT, 'delivery', TASK_ID, 'screenshots');
fs.mkdirSync(outDir, { recursive: true });

function sanitize(s) { return s.replace(/[^A-Za-z0-9._-]+/g, '_'); }
function stripAnsi(s) { return s.replace(/\x1b\[[0-9;]*m/g, ''); }

async function waitForViteUrl(child, timeoutMs = 90000) {
  return new Promise((resolve, reject) => {
    let buf = '';
    const timer = setTimeout(() => reject(new Error('vite start timeout')), timeoutMs);
    const onData = (chunk) => {
      buf += chunk.toString();
      const m = stripAnsi(buf).match(/Local:\s*(https?:\/\/[^\s]+?\/)/);
      if (m) { clearTimeout(timer); resolve(m[1]); }
    };
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
  });
}

function killTree(pid) {
  if (process.platform === 'win32') {
    try { spawnSync('taskkill', ['/PID', String(pid), '/F', '/T'], { stdio: 'ignore' }); } catch {}
  } else {
    try { process.kill(-pid, 'SIGTERM'); } catch {}
  }
}

async function shot(col, code, entry, port) {
  const tag = sanitize(col);
  const entryDir = path.join(REPO_ROOT, 'tasks', TASK_ID, 'extracted', code, entry, 'frontend');
  console.log(`\n=== ${col} (${code}) @ port ${port} ===`);
  console.log(`  entryDir=${entryDir}`);

  const binDir = path.join(entryDir, 'node_modules', '.bin');
  const hasBin = fs.existsSync(binDir);
  if (!hasBin) {
    console.log('  npm install ...');
    const inst = spawnSync('npm', ['install', '--prefer-offline', '--no-audit', '--no-fund'], {
      cwd: entryDir, stdio: 'inherit', shell: true, timeout: 600000,
    });
    if (inst.status !== 0) { console.error('  npm install failed'); return; }
  }

  const child = spawn('npm', ['run', 'dev', '--', '--port', String(port), '--strictPort'], {
    cwd: entryDir, shell: true, detached: process.platform !== 'win32',
  });

  let url;
  try {
    url = await waitForViteUrl(child);
    console.log(`  vite up: ${url}`);
  } catch (e) {
    console.error(`  ${col} vite failed: ${e.message}`);
    killTree(child.pid); return;
  }

  await new Promise((r) => setTimeout(r, 2500));

  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const page = await context.newPage();
    try {
      await page.goto(url, { waitUntil: 'networkidle', timeout: 20000 });
    } catch (e) {
      console.error(`  goto failed: ${e.message}`);
      try { await page.goto(url, { waitUntil: 'load', timeout: 15000 }); } catch {}
    }
    await new Promise((r) => setTimeout(r, 1500));
    const initialPng = path.join(outDir, `${tag}_01_login.png`);
    await page.screenshot({ path: initialPng, fullPage: true });
    console.log(`  ${path.basename(initialPng)}`);

    // Try clicking around to reach dashboard - just capture a second view showing more UI
    try {
      // try opening about / or hovering menus / just wait for any auto-load
      await page.waitForTimeout(1500);
      const secondPng = path.join(outDir, `${tag}_02_ui.png`);
      await page.screenshot({ path: secondPng, fullPage: true });
      console.log(`  ${path.basename(secondPng)}`);
    } catch (e) {
      console.error(`  second shot: ${e.message}`);
    }
  } finally {
    await browser.close();
    killTree(child.pid);
    await new Promise((r) => setTimeout(r, 1200));
  }
}

(async () => {
  let port = preferredPortBase(TASK_ID, 'screenshot-platform', 8);
  for (const [col, info] of Object.entries(map.models)) {
    await shot(col, info.code, info.entry, port);
    port += 1;
  }
})();
