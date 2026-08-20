#!/usr/bin/env node
// Capture MiMo Voice Studio verification screens for full-stack React tasks.
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..', '..');
const taskId = process.argv[2];
if (!taskId) {
  console.error('usage: node skills/qc-eval/scripts/screenshot_mimo_voice.js <TASK_ID>');
  process.exit(2);
}

const taskDir = path.join(ROOT, 'tasks', taskId);
const deliveryDir = path.join(ROOT, 'delivery', taskId, 'screenshots');
fs.mkdirSync(deliveryDir, { recursive: true });

const map = JSON.parse(fs.readFileSync(path.join(taskDir, 'model_map.json'), 'utf8'));

const CONFIG = {
  '60B0614C': {
    backend: ['python', ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8000']],
    backendPort: 8000,
    frontendEntry: 'frontend',
    frontendPort: 5173,
    pages: [
      ['01_dashboard', async (page, base) => page.goto(base)],
      ['02_studio', async (page) => page.getByText('TTS Studio', { exact: true }).click()],
      ['03_voice_lab', async (page) => page.getByText('Voice Lab', { exact: true }).click()],
    ],
  },
  'Opus 4.6': {
    backend: ['python', ['-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1', '--port', '8000']],
    backendPort: 8000,
    frontendEntry: 'frontend',
    frontendPort: 5174,
    pages: [
      ['01_dashboard', async (page, base) => page.goto(base)],
      ['02_studio', async (page, base) => page.goto(`${base}studio`)],
      ['03_voice_lab', async (page, base) => page.goto(`${base}voice-lab`)],
    ],
  },
  '60B0613H': {
    backend: ['python', ['-m', 'uvicorn', 'server.main:app', '--host', '127.0.0.1', '--port', '8000']],
    backendPort: 8000,
    frontendEntry: 'frontend',
    frontendPort: 5175,
    pages: [
      ['01_dashboard', async (page, base) => page.goto(base)],
      ['02_studio', async (page, base) => page.goto(`${base}studio`)],
      ['03_voice_lab', async (page, base) => page.goto(`${base}voice-lab`)],
    ],
  },
  '60B0605F': {
    backend: ['python', ['-m', 'uvicorn', 'app.backend.main:app', '--host', '127.0.0.1', '--port', '8765']],
    backendPort: 8765,
    frontendEntry: 'app/frontend',
    frontendPort: 5176,
    pages: [
      ['01_dashboard', async (page, base) => page.goto(`${base}#/`)],
      ['02_studio', async (page, base) => page.goto(`${base}#/studio`)],
      ['03_voice_lab', async (page, base) => page.goto(`${base}#/voice-lab`)],
    ],
  },
};

function safeName(name) {
  return name.replace(/\s+/g, '_').replace(/[^\w.-]/g, '_');
}

function spawnLogged(command, args, cwd, label) {
  const proc = spawn(command, args, { cwd, shell: process.platform === 'win32', stdio: ['ignore', 'pipe', 'pipe'] });
  proc.stdout.on('data', (d) => process.stdout.write(`[${label}] ${d}`));
  proc.stderr.on('data', (d) => process.stderr.write(`[${label}] ${d}`));
  return proc;
}

function killTree(proc) {
  if (!proc || proc.killed) return Promise.resolve();
  return new Promise((resolve) => {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(proc.pid), '/f', '/t'], { shell: true })
        .on('close', resolve);
    } else {
      proc.kill('SIGTERM');
      resolve();
    }
  });
}

async function waitForHttp(url, ms = 45000) {
  const deadline = Date.now() + ms;
  let last = '';
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url);
      if (res.status < 500) return;
      last = `${res.status} ${res.statusText}`;
    } catch (err) {
      last = err.message;
    }
    await new Promise((r) => setTimeout(r, 700));
  }
  throw new Error(`timeout waiting for ${url}: ${last}`);
}

async function captureModel(browser, col) {
  const model = map.models[col];
  const cfg = CONFIG[col];
  if (!model || !cfg) return;

  const codeDir = path.join(taskDir, 'extracted', model.code);
  const frontendDir = path.join(codeDir, cfg.frontendEntry);
  console.log(`==> ${col} (${model.code})`);

  const backend = spawnLogged(cfg.backend[0], cfg.backend[1], codeDir, `${col} backend`);
  const frontend = spawnLogged('npm', ['run', 'dev', '--', '--host', '127.0.0.1', '--port', String(cfg.frontendPort), '--strictPort'], frontendDir, `${col} vite`);
  try {
    await waitForHttp(`http://127.0.0.1:${cfg.backendPort}/api/health`);
    await waitForHttp(`http://127.0.0.1:${cfg.frontendPort}/`);

    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
    page.setDefaultTimeout(8000);
    const base = `http://127.0.0.1:${cfg.frontendPort}/`;
    for (const [name, navigate] of cfg.pages) {
      await navigate(page, base);
      await page.waitForLoadState('networkidle').catch(() => {});
      await page.waitForTimeout(900);
      const out = path.join(deliveryDir, `${safeName(col)}_${name}.png`);
      await page.screenshot({ path: out, fullPage: false });
      console.log(`   ${path.basename(out)}`);
    }
    await page.close();
  } finally {
    await killTree(frontend);
    await killTree(backend);
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const col of map.sheet_columns) {
      await captureModel(browser, col);
    }
  } finally {
    await browser.close();
  }
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
