// Custom capture for E8XLOQ: React + Node.js custom HTTP.
// For each model: wipe users, start backend + vite, register admin,
// open providers admin and generation form pages, screenshot.

const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const HERE = __dirname;
const REPO_ROOT = path.resolve(HERE, '..', '..', '..');
const TASK_ID = 'E8XLOQ';
const outDir = path.join(REPO_ROOT, 'delivery', TASK_ID, 'screenshots');
fs.mkdirSync(outDir, { recursive: true });

const mapPath = path.join(REPO_ROOT, 'tasks', TASK_ID, 'model_map.json');
const map = JSON.parse(fs.readFileSync(mapPath, 'utf-8'));

function sanitize(s) { return s.replace(/[^A-Za-z0-9._-]+/g, '_'); }
function stripAnsi(s) { return s.replace(/\x1b\[[0-9;]*m/g, ''); }
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function killTree(pid) {
  if (!pid) return;
  if (process.platform === 'win32') {
    try { spawnSync('taskkill', ['/PID', String(pid), '/F', '/T'], { stdio: 'ignore' }); } catch {}
  } else {
    try { process.kill(-pid, 'SIGTERM'); } catch {}
  }
}

async function waitForViteUrl(child, timeoutMs = 60000) {
  return new Promise((resolve, reject) => {
    let buf = '';
    const t = setTimeout(() => reject(new Error('vite timeout: ' + buf.slice(-500))), timeoutMs);
    const on = (chunk) => {
      buf += chunk.toString();
      const m = stripAnsi(buf).match(/Local:\s*(https?:\/\/[^\s]+?\/)/);
      if (m) { clearTimeout(t); resolve(m[1]); }
    };
    child.stdout.on('data', on);
    child.stderr.on('data', on);
  });
}

async function waitForHttp(url, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await new Promise((resolve, reject) => {
        const req = http.get(url, (res) => { res.resume(); res.on('end', resolve); });
        req.on('error', reject);
        req.setTimeout(2000, () => req.destroy(new Error('t')));
      });
      return true;
    } catch { await sleep(1000); }
  }
  return false;
}

async function postJson(url, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const u = new URL(url);
    const req = http.request({
      method: 'POST', hostname: u.hostname, port: u.port, path: u.pathname,
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) },
    }, res => {
      let buf = '';
      res.on('data', c => buf += c);
      res.on('end', () => resolve({ status: res.statusCode, body: buf }));
    });
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

function wipeUsers(dbPath) {
  const db = JSON.parse(fs.readFileSync(dbPath, 'utf-8'));
  db.users = [];
  db.sessions = [];
  fs.writeFileSync(dbPath, JSON.stringify(db, null, 2));
}

