#!/usr/bin/env node
// Capture ClickVisual /query runtime pages with mocked backend responses.

const fs = require('fs');
const path = require('path');
const http = require('http');
const { spawn, spawnSync } = require('child_process');
const { chromium } = require('playwright');
const { preferredPortBase } = require('./lib/concurrency');

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');

function safe(name) {
  return String(name).replace(/[^0-9A-Za-z_.-]+/g, '_');
}

function stripAnsi(s) {
  return String(s || '').replace(/\x1b\[[0-9;]*m/g, '');
}

function killTree(pid) {
  if (!pid) return;
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/F', '/T', '/PID', String(pid)], { stdio: 'ignore' });
  } else {
    try { process.kill(-pid); } catch (_) {}
    try { process.kill(pid); } catch (_) {}
  }
}

async function renderOutput(browser, text, outPath) {
  const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });
  const esc = (s) => stripAnsi(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  await page.setContent(`<!doctype html><meta charset="utf-8">
<style>
body{margin:0;background:#0d1117;color:#e6edf3;font-family:"Cascadia Mono","Microsoft YaHei UI","Microsoft YaHei","Segoe UI Symbol",Consolas,monospace}
pre{white-space:pre-wrap;font-size:22px;line-height:1.45;margin:0;padding:22px}
</style><pre>${esc(text).split(/\r?\n/).slice(-90).join('\n')}</pre>`);
  const box = await page.locator('pre').boundingBox();
  await page.screenshot({
    path: outPath,
    clip: {
      x: 0,
      y: 0,
      width: 1500,
      height: Math.min(Math.max(Math.ceil((box?.height || 0) + 8), 220), 950),
    },
  });
  await page.close();
}

function startUi(uiDir, port) {
  const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const child = spawn(npm, ['run', 'start:no-ui'], {
    cwd: uiDir,
    shell: process.platform === 'win32',
    env: {
      ...process.env,
      BROWSER: 'none',
      CI: '1',
      HOST: '127.0.0.1',
      PORT: String(port),
      UMI_UI: 'none',
      UMI_ENV: 'dev',
      MFSU: 'false',
    },
    windowsHide: true,
  });
  let output = '';
  child.stdout.on('data', d => { output += d.toString(); });
  child.stderr.on('data', d => { output += d.toString(); });
  return { child, output: () => output };
}

function buildUi(uiDir) {
  const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const res = spawnSync(npm, ['run', 'build'], {
    cwd: uiDir,
    shell: process.platform === 'win32',
    env: { ...process.env, CI: '1' },
    encoding: 'utf8',
    windowsHide: true,
    timeout: 300000,
  });
  return {
    ok: res.status === 0,
    output: [res.stdout, res.stderr].filter(Boolean).join('\n'),
  };
}

function contentType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  return {
    '.html': 'text/html; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.ico': 'image/x-icon',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
  }[ext] || 'application/octet-stream';
}

function serveDist(distDir, port) {
  const server = http.createServer((req, res) => {
    const reqUrl = new URL(req.url, `http://127.0.0.1:${port}`);
    let rel = decodeURIComponent(reqUrl.pathname).replace(/^\/+/, '');
    let filePath = path.join(distDir, rel);
    if (!filePath.startsWith(distDir)) {
      res.writeHead(403);
      res.end('forbidden');
      return;
    }
    if (!rel || !fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
      const routeIndex = path.join(distDir, rel, 'index.html');
      filePath = fs.existsSync(routeIndex) ? routeIndex : path.join(distDir, 'index.html');
    }
    if (!fs.existsSync(filePath)) {
      res.writeHead(404);
      res.end('not found');
      return;
    }
    res.writeHead(200, { 'content-type': contentType(filePath) });
    fs.createReadStream(filePath).pipe(res);
  });
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, '127.0.0.1', () => resolve({
      url: `http://127.0.0.1:${port}`,
      close: () => new Promise(r => server.close(r)),
    }));
  });
}

