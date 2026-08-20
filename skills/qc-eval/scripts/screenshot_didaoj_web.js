// DidaOJ web config tasks: capture real Vite page screenshots with mocked
// network responses, or build errors when the model cannot run.

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');

function safe(name) {
  return String(name).replace(/[^0-9A-Za-z_.-]+/g, '_');
}

function readJson(p) {
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

function stripAnsi(s) {
  return String(s || '').replace(/\x1b\[[0-9;]*m/g, '');
}

function runCapture(cmd, args, cwd, timeoutMs = 90000) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, {
      cwd,
      shell: process.platform === 'win32',
      env: {
        ...process.env,
        BROWSER: 'none',
        CI: '1',
      },
    });
    let out = '';
    const timer = setTimeout(() => {
      out += `\n[timeout after ${timeoutMs}ms]\n`;
      try { child.kill('SIGKILL'); } catch (_) {}
    }, timeoutMs);
    child.stdout.on('data', d => { out += d.toString(); });
    child.stderr.on('data', d => { out += d.toString(); });
    child.on('close', code => {
      clearTimeout(timer);
      resolve({ code, out });
    });
  });
}

async function renderTerminal(browser, text, outPath) {
  const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });
  const esc = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  const lines = esc(stripAnsi(text)).split(/\r?\n/).slice(0, 80).join('\n');
  await page.setContent(`<!doctype html>
    <style>
      body{margin:0;background:#0d1117;color:#e6edf3;font-family:"Cascadia Mono","Microsoft YaHei UI","Microsoft YaHei","Segoe UI Symbol",Consolas,monospace}
      pre{white-space:pre-wrap;font-size:20px;line-height:1.4;margin:0;padding:22px}
      .bad{color:#ff6b6b}.ok{color:#55d184}
    </style>
    <pre>${lines}</pre>`);
  await page.screenshot({ path: outPath, fullPage: true });
  await page.close();
}

function startDev(cwd, port) {
  const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const child = spawn(npm, ['run', 'dev', '--', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
    cwd,
    shell: process.platform === 'win32',
  });
  let output = '';
  child.stdout.on('data', d => { output += d.toString(); });
  child.stderr.on('data', d => { output += d.toString(); });
  return { child, getOutput: () => output };
}

async function waitForServer(proc, port, timeoutMs = 45000) {
  const deadline = Date.now() + timeoutMs;
  const url = `http://127.0.0.1:${port}/`;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url);
      if (res.status < 500) return url;
    } catch (_) {}
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error(`dev server not ready on ${port}\n${proc.getOutput()}`);
}

async function setupRoutes(page) {
  const oj = { list: [
    { name: 'DidaOJ', url: 'https://oj.didapipa.com/', status: 'success' },
    { name: 'HDU', url: 'https://acm.hdu.edu.cn/', status: 'warning' },
  ] };
  const links = { list: [
    { name: 'Codeforces', url: 'https://codeforces.com/' },
    { name: 'AtCoder', url: 'https://atcoder.jp/' },
  ] };
  const user = {
    id: 1,
    userId: 1,
    username: 'qc_admin',
    nickname: 'QC Admin',
    roles: ['r-admin'],
  };
  await page.route('**/api/**', r => r.fulfill({ json: { code: 0, data: {} } }));
  await page.route('**/api/user/login/refresh', r => r.fulfill({ json: { code: 0, data: user } }));
  await page.route('**/api/user/checkin**', r => r.fulfill({ json: { code: 0, data: {} } }));
  await page.route('**/system/notification.json**', r => r.fulfill({ json: { theme: 'info', content: 'QC runtime notification' } }));
  await page.route('**/system/announcement.json**', r => r.fulfill({ json: { title: 'QC runtime announcement', content: 'mocked announcement body' } }));
  await page.route('**/system/oj-status.json**', r => r.fulfill({ json: oj }));
  await page.route('**/system/friend-link.json**', r => r.fulfill({ json: links }));
  await page.route('**/api/system/oj-status', r => r.fulfill({ json: { code: 0, data: {} } }));
  await page.route('**/api/system/friend-link', r => r.fulfill({ json: { code: 0, data: { content: 'mocked announcement body' } } }));
}