async function processOne(col, code, backendPort, vitePort) {
  const tag = sanitize(col);
  const modelDir = path.join(REPO_ROOT, 'tasks', TASK_ID, 'extracted', code);
  const dbPath = path.join(modelDir, 'server', 'data', 'database.json');
  const dbBackup = fs.readFileSync(dbPath, 'utf-8');

  console.log(`\n== ${col} (${code}) backend=${backendPort} vite=${vitePort} ==`);

  wipeUsers(dbPath);

  const backend = spawn(process.execPath, ['server/index.js'], {
    cwd: modelDir,
    env: { ...process.env, PORT: String(backendPort), SERVER_PORT: String(backendPort) },
    detached: process.platform !== 'win32',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let beLog = '';
  backend.stdout.on('data', c => beLog += c);
  backend.stderr.on('data', c => beLog += c);

  const viteBin = path.join(modelDir, 'node_modules', '.bin', process.platform === 'win32' ? 'vite.cmd' : 'vite');
  const vite = spawn(viteBin, ['--port', String(vitePort), '--strictPort', '--host', '127.0.0.1'], {
    cwd: modelDir,
    env: { ...process.env, VITE_API_PORT: String(backendPort) },
    detached: process.platform !== 'win32',
    stdio: ['ignore', 'pipe', 'pipe'],
    shell: process.platform === 'win32',
  });

  const cleanup = () => { killTree(backend.pid); killTree(vite.pid); fs.writeFileSync(dbPath, dbBackup); };
  try {
    const beReady = await waitForHttp(`http://127.0.0.1:${backendPort}/api/providers`, 15000);
    if (!beReady) throw new Error('backend not ready\n' + beLog.slice(-800));

    // Some models may not have /api/providers unauthed. Try direct root
    const anyBe = await waitForHttp(`http://127.0.0.1:${backendPort}/`, 5000);

    const viteUrl = await waitForViteUrl(vite, 60000);
    console.log(`   vite up: ${viteUrl}`);

    // Vite proxy hits localhost:3001 by default. We need to patch proxy target or set port.
    // Check vite.config.js of each model — some use env var VITE_API_PORT? unlikely.
    // Just set backend to 3001 to match default vite.config? Multi-model conflicts.
    // For now, we've hardcoded the vite proxy target in each project. If it's 3001
    // and our backend is different, the proxy will fail. Let's use 3001 for one model at a time.

    // Register admin via backend directly
    let reg = await postJson(`http://127.0.0.1:${backendPort}/api/auth/register`,
      { email: 'admin@qc.local', password: 'admin123', name: 'qc', nickname: 'qc' });
    if (reg.status !== 200 && reg.status !== 201) {
      // try /api/register
      reg = await postJson(`http://127.0.0.1:${backendPort}/api/register`,
        { email: 'admin@qc.local', password: 'admin123', name: 'qc', nickname: 'qc' });
    }
    console.log(`   register: ${reg.status}`);
    let token = null; let userObj = null;
    try { const j = JSON.parse(reg.body); token = j.token; userObj = { ...j.user, token: j.token }; } catch {}
    console.log(`   token: ${token ? token.slice(0, 20) + '...' : 'NONE'} role=${userObj?.role}`);

    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();

    // Seed localStorage token by navigating first then setting
    await page.goto(viteUrl, { waitUntil: 'domcontentloaded' });
    if (userObj) {
      await page.evaluate((u) => {
        localStorage.setItem('gallery:auth', JSON.stringify(u));
      }, userObj);
    }

    // Screenshot 01: login/home
    await page.goto(viteUrl, { waitUntil: 'networkidle', timeout: 20000 }).catch(() => {});
    await sleep(1500);
    const p01 = path.join(outDir, `${tag}_01_home.png`);
    await page.screenshot({ path: p01, fullPage: false });
    console.log(`   [ok] ${p01}`);

    // Screenshot 02: admin providers
    await page.goto(viteUrl + 'admin', { waitUntil: 'networkidle', timeout: 20000 }).catch(() => {});
    await sleep(2000);
    const p02 = path.join(outDir, `${tag}_02_admin.png`);
    await page.screenshot({ path: p02, fullPage: false });
    console.log(`   [ok] ${p02}`);

    // Screenshot 03: full page admin (long)
    const p03 = path.join(outDir, `${tag}_03_admin_full.png`);
    await page.screenshot({ path: p03, fullPage: true });
    console.log(`   [ok] ${p03}`);

    await browser.close();
  } catch (e) {
    console.error(`   ERR: ${e.message}`);
    // still take screenshot of whatever loaded
  } finally {
    cleanup();
    await sleep(1000);
  }
}

(async () => {
  const models = [
    ['30B-0616E-OPD', '5SIDV'],
    ['30B-Release-Merge-0616E-29', '6U7Q4'],
    ['30B-Merge-0618B-AA', '9G5OO'],
    ['Opus 4.7', 'PDCOF'],
  ];
  // Use a fresh port each time; backend 3001 to match vite.config default
  for (const [col, code] of models) {
    await processOne(col, code, 3001, 5173);
    await sleep(2000);
  }
})();