async function waitForUi(proc, port, timeoutMs = 120000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const clean = stripAnsi(proc.output());
    const found = clean.match(/Local:\s*(http:\/\/(?:localhost|127\.0\.0\.1):(\d+))/);
    const url = found ? found[1].replace('localhost', '127.0.0.1') : `http://127.0.0.1:${port}`;
    try {
      const res = await fetch(url);
      if (res.status < 500) return url;
    } catch (_) {}
    if (proc.child.exitCode !== null) break;
    await new Promise(r => setTimeout(r, 700));
  }
  throw new Error(stripAnsi(proc.output()).slice(-12000) || `dev server not ready on ${port}`);
}

function mockJson(url) {
  const u = new URL(url);
  const p = u.pathname;
  const now = Math.floor(Date.now() / 1000);
  const logRaw = {
    _time_nanosecond_: '2026-07-14T10:30:00.000Z',
    level: 'ERROR',
    host: 'web01',
    zero_count: 0,
    zero_string: '0',
    empty_text: '',
    empty_array: [],
    empty_object: {},
    null_field: null,
    message: 'ERROR Error error login request failed, service=auth-service, status=500',
    trace_id: 'qc-trace-9AP9AS',
  };
  const log = {
    _time_second_: now,
    _time_nanosecond_: logRaw._time_nanosecond_,
    level: 'ERROR',
    host: 'web01',
    zero_count: 0,
    zero_string: '0',
    empty_text: '',
    empty_array: [],
    empty_object: {},
    null_field: null,
    message: logRaw.message,
    _raw_log_: JSON.stringify(logRaw),
  };

  if (p.endsWith('/api/v1/users/info')) {
    return { code: 0, data: { id: 1, nickname: 'clickvisual', username: 'clickvisual', access: 'admin', oauth: '', oauthId: '' } };
  }
  if (p.endsWith('/api/v1/menus/list')) {
    return { code: 0, data: [
      { path: '/query', name: '日志', icon: '', children: [] },
    ] };
  }
  if (p.endsWith('/api/v1/pms/commonInfo')) {
    return { code: 0, data: {
      prefixes_info: [],
      app_subResources_info: [],
      configRsrc_subResources_info: [],
      all_acts_info: [],
      domainCascader: [],
    } };
  }
  if (p.endsWith('/api/v2/base/instances')) {
    return { code: 0, data: [
      { id: 1, name: 'clickhouse', datasource: 'clickhouse', desc: 'mocked instance', databases: [
        { id: 1, iid: 1, name: 'test', databaseName: 'test', desc: 'mocked database', tables: [
          { id: 100, tableName: 'logs', createType: 0, desc: 'logs', relTraceTableId: 0, databaseId: 1 },
        ] },
      ] },
    ] };
  }
  if (p.endsWith('/api/v1/tables/100')) {
    return { code: 0, data: {
      id: 100,
      name: 'logs',
      tableName: 'logs',
      createType: 0,
      desc: 'logs',
      traceTableId: 0,
      database: { id: 1, iid: 1, name: 'test', databaseName: 'test', datasourceType: 'clickhouse', instanceName: 'clickhouse', mode: 0, desc: '', instanceDesc: '' },
      sqlContent: { keys: [], data: {} },
    } };
  }
  if (p.endsWith('/api/v2/storage/100/columns')) {
    return { code: 0, data: [
      { name: '_raw_log_' },
      { name: 'message' },
      { name: 'level' },
      { name: 'host' },
      { name: '_time_nanosecond_' },
    ] };
  }
  if (p.endsWith('/api/v2/storage/100/analysis-fields')) {
    return { code: 0, data: {
      baseFields: [{ field: '_time_nanosecond_', alias: '_time_nanosecond_', typ: 0, rootName: '', jsonIndex: [], hashTyp: 0, ctime: now, utime: now }],
      logFields: [
        { field: 'message', alias: 'message', typ: 0, rootName: '', jsonIndex: [], hashTyp: 0, ctime: now, utime: now },
        { field: 'level', alias: 'level', typ: 0, rootName: '', jsonIndex: [], hashTyp: 0, ctime: now, utime: now },
        { field: 'host', alias: 'host', typ: 0, rootName: '', jsonIndex: [], hashTyp: 0, ctime: now, utime: now },
        { field: 'zero_count', alias: 'zero_count', typ: 0, rootName: '', jsonIndex: [], hashTyp: 0, ctime: now, utime: now },
        { field: 'zero_string', alias: 'zero_string', typ: 0, rootName: '', jsonIndex: [], hashTyp: 0, ctime: now, utime: now },
        { field: 'empty_text', alias: 'empty_text', typ: 0, rootName: '', jsonIndex: [], hashTyp: 0, ctime: now, utime: now },
        { field: 'empty_array', alias: 'empty_array', typ: 0, rootName: '', jsonIndex: [], hashTyp: 0, ctime: now, utime: now },
        { field: 'empty_object', alias: 'empty_object', typ: 0, rootName: '', jsonIndex: [], hashTyp: 0, ctime: now, utime: now },
        { field: 'null_field', alias: 'null_field', typ: 0, rootName: '', jsonIndex: [], hashTyp: 0, ctime: now, utime: now },
      ],
    } };
  }
  if (p.endsWith('/api/v2/storage/collects')) {
    return { code: 0, data: [] };
  }
  if (p.endsWith('/api/v1/tables/100/logs')) {
    return { code: 0, data: {
      count: 1,
      cost: 23,
      logs: [log],
      hiddenFields: [],
      defaultFields: [],
      keys: [],
      limited: 0,
      terms: [],
      query: "`message` ILIKE '%error%'",
      where: "`message` ILIKE '%error%'",
      isTrace: 0,
      isNeedSort: false,
      sortRule: [],
    } };
  }
  if (p.endsWith('/api/v1/tables/100/charts')) {
    return { code: 0, data: {
      count: 1,
      progress: '100%',
      histograms: [
        { count: 0, from: (now - 600) * 1000, to: (now - 300) * 1000, progress: '100%' },
        { count: 1, from: (now - 300) * 1000, to: now * 1000, progress: '100%' },
      ],
    } };
  }
  if (p.includes('/api/')) {
    return { code: 0, data: [] };
  }
  return null;
}

