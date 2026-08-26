#!/usr/bin/env node
// Start each SPA MM030 FastAPI + Vite deliverable locally and capture QC evidence.

const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const http = require('http');
const path = require('path');

const HERE = __dirname;
const SKILL_DIR = path.resolve(HERE, '..');
const REPO_ROOT = path.resolve(SKILL_DIR, '..', '..');

function parseArgs(argv) {
  const out = { taskId: null, only: null };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--only') out.only = argv[++i];
    else out.taskId = a;
  }
  if (!out.taskId) {
    console.error('usage: screenshot_spa_mm030.js <TASK_ID> [--only <MODEL>]');
    process.exit(2);
  }
  return out;
}

function safeName(s) {
  return String(s).replace(/ /g, '_');
}

function killTree(pid) {
  if (!pid) return;
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/F', '/T', '/PID', String(pid)], { stdio: 'ignore' });
  } else {
    try { process.kill(-pid, 'SIGTERM'); } catch {}
  }
}

async function waitForHttp(url, timeoutMs = 45000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await new Promise((resolve, reject) => {
        const req = http.get(url, (res) => {
          res.resume();
          res.on('end', resolve);
        });
        req.on('error', reject);
        req.setTimeout(2000, () => req.destroy(new Error('timeout')));
      });
      return true;
    } catch {
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
  return false;
}

async function waitForVite(child, timeoutMs = 60000) {
  return new Promise((resolve, reject) => {
    let buf = '';
    const stripAnsi = (s) => s.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '');
    const timer = setTimeout(() => reject(new Error(`vite timeout: ${buf.slice(-800)}`)), timeoutMs);
    const onData = (chunk) => {
      buf += chunk.toString();
      const m = stripAnsi(buf).match(/Local:\s*(https?:\/\/\S+)/);
      if (m) {
        clearTimeout(timer);
        resolve(m[1].replace(/\/$/, ''));
      }
    };
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
    child.on('exit', (code) => {
      clearTimeout(timer);
      reject(new Error(`vite exited with ${code}: ${buf.slice(-800)}`));
    });
  });
}

async function screenshotVisible(page, outPath) {
  await page.waitForTimeout(1200);
  await page.screenshot({ path: outPath, fullPage: false });
}

async function clickView(page, viewId) {
  await page.evaluate((id) => {
    const btn = document.querySelector(`[data-view="${id}"]`);
    if (btn) {
      const group = btn.closest('.nav-group');
      if (group) {
        group.classList.add('expanded');
        group.classList.remove('collapsed');
      }
      btn.click();
    }
  }, viewId);
  await page.waitForTimeout(1800);
}

async function captureOne(taskId, modelName, info, index) {
  const code = info.code;
  const tag = safeName(modelName);
  const feDir = path.join(REPO_ROOT, 'tasks', taskId, 'extracted', code, info.entry);
  const appRoot = path.dirname(feDir);
  const outDir = path.join(REPO_ROOT, 'delivery', taskId, 'screenshots');
  const logDir = path.join(REPO_ROOT, 'tasks', taskId, 'logs');
  fs.mkdirSync(outDir, { recursive: true });
  fs.mkdirSync(logDir, { recursive: true });

  const py = process.env.QC_PYTHON || path.join(REPO_ROOT, 'tasks', taskId, '.venv', 'bin', 'python');
  const apiPort = 8000;
  const vitePort = 5500;
  const env = {
    ...process.env,
    APP_ENV: 'test',
    APP_DATABASE_BACKEND: 'sqlite',
    APP_MYSQL_ENABLED: 'false',
    APP_MYSQL2_ENABLED: 'false',
    APP_SMTP_ENABLED: 'false',
  };

  console.log(`\n==> ${modelName} (${code})`);
  const backendLog = fs.openSync(path.join(logDir, `${tag}_backend.log`), 'w');
  const backend = spawn(py, ['-m', 'uvicorn', 'spa_mm030_system.api:app', '--host', '127.0.0.1', '--port', String(apiPort)], {
    cwd: appRoot,
    env,
    detached: process.platform !== 'win32',
    stdio: ['ignore', backendLog, backendLog],
  });

  let frontend;
  try {
    const beOk = await waitForHttp(`http://127.0.0.1:${apiPort}/docs`);
    if (!beOk) throw new Error('backend did not expose /docs');

    const frontendLog = fs.openSync(path.join(logDir, `${tag}_frontend.log`), 'w');
    frontend = spawn('npm', ['run', 'dev', '--', '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'], {
      cwd: feDir,
      env,
      detached: process.platform !== 'win32',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    frontend.stdout.on('data', (d) => fs.writeSync(frontendLog, d));
    frontend.stderr.on('data', (d) => fs.writeSync(frontendLog, d));
    const baseUrl = await waitForVite(frontend);
    console.log(`   up: ${baseUrl}`);

    const browser = await chromium.launch({ headless: true });
    try {
      const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
      const page = await ctx.newPage();
      page.on('dialog', async (dialog) => {
        await dialog.accept('QC smoke');
      });
      await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.locator('#login-username').fill('admin');
      await page.locator('#login-password').fill('admin123456');
      await page.locator('#login-form button[type="submit"]').click();
      await page.waitForSelector('#dashboard-view:not(.hidden)', { timeout: 15000 }).catch(() => {});

      await clickView(page, 'dashboard-home-view');
      await screenshotVisible(page, path.join(outDir, `${tag}_01_dashboard.png`));
      await clickView(page, 'jobs-view');
      await screenshotVisible(page, path.join(outDir, `${tag}_02_jobs.png`));
      await clickView(page, 'quality-view');
      await screenshotVisible(page, path.join(outDir, `${tag}_03_quality.png`));
    } finally {
      await browser.close();
    }
  } finally {
    if (frontend) killTree(frontend.pid);
    killTree(backend.pid);
    fs.closeSync(backendLog);
    await new Promise((r) => setTimeout(r, 1500 + index * 200));
  }
}

async function main() {
  const args = parseArgs(process.argv);
  const mapPath = path.join(REPO_ROOT, 'tasks', args.taskId, 'model_map.json');
  const mm = JSON.parse(fs.readFileSync(mapPath, 'utf8'));
  const names = mm.sheet_columns && mm.sheet_columns.length ? mm.sheet_columns : Object.keys(mm.models || {});
  let idx = 0;
  for (const name of names) {
    if (args.only && args.only !== name && args.only !== (mm.models[name] || {}).code) continue;
    await captureOne(args.taskId, name, mm.models[name], idx++);
  }
}

main().catch((err) => {
  console.error(err.stack || err.message);
  process.exit(1);
});