function existingBuildFailure(taskId, tag) {
  const logDir = path.join(REPO_ROOT, 'tasks', taskId, 'logs');
  const names = [`${tag}_repair_build.log`, `${tag}_build-only.log`, `${tag}_terminal_build.log`];
  for (const name of names) {
    const p = path.join(logDir, name);
    if (!fs.existsSync(p)) continue;
    const text = fs.readFileSync(p, 'utf8');
    if (/Build failed|error during build|SyntaxError|\[vite:vue\]/i.test(text)) {
      return { name, text };
    }
  }
  return null;
}

async function screenshotModel(browser, taskId, col, info, port, outDir) {
  const tag = safe(col);
  const cwd = path.join(REPO_ROOT, 'tasks', taskId, 'extracted', info.code, 'DidaOJ-web');
  if (!fs.existsSync(cwd)) throw new Error(`missing ${cwd}`);

  const knownBuildFailure = existingBuildFailure(taskId, tag);
  if (knownBuildFailure) {
    const out = path.join(outDir, `${tag}_01_build_error.png`);
    await renderTerminal(browser, knownBuildFailure.text, out);
    return;
  }

  const dev = startDev(cwd, port);
  try {
    const base = await waitForServer(dev, port);
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await context.addInitScript(() => {
      window.localStorage.setItem('user', JSON.stringify({
        userId: 1,
        username: 'qc_admin',
        nickname: 'QC Admin',
        roles: ['r-admin'],
      }));
    });
    const page = await context.newPage();
    await setupRoutes(page);
    await page.goto(`${base}manage/web`, { waitUntil: 'networkidle', timeout: 45000 });
    await page.waitForTimeout(1200);
    await page.screenshot({ path: path.join(outDir, `${tag}_01_page_manage_web.png`), fullPage: false });

    const judgeCard = page.locator('text=判官状态').first();
    if (await judgeCard.count()) {
      await judgeCard.scrollIntoViewIfNeeded();
      await page.waitForTimeout(300);
    }
    const editButtons = page.locator('button:has-text("编辑")');
    const n = await editButtons.count();
    if (n) {
      await editButtons.nth(Math.min(1, n - 1)).click();
      await page.waitForTimeout(700);
      await page.screenshot({ path: path.join(outDir, `${tag}_02_page_config_edit.png`), fullPage: false });
    }
    await context.close();
  } finally {
    try { dev.child.kill('SIGTERM'); } catch (_) {}
    if (process.platform === 'win32') {
      try { spawn('taskkill', ['/F', '/T', '/PID', String(dev.child.pid)]); } catch (_) {}
    }
  }
}

async function main() {
  const taskId = process.argv[2];
  if (!taskId) {
    console.error('usage: node screenshot_didaoj_web.js <TASK_ID>');
    process.exit(2);
  }
  const taskDir = path.join(REPO_ROOT, 'tasks', taskId);
  const outDir = path.join(REPO_ROOT, 'delivery', taskId, 'screenshots');
  fs.mkdirSync(outDir, { recursive: true });
  fs.mkdirSync(path.join(taskDir, 'logs'), { recursive: true });
  for (const f of fs.readdirSync(outDir)) {
    if (f.endsWith('.png')) fs.unlinkSync(path.join(outDir, f));
  }
  const map = readJson(path.join(taskDir, 'model_map.json'));
  const browser = await chromium.launch({ headless: true });
  try {
    let port = 5520;
    for (const col of map.sheet_columns) {
      await screenshotModel(browser, taskId, col, map.models[col], port++, outDir);
    }
  } finally {
    await browser.close();
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