async function setupRoutes(page) {
  await page.route('**/api/**', route => {
    const data = mockJson(route.request().url());
    route.fulfill({ json: data || { code: 0, data: [] } });
  });
}

async function waitForLogPage(page, url) {
  const deadline = Date.now() + 90000;
  let lastText = '';
  while (Date.now() < deadline) {
    lastText = await page.locator('body').innerText().catch(() => '');
    if (lastText && !lastText.includes('Bundling') && (lastText.includes('zero_count') || lastText.includes('日志总条数') || lastText.includes('ERROR'))) {
      return;
    }
    await page.waitForTimeout(5000);
    if (lastText.includes('Bundling') && Date.now() < deadline) {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 }).catch(() => {});
    }
  }
  throw new Error(`log page did not finish loading; last body text:\n${lastText.slice(0, 2000)}`);
}

async function clickHideZero(page) {
  const icon = page.locator('.anticon-eye, .anticon-eye-invisible').last();
  if (await icon.count()) {
    await icon.locator('xpath=ancestor::button[1]').click();
    return true;
  }
  const zeroButton = page.getByRole('button', { name: /^0$/ }).first();
  if (await zeroButton.count()) {
    await zeroButton.click();
    return true;
  }
  return false;
}

async function capturePage(browser, base, tag, outDir) {
  const context = await browser.newContext({ viewport: { width: 2048, height: 1000 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const pageMessages = [];
  page.on('pageerror', e => pageMessages.push(`pageerror: ${e.message}`));
  page.on('console', m => {
    if (['error', 'warning'].includes(m.type())) pageMessages.push(`console ${m.type()}: ${m.text()}`);
  });
  page.on('requestfailed', r => pageMessages.push(`requestfailed: ${r.url()} ${r.failure()?.errorText || ''}`));
  await setupRoutes(page);
  const url = `${base}/share?tid=100&kw=%60message%60%20like%20%27%25error%25%27&page=1&size=10&tab=relative&index=2&queryType=log&logState=0`;
  await page.goto(url, {
    waitUntil: 'domcontentloaded',
    timeout: 90000,
  });
  await waitForLogPage(page, url).catch(e => {
    throw new Error(`${e.message}\n${pageMessages.slice(-20).join('\n')}`);
  });
  await page.waitForTimeout(3000);
  await page.screenshot({ path: path.join(outDir, `${tag}_01_frontend_page_zero_visible.png`), fullPage: false });
  if (await clickHideZero(page)) {
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(outDir, `${tag}_02_frontend_page_zero_hidden.png`), fullPage: false });
  }
  await context.close();
}

async function processModel(browser, taskId, col, info, port, outDir, remoteBaseUrl = '', staticBuild = false) {
  const tag = safe(col);
  if (remoteBaseUrl) {
    await capturePage(browser, remoteBaseUrl.replace(/\/$/, ''), tag, outDir);
    return;
  }
  const uiDir = path.join(REPO_ROOT, 'tasks', taskId, 'extracted', info.code, 'ui');
  if (!fs.existsSync(path.join(uiDir, 'package.json'))) {
    await renderOutput(browser, `missing package.json in ${uiDir}`, path.join(outDir, `${tag}_02_frontend_start_error.png`));
    return;
  }
  if (!fs.existsSync(path.join(uiDir, 'node_modules', '.bin'))) {
    await renderOutput(browser, `missing node_modules in ${uiDir}`, path.join(outDir, `${tag}_02_frontend_start_error.png`));
    return;
  }

  if (staticBuild) {
    const distDir = path.join(uiDir, 'dist');
    const built = fs.existsSync(path.join(distDir, 'index.html'))
      ? { ok: true, output: `using existing build in ${distDir}` }
      : buildUi(uiDir);
    if (!built.ok) {
      await renderOutput(browser, built.output, path.join(outDir, `${tag}_02_frontend_start_error.png`));
      return;
    }
    const server = await serveDist(distDir, port);
    try {
      await capturePage(browser, server.url, tag, outDir);
    } catch (e) {
      await renderOutput(browser, `${e.message}\n\n${built.output}`, path.join(outDir, `${tag}_02_frontend_start_error.png`));
    } finally {
      await server.close();
    }
    return;
  }

  const dev = startUi(uiDir, port);
  try {
    const base = await waitForUi(dev, port);
    await capturePage(browser, base, tag, outDir);
  } catch (e) {
    await renderOutput(browser, `${e.message}\n\n${dev.output()}`, path.join(outDir, `${tag}_02_frontend_start_error.png`));
  } finally {
    killTree(dev.child.pid);
    await new Promise(r => setTimeout(r, 1000));
  }
}

async function main() {
  const taskId = process.argv[2];
  if (!taskId) {
    console.error('usage: node screenshot_clickvisual_logs.js <TASK_ID> [--only COL_OR_CODE] [--base-port PORT] [--static-build]');
    process.exit(2);
  }
  let only = '';
  let basePort = null;
  let baseUrl = '';
  let staticBuild = false;
  for (let i = 3; i < process.argv.length; i += 1) {
    if (process.argv[i] === '--only') only = process.argv[++i] || '';
    else if (process.argv[i] === '--base-port') basePort = Number(process.argv[++i]);
    else if (process.argv[i] === '--base-url') baseUrl = process.argv[++i] || '';
    else if (process.argv[i] === '--static-build') staticBuild = true;
  }
  const taskDir = path.join(REPO_ROOT, 'tasks', taskId);
  basePort ??= preferredPortBase(taskId, 'screenshot-clickvisual-logs', 8);
  const outDir = path.join(REPO_ROOT, 'delivery', taskId, 'screenshots');
  fs.mkdirSync(outDir, { recursive: true });
  for (const f of fs.readdirSync(outDir)) {
    if (
      f.endsWith('.png') &&
      (/_editor\.png$/.test(f) || /_frontend_(query_page|zero_visible|zero_hidden|page_zero_visible|page_zero_hidden|start_error)\.png$/.test(f))
    ) {
      fs.unlinkSync(path.join(outDir, f));
    }
  }
  const mm = JSON.parse(fs.readFileSync(path.join(taskDir, 'model_map.json'), 'utf8'));
  const browser = await chromium.launch({ headless: true });
  try {
    let port = basePort;
    for (const col of mm.sheet_columns) {
      const info = mm.models[col];
      if (only && only !== col && only !== info.code) continue;
      await processModel(browser, taskId, col, info, port++, outDir, baseUrl, staticBuild);
    }
  } finally {
    await browser.close();
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
