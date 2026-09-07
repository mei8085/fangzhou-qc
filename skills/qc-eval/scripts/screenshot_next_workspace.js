#!/usr/bin/env node
/*
 * Capture real Next.js workspace pages for each model artifact.
 * Evidence images are plain browser screenshots with no overlays or labels.
 */
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');
const { preferredPortBase } = require('./lib/concurrency');

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const taskId = process.argv[2];

if (!taskId) {
  console.error('Usage: node screenshot_next_workspace.js <TASK_ID> [--route /workspace] [--base-port 5310]');
  process.exit(2);
}

let route = '/workspace';
let basePort = null;
for (let i = 3; i < process.argv.length; i += 1) {
  if (process.argv[i] === '--route') {
    route = process.argv[i + 1] || route;
    i += 1;
  } else if (process.argv[i] === '--base-port') {
    basePort = Number(process.argv[i + 1]);
    i += 1;
  }
}

const taskDir = path.join(REPO_ROOT, 'tasks', taskId);
basePort ??= preferredPortBase(taskId, 'screenshot-next-workspace', 8);
const outDir = path.join(REPO_ROOT, 'delivery', taskId, 'screenshots');
fs.mkdirSync(outDir, { recursive: true });
fs.mkdirSync(path.join(taskDir, 'logs'), { recursive: true });

const modelMap = JSON.parse(fs.readFileSync(path.join(taskDir, 'model_map.json'), 'utf8'));

function safe(label) {
  return label.replace(/ /g, '_');
}

function waitForServer(child, port, timeoutMs = 60000) {
  return new Promise((resolve, reject) => {
    let buf = '';
    const timer = setTimeout(
      () => reject(new Error(`next dev timeout on ${port}\n${buf.slice(-2000)}`)),
      timeoutMs,
    );
    const onData = (data) => {
      buf += data.toString();
      if (buf.includes('Ready') || buf.includes('Local:') || buf.includes(`localhost:${port}`)) {
        clearTimeout(timer);
        resolve(buf);
      }
    };
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
    child.on('exit', (code) => {
      clearTimeout(timer);
      reject(new Error(`next dev exited ${code}\n${buf.slice(-2000)}`));
    });
  });
}

async function killProcessTree(child) {
  if (!child || child.killed) return;
  if (process.platform === 'win32') {
    await new Promise((resolve) => {
      spawn('taskkill', ['/pid', String(child.pid), '/f', '/t']).on('exit', resolve);
    });
  } else {
    child.kill('SIGTERM');
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  let idx = 0;
  let failures = 0;

  for (const [col, info] of Object.entries(modelMap.models)) {
    const code = info.code;
    const modelDir = path.join(taskDir, 'extracted', code, info.entry || '.');
    const nextBin = path.join(modelDir, 'node_modules', 'next', 'dist', 'bin', 'next');
    const port = basePort + idx;
    idx += 1;

    const logPath = path.join(taskDir, 'logs', `${code}-dev-workspace.log`);
    let log = `PS> cd ${modelDir}; node node_modules/next/dist/bin/next dev -p ${port} -H 127.0.0.1\n`;

    if (!fs.existsSync(nextBin)) {
      log += `missing next binary: ${nextBin}\nEXIT_CODE=1\n`;
      fs.writeFileSync(logPath, log, 'utf8');
      console.error(`[${code}] missing next binary`);
      failures += 1;
      continue;
    }

    const child = spawn(process.execPath, [nextBin, 'dev', '-p', String(port), '-H', '127.0.0.1'], {
      cwd: modelDir,
      env: { ...process.env, BROWSER: 'none' },
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    child.stdout.on('data', (data) => {
      log += data.toString();
    });
    child.stderr.on('data', (data) => {
      log += data.toString();
    });

    try {
      await waitForServer(child, port);
      const page = await browser.newPage({
        viewport: { width: 1440, height: 1000 },
        deviceScaleFactor: 1,
      });
      page.on('console', (msg) => {
        if (msg.type() === 'error') log += `\n[console error] ${msg.text()}\n`;
      });
      await page.goto(`http://127.0.0.1:${port}${route}`, {
        waitUntil: 'networkidle',
        timeout: 45000,
      });
      const out = path.join(outDir, `${safe(col)}_02_workspace.png`);
      await page.screenshot({ path: out, fullPage: false });
      await page.close();
      log += `\nSCREENSHOT=${out}\nEXIT_CODE=0\n`;
      console.log(`[${code}] ${route} screenshot OK`);
    } catch (err) {
      log += `\nERROR=${err.stack || err}\nEXIT_CODE=1\n`;
      console.error(`[${code}] ${route} screenshot failed: ${err.message}`);
      failures += 1;
    } finally {
      fs.writeFileSync(logPath, log, 'utf8');
      await killProcessTree(child);
    }
  }

  await browser.close();
  process.exit(failures ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
