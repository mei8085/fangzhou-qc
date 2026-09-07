#!/usr/bin/env node
/**
 * Run Docker-based ASP.NET Core deliverables on u03l and capture real evidence.
 *
 * Local machine is used only for rsync, SSH port forwarding, and Playwright
 * screenshots. All Docker commands run on the u03l workstation.
 */

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');
const { preferredPortBase, reservePortBlock } = require('./lib/concurrency');

const REPO_ROOT = path.resolve(__dirname, '../../..');
const SSH_HOST = 'u03l';
const REMOTE_BASE = '/home/fz/qc-eval/dotnet-smoke';
const SSH_OPTS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', '-o', 'StrictHostKeyChecking=accept-new'];

function run(cmd, args, opts = {}) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, {
      cwd: opts.cwd || REPO_ROOT,
      env: opts.env || process.env,
      shell: false,
      windowsHide: true,
    });
    let out = '';
    child.stdout.on('data', (d) => { out += d.toString(); if (!opts.quiet) process.stdout.write(d); });
    child.stderr.on('data', (d) => { out += d.toString(); if (!opts.quiet) process.stderr.write(d); });
    child.on('close', (code) => resolve({ code, out }));
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function q(s) {
  return `'${String(s).replaceAll("'", "'\\''")}'`;
}

async function ssh(command, opts = {}) {
  return run('ssh', [...SSH_OPTS, SSH_HOST, command], opts);
}

function spawnTunnel(localPort, remotePort) {
  const child = spawn('ssh', [
    ...SSH_OPTS,
    '-o', 'ExitOnForwardFailure=yes',
    '-N',
    '-L', `${localPort}:localhost:${remotePort}`,
    SSH_HOST,
  ], {
    cwd: REPO_ROOT,
    windowsHide: true,
    stdio: 'ignore',
    detached: false,
  });
  return child;
}

function htmlEscape(s) {
  return String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

async function evidencePageScreenshot(text, outPath, title) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const body = htmlEscape(text.slice(-22000));
  await page.setContent(`<!doctype html>
<meta charset="utf-8">
<style>
  body { margin: 0; background: #101820; color: #eaf1f7; font: 14px "Cascadia Mono", "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI Symbol", Consolas, monospace; }
  pre { white-space: pre-wrap; line-height: 1.45; padding: 20px 24px; margin: 0; }
</style>
<pre>${body}</pre>`);
  await page.screenshot({ path: outPath, fullPage: true });
  await browser.close();
}

async function waitHealth(baseUrl, ms) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${baseUrl}/api/health`);
      if (res.ok) return true;
    } catch (_) {}
    await sleep(3000);
  }
  return false;
}

async function syncRepo(localRepo, remoteRepo) {
  await ssh(`mkdir -p ${q(remoteRepo)}`);
  const rsyncSource = localRepo
    .replace(/^([A-Za-z]):\\/, (_, d) => `/${d.toLowerCase()}/`)
    .replaceAll('\\', '/');
  const rsync = await run('rsync', [
    '-az', '--delete',
    '--exclude', 'bin/',
    '--exclude', 'obj/',
    '--exclude', '.git/',
    '-e', `ssh ${SSH_OPTS.join(' ')}`,
    `${rsyncSource}/`,
    `${SSH_HOST}:${remoteRepo}/`,
  ]);
  if (rsync.code !== 0) throw new Error(`rsync failed: ${rsync.out}`);
}

function findRepo(modelDir) {
  const stack = [modelDir];
  while (stack.length) {
    const cur = stack.pop();
    for (const name of fs.readdirSync(cur)) {
      const p = path.join(cur, name);
      if (!fs.statSync(p).isDirectory()) continue;
      if (fs.existsSync(path.join(p, 'docker-compose.yml'))) return p;
      stack.push(p);
    }
  }
  return null;
}

async function captureUi(baseUrl, outDir, tag, label) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(18000);

  await page.goto(baseUrl, { waitUntil: 'networkidle' });
  await page.screenshot({ path: path.join(outDir, `${tag}_01_login.png`), fullPage: true });

  for (const sel of ['input[name="Username"]', 'input[name="username"]', 'input#Username', 'input[type="text"]']) {
    if (await page.locator(sel).count()) {
      await page.locator(sel).first().fill('admin');
      break;
    }
  }
  for (const sel of ['input[name="Password"]', 'input[name="password"]', 'input#Password', 'input[type="password"]']) {
    if (await page.locator(sel).count()) {
      await page.locator(sel).first().fill('ChangeMe!2026');
      break;
    }
  }
  const submit = page.locator('button[type="submit"], input[type="submit"], button:has-text("Sign"), button:has-text("Login"), button:has-text("登录")').first();
  if (await submit.count()) {
    await submit.click();
    await page.waitForLoadState('networkidle').catch(() => {});
  }
  await sleep(1500);
  await page.screenshot({ path: path.join(outDir, `${tag}_02_after_login.png`), fullPage: true });

  for (const route of ['/Dashboard', '/Documents', '/Jobs', '/Admin']) {
    try {
      await page.goto(`${baseUrl}${route}`, { waitUntil: 'networkidle', timeout: 18000 });
      await page.screenshot({ path: path.join(outDir, `${tag}_03_${route.slice(1).toLowerCase()}.png`), fullPage: true });
      break;
    } catch (_) {}
  }
  await browser.close();
  console.log(`  [shot] ${label}: real browser UI captured`);
}

async function remoteComposeDown(remoteRepo, project) {
  await ssh(`cd ${q(remoteRepo)} 2>/dev/null && docker compose -p ${q(project)} down -v --remove-orphans || true`, { quiet: true });
}

async function processModel(taskId, col, info, idx, localBase, remoteBase, mysqlBase) {
  const tag = col.replaceAll(' ', '_');
  const outDir = path.join(REPO_ROOT, 'delivery', taskId, 'screenshots');
  fs.mkdirSync(outDir, { recursive: true });
  const localRepo = findRepo(path.join(REPO_ROOT, 'tasks', taskId, 'extracted', info.code));
  if (!localRepo) {
    await evidencePageScreenshot('No docker-compose.yml found in extracted deliverable.', path.join(outDir, `${tag}_01_start_error.png`), `${col} real run evidence`);
    return;
  }

  const remoteRepo = `${REMOTE_BASE}/${taskId}/${info.code}/repo`;
  const project = `qc_${taskId.toLowerCase()}_${info.code.toLowerCase()}`;
  const remotePort = remoteBase + idx;
  const mysqlPort = mysqlBase + idx;
  const localPort = localBase + idx;
  console.log(`\n==> ${col} (${info.code}) on ${SSH_HOST}`);
  await syncRepo(localRepo, remoteRepo);
  await remoteComposeDown(remoteRepo, project);

  const envPrefix = [
    `COMPOSE_PROJECT_NAME=${q(project)}`,
    `APP_HOST_PORT=${remotePort}`,
    `MYSQL_HOST_PORT=${mysqlPort}`,
    'APT_MIRROR_HOST=mirrors.aliyun.com',
    'HOST_NUGET_CACHE=./.docker/nuget-cache',
  ].join(' ');
  const upCmd = `cd ${q(remoteRepo)} && ${envPrefix} docker compose -p ${q(project)} up -d --build stw-mysql stw-app`;
  const up = await ssh(upCmd, { quiet: false });

  let tunnel = null;
  try {
    if (up.code === 0) {
      tunnel = spawnTunnel(localPort, remotePort);
      await sleep(1200);
      const healthy = await waitHealth(`http://127.0.0.1:${localPort}`, 300000);
      if (healthy) {
        await captureUi(`http://127.0.0.1:${localPort}`, outDir, tag, col);
      } else {
        const logs = await ssh(`cd ${q(remoteRepo)} && docker compose -p ${q(project)} logs --no-color --tail 260`, { quiet: true });
        await evidencePageScreenshot(`${up.out}\n\n--- remote docker logs ---\n${logs.out}`, path.join(outDir, `${tag}_01_start_error.png`), `${col} real startup failure on u03l`);
      }
    } else {
      const logs = await ssh(`cd ${q(remoteRepo)} && docker compose -p ${q(project)} logs --no-color --tail 260 || true`, { quiet: true });
      await evidencePageScreenshot(`${up.out}\n\n--- remote docker logs ---\n${logs.out}`, path.join(outDir, `${tag}_01_start_error.png`), `${col} real build failure on u03l`);
    }
  } finally {
    if (tunnel) tunnel.kill();
    await remoteComposeDown(remoteRepo, project);
  }
}

async function main() {
  const taskId = process.argv[2];
  if (!taskId) {
    console.error('Usage: screenshot_dotnet_u03l.js <TASK_ID>');
    process.exit(2);
  }
  const host = await ssh('hostname && docker --version && docker compose version', { quiet: false });
  if (host.code !== 0) process.exit(host.code);
  const mm = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, 'tasks', taskId, 'model_map.json'), 'utf8'));
  const cols = (mm.sheet_columns || Object.keys(mm.models)).filter((col) => !(mm.models[col] || {}).missing);
  const count = Math.max(1, cols.length);
  const localLease = await reservePortBlock(taskId, 'screenshot-dotnet-local', count);
  const remoteBase = preferredPortBase(taskId, 'screenshot-dotnet-remote', count);
  const mysqlBase = preferredPortBase(taskId, 'screenshot-dotnet-mysql', count);
  console.log(`==> task-scoped ports local=${localLease.base} remote=${remoteBase} mysql=${mysqlBase}`);
  try {
    let idx = 0;
    for (const col of cols) {
      await processModel(taskId, col, mm.models[col], idx++, localLease.base, remoteBase, mysqlBase);
    }
  } finally {
    localLease.release();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
