#!/usr/bin/env node
// For each model declared in tasks/<TASK_ID>/model_map.json, spin up the model's
// own vite dev server (in the entry directory given by model_map or a detected
// frontend directory) and capture real-app screenshots — never reuse the
// labeler's evidence.
//
// Captured states (per model):
//   01_initial      — main page after first paint
//   02_cart_added   — after clicking the first product's "+" / add button
//   03_cart_open    — after clicking the cart bar / icon
//
// All PNGs land in delivery/<TASK_ID>/screenshots/. Each model gets its own dev
// server on a unique port; the server is killed before the next model starts.
//
// Usage:
//   node screenshot_vue.js <TASK_ID> [--only <COL>]
//                          [--base-port 5173] [--keep-existing]
//                          [--if-annotator-web]
//
// Optional task config: tasks/<TASK_ID>/screenshot_vue.json. A model entry can
// define route + ordered steps ({name, goto, click, clicks, wait_for_text,
// wait_for_selector}) for
// task-specific evidence instead of the legacy cart-oriented fallback.

const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { reservePortBlock } = require('./lib/concurrency');

function sha1File(p) {
  return crypto.createHash('sha1').update(fs.readFileSync(p)).digest('hex');
}

const HERE = __dirname;
const SKILL_DIR = path.resolve(HERE, '..');
const REPO_ROOT = path.resolve(SKILL_DIR, '..', '..');

function parseArgs(argv) {
  const out = { id: null, only: null, basePort: null, keep: false, printSteps: false, ifAnnotatorWeb: false };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--only') out.only = argv[++i];
    else if (a === '--base-port') out.basePort = parseInt(argv[++i], 10);
    else if (a === '--keep-existing') out.keep = true;
    else if (a === '--print-steps') out.printSteps = true;
    else if (a === '--if-annotator-web') out.ifAnnotatorWeb = true;
    else out.id = a;
  }
  if (!out.id) {
    console.error('usage: screenshot_vue.js <TASK_ID> [--only COL] [--base-port 5173] [--keep-existing] [--print-steps] [--if-annotator-web]');
    process.exit(2);
  }
  return out;
}

function printManualSteps(taskId, map, basePort) {
  console.log(`# 手动复测 / 截图指引 — ${taskId}`);
  console.log('');
  console.log(`说明：自动截图脚本（${'`screenshot_vue.js`'}）跑不下来时按下面流程手工跑一遍，截图按命名落到`);
  console.log('       `delivery/' + taskId + '/screenshots/<COL>_NN_<state>.png`，之后跑 `compose.py` 合成 verify.png 即可。');
  console.log('');
  let port = basePort;
  for (const [col, info] of Object.entries(map.models)) {
    const tag = col.replace(/ /g, '_');
    const entry = info.entry === '.' ? '' : `/${info.entry}`;
    const entryDir = `tasks/${taskId}/extracted/${info.code}${entry}`;
    console.log(`## ${col}（${info.code}）`);
    console.log('');
    console.log('1. 起 dev server');
    console.log('   ```');
    console.log(`   cd ${entryDir}`);
    console.log(`   npm install --prefer-offline --no-audit --no-fund   # 仅首次（修复解压时丢失的 .bin/）`);
    console.log(`   npm run dev -- --port ${port} --strictPort`);
    console.log('   ```');
    console.log(`2. 浏览器打开 http://localhost:${port}/`);
    console.log(`3. 按状态截图（建议宽 420 高 820，DPR 2 模拟手机）：`);
    console.log(`   - 首屏直接截：保存为 \`delivery/${taskId}/screenshots/${tag}_01_initial.png\``);
    console.log(`   - 点第一个商品的 + 加入购物车后截：保存为 \`${tag}_02_cart_added.png\``);
    console.log(`   - 点购物车图标展开 popup 后截：保存为 \`${tag}_03_cart_open.png\``);
    console.log('4. Ctrl+C 关掉 dev server。');
    console.log('');
    port += 1;
  }
  console.log('## 收尾');
  console.log('');
  console.log('```');
  console.log(`python3 skills/qc-eval/scripts/compose.py ${taskId}`);
  console.log('```');
  console.log('');
  console.log('合成图（黑底、不缩放、横向并排）将出现在 `delivery/' + taskId + '/screenshots/<COL>_verify.png`。');
}

function sanitize(s) { return s.replace(/ /g, '_'); }

function stripAnsi(s) { return s.replace(/\x1b\[[0-9;]*m/g, ''); }

function pngSize(file) {
  try {
    const b = fs.readFileSync(file);
    if (b.length < 24) return null;
    if (b.slice(0, 8).compare(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) !== 0) return null;
    if (b.slice(12, 16).toString('ascii') !== 'IHDR') return null;
    return { width: b.readUInt32BE(16), height: b.readUInt32BE(20) };
  } catch {
    return null;
  }
}

function looksLikeWebAttachment(file) {
  const size = pngSize(file);
  if (!size) return false;
  const { width, height } = size;
  if (width < 900 || height < 600) return false;
  const ratio = width / Math.max(height, 1);
  return ratio >= 0.55 && ratio <= 3.2;
}

function modelHasWebAttachment(taskDir, platformCode) {
  const arkDir = path.join(taskDir, 'ark_g1');
  if (!fs.existsSync(arkDir)) return false;
  for (const runDir of fs.readdirSync(arkDir)) {
    if (!runDir.includes(`__${platformCode}`)) continue;
    const attachDir = path.join(arkDir, runDir, 'evaluation_attachments');
    if (!fs.existsSync(attachDir)) continue;
    for (const name of fs.readdirSync(attachDir)) {
      if (/\.png$/i.test(name) && looksLikeWebAttachment(path.join(attachDir, name))) {
        return true;
      }
    }
  }
  return false;
}

function resolveEntryDir(taskDir, info) {
  const explicit = info.entry || '.';
  const bases = [info.platform, info.code].filter(Boolean)
    .map((name) => path.join(taskDir, 'extracted', name));
  const cands = [];
  for (const base of bases) {
    cands.push(path.join(base, explicit));
    cands.push(path.join(base, explicit, 'web'));
    cands.push(base);
    cands.push(path.join(base, 'web'));
    cands.push(path.join(base, 'frontend'));
    cands.push(path.join(base, 'frontend', 'web'));
    cands.push(path.join(base, 'evalscope', 'web'));
    cands.push(path.join(base, explicit, 'evalscope', 'web'));
    // Some full-stack artifacts are symlinked to backend/ for Python tests; the
    // frontend lives next to backend in the original repo.
    cands.push(path.join(base, '..', 'frontend'));
    cands.push(path.join(base, '..', 'frontend', 'web'));
  }
  const seen = new Set();
  for (const c of cands) {
    const normalized = path.resolve(c);
    if (seen.has(normalized)) continue;
    seen.add(normalized);
    if (fs.existsSync(path.join(normalized, 'package.json'))) return normalized;
  }
  return path.resolve(path.join(bases[0] || path.join(taskDir, 'extracted'), explicit));
}

async function waitForViteUrl(child, timeoutMs = 60000) {
  return new Promise((resolve, reject) => {
    let buf = '';
    const onData = (chunk) => {
      buf += chunk.toString();
      const clean = stripAnsi(buf);
      // vite prints "  ➜  Local:   http://localhost:5173/" or
      // "http://localhost:5173/yu-gi-oh/" when `base` is not "/".
      const m = clean.match(/Local:\s*(https?:\/\/\S+)/);
      if (m) {
        const url = m[1];
        child.stdout.off('data', onData);
        child.stderr.off('data', onErr);
        resolve(url);
      }
    };
    const onErr = (chunk) => { buf += chunk.toString(); };
    child.stdout.on('data', onData);
    child.stderr.on('data', onErr);
    const t = setTimeout(() => {
      child.stdout.off('data', onData);
      child.stderr.off('data', onErr);
      reject(new Error(`vite did not print Local: URL within ${timeoutMs}ms. last output:\n${buf.slice(-1000)}`));
    }, timeoutMs);
    child.on('exit', code => {
      clearTimeout(t);
      reject(new Error(`vite exited with code ${code}. last output:\n${buf.slice(-1000)}`));
    });
  });
}

function killTree(pid) {
  if (!pid) return;
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/F', '/T', '/PID', String(pid)], { stdio: 'ignore' });
  } else {
    try { process.kill(-pid); } catch {}
    try { process.kill(pid); } catch {}
  }
}

function packageRunner(entryDir) {
  if (fs.existsSync(path.join(entryDir, 'pnpm-lock.yaml'))) return { bin: 'pnpm', install: 'pnpm install --frozen-lockfile', run: 'pnpm run dev' };
  if (fs.existsSync(path.join(entryDir, 'yarn.lock'))) return { bin: 'yarn', install: 'yarn install --frozen-lockfile', run: 'yarn dev' };
  return { bin: 'npm', install: 'npm install --prefer-offline --no-audit --no-fund --loglevel=error', run: 'npm run dev' };
}

async function startStaticServer(publicDir, port) {
  const python = process.env.QC_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const child = spawn(python, [
    '-m', 'http.server', String(port),
    '--bind', '127.0.0.1',
    '--directory', publicDir,
  ], {
    cwd: publicDir,
    windowsHide: true,
    detached: process.platform !== 'win32',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  child.on('error', e => console.error('     static server spawn error:', e.message));
  const url = await waitForHttpUrl(child, port);
  return { child, url };
}

function isNextProject(entryDir) {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(entryDir, 'package.json'), 'utf8'));
    return Boolean((pkg.dependencies && pkg.dependencies.next) || (pkg.devDependencies && pkg.devDependencies.next));
  } catch {
    return false;
  }
}

function isViteProject(entryDir) {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(entryDir, 'package.json'), 'utf8'));
    return Boolean((pkg.dependencies && pkg.dependencies.vite) || (pkg.devDependencies && pkg.devDependencies.vite));
  } catch {
    return false;
  }
}

function hasViteDevScript(scripts) {
  // A project can depend on Vite while using `dev` for its backend watcher.
  // Only treat `dev` as a Vite server when the script actually invokes Vite.
  return /(?:^|\s)(?:npx\s+)?vite(?:\s|$)/.test(String((scripts || {}).dev || ''));
}

function readPackage(entryDir) {
  try {
    return JSON.parse(fs.readFileSync(path.join(entryDir, 'package.json'), 'utf8'));
  } catch {
    return {};
  }
}

function ensureProjectBin(entryDir) {
  // The tarball's node_modules ships dependency code but no .bin shims (Linux
  // symlinks were skipped during extraction on Windows). Run the package
  // manager once per entry dir to recreate the needed dev-server shim.
  const scripts = readPackage(entryDir).scripts || {};
  if (!isNextProject(entryDir) && !(isViteProject(entryDir) && hasViteDevScript(scripts))) return;
  const binName = isNextProject(entryDir) ? 'next' : 'vite';
  const shim = process.platform === 'win32'
    ? path.join(entryDir, 'node_modules', '.bin', `${binName}.cmd`)
    : path.join(entryDir, 'node_modules', '.bin', binName);
  if (fs.existsSync(shim)) return;
  const pm = packageRunner(entryDir);
  console.log(`     [bin] no ${binName} shim at ${shim} — running ${pm.install} (one-time)`);
  const r = spawnSync(pm.install, {
    cwd: entryDir, shell: true, stdio: 'inherit',
  });
  if (r.status !== 0) throw new Error(`${pm.install} failed in ${entryDir}`);
}

async function waitForHttpUrl(child, port, timeoutMs = 60000) {
  const target = `http://localhost:${port}/`;
  let buf = '';
  const onData = (chunk) => { buf += chunk.toString(); };
  child.stdout.on('data', onData);
  child.stderr.on('data', onData);
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const clean = stripAnsi(buf);
    const m = clean.match(/https?:\/\/(?:localhost|127\.0\.0\.1):\d+\/?/);
    if (m) {
      child.stdout.off('data', onData);
      child.stderr.off('data', onData);
      return m[0].endsWith('/') ? m[0] : `${m[0]}/`;
    }
    const ready = clean.match(/READY\s+\{[^\n]*"port"\s*:\s*(\d+)/);
    if (ready) {
      child.stdout.off('data', onData);
      child.stderr.off('data', onData);
      return `http://127.0.0.1:${ready[1]}/`;
    }
    try {
      const res = await fetch(target, { method: 'GET' });
      if (res.status < 500) {
        child.stdout.off('data', onData);
        child.stderr.off('data', onData);
        return target;
      }
    } catch {}
    if (child.exitCode !== null) {
      child.stdout.off('data', onData);
      child.stderr.off('data', onData);
      throw new Error(`server exited with code ${child.exitCode}. last output:\n${buf.slice(-1000)}`);
    }
    await new Promise(r => setTimeout(r, 500));
  }
  child.stdout.off('data', onData);
  child.stderr.off('data', onData);
  throw new Error(`server did not become reachable within ${timeoutMs}ms. last output:\n${buf.slice(-1000)}`);
}

async function startDevServer(entryDir, port) {
  ensureProjectBin(entryDir);
  // Need shell:true on Windows because npm is a .cmd shim — Node 20+ requires
  // shell:true to spawn it. The shell also handles `--` argument passthrough.
  const pm = packageRunner(entryDir);
  const pkg = readPackage(entryDir);
  const scripts = pkg.scripts || {};
  // Next project scripts in these tasks often hard-code --port 3210, so call
  // next directly to guarantee each model gets its own screenshot port.
  let cmd;
  if (isNextProject(entryDir)) {
    cmd = `npx next dev --port ${port}`;
  } else if (isViteProject(entryDir) && hasViteDevScript(scripts)) {
    cmd = `${pm.run} -- --port ${port} --strictPort`;
  } else {
    cmd = scripts.start ? `${pm.bin} start` : `${pm.bin} run dev`;
  }
  console.log(`     starting "${cmd}" in ${entryDir}`);
  const child = spawn(cmd, {
    cwd: entryDir,
    shell: true,
    windowsHide: true,
    detached: process.platform !== 'win32',
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PORT: String(port) },
  });
  child.on('error', e => console.error('     spawn error:', e.message));
  let url;
  try {
    url = isViteProject(entryDir) && hasViteDevScript(scripts)
      ? await waitForViteUrl(child)
      : await waitForHttpUrl(child, port);
  } catch (e) {
    killTree(child.pid);
    throw e;
  }
  return { child, url };
}

async function trySelectors(page, selectors, action = 'click') {
  for (const sel of selectors) {
    const el = await page.$(sel);
    if (el) {
      const visible = await el.isVisible().catch(() => false);
      if (!visible) continue;
      if (action === 'click') {
        try { await el.click({ timeout: 3000 }); return sel; } catch {}
      } else if (action === 'find') {
        return sel;
      }
    }
  }
  return null;
}

async function screenshotModel(browser, label, code, entryDir, outDir, port, keep) {
  const tag = sanitize(label);
  const initialPng = path.join(outDir, `${tag}_01_initial.png`);
  const cartAddPng = path.join(outDir, `${tag}_02_cart_added.png`);
  const cartOpenPng = path.join(outDir, `${tag}_03_cart_open.png`);

  if (keep && fs.existsSync(initialPng)) {
    console.log(`   [skip] ${label} (${code}): ${path.basename(initialPng)} exists`);
    return { skipped: true, initialPng, cartAddPng, cartOpenPng };
  }

  let dev;
  try {
    dev = await startDevServer(entryDir, port);
  } catch (e) {
    console.error(`   [err] ${label}: dev server failed — ${e.message}`);
    return { error: e.message };
  }
  const url = dev.url;
  console.log(`     vite up at ${url}`);

  const ctx = await browser.newContext({
    viewport: { width: 420, height: 820 }, // mobile-ish, points-of-sale tend to be mobile
    deviceScaleFactor: 2,
  });
  const page = await ctx.newPage();
  const errs = [];
  page.on('pageerror', e => errs.push(e.message));

  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    // Wait for the SPA to mount something other than the empty #app placeholder.
    await page.waitForFunction(
      () => document.body && document.body.innerText && document.body.innerText.length > 30,
      null, { timeout: 20000 }
    ).catch(() => {});
    const isCartLike = await page.evaluate(() => {
      const text = document.body?.innerText || '';
      return /购物车|加入购物车|商品|点餐|去结算|结算/.test(text);
    }).catch(() => false);
    if (!isCartLike) {
      await page.setViewportSize({ width: 1280, height: 900 });
      await page.waitForTimeout(500);
    }
    // Some full-stack frontends emit a transient API toast while their backend
    // is not running. Let it settle so the verification image shows the page,
    // not just a notification overlay.
    await page.waitForTimeout(4200);
    await page.screenshot({ path: initialPng, fullPage: true });
    console.log(`     ${path.basename(initialPng)}`);

    if (!isCartLike) {
      for (const stale of [cartAddPng, cartOpenPng]) {
        if (fs.existsSync(stale)) fs.unlinkSync(stale);
      }
      console.log(`     ${path.basename(cartAddPng)} skipped (non-cart app)`);
      console.log(`     ${path.basename(cartOpenPng)} skipped (non-cart app)`);
      return { initialPng, cartAddPng, cartOpenPng };
    }

    // 02 — try to click an "add to cart" / "+" control on the first product
    const addClicked = await trySelectors(page, [
      // explicit class hints
      '.add-btn:not([disabled])',
      '.btn-add:not([disabled])',
      '.add-to-cart',
      '.add',
      '.plus',
      '.icon-add',
      'button[class*="add" i]:not([disabled])',
      '[class*="add-cart" i]',
      // generic "+ button" within product cards
      '.product-item button',
      '.product-card button',
      '.goods-item button',
      '.item button',
      'button',
    ]);
    if (addClicked) {
      await page.waitForTimeout(1200); // let any animation play
      await page.screenshot({ path: cartAddPng, fullPage: true });
      // blank_guard 会拒收与前一帧 byte 一致的图，所以哪怕点了按钮也复核一下
      if (fs.existsSync(cartAddPng) && fs.existsSync(initialPng) &&
          sha1File(cartAddPng) === sha1File(initialPng)) {
        fs.unlinkSync(cartAddPng);
        console.log(`     ${path.basename(cartAddPng)} skipped (identical to initial after click ${addClicked})`);
      } else {
        console.log(`     ${path.basename(cartAddPng)} (clicked ${addClicked})`);
      }
    } else {
      // 选择器没匹配到就跳过——不再截一张跟 initial 一模一样的图凑数
      console.log(`     ${path.basename(cartAddPng)} skipped (no add button found)`);
    }

    // 03 — open the cart popup. Different models bind the toggle to different
    // elements (cart icon, icon wrap, or even the checkout button). We try
    // each candidate; after every click we assert a visible popup/dialog
    // appeared. If the click didn't open anything, click the same element
    // again to undo any partial toggle before moving on.
    const triggerSelectors = [
      '.cart-icon-wrap',    // 0F3TQ
      '.cart-icon-wrapper', // 915V3
      '.cart-icon',         // 5C94P
      '.cart-bar .cart-btn',// SI9GM (quirk: 去结算 button toggles)
      '.cart-btn',
      '.cart-bar > div:first-child',
    ];
    let opened = null;
    for (const sel of triggerSelectors) {
      const el = await page.$(sel);
      if (!el) continue;
      if (!(await el.isVisible().catch(() => false))) continue;
      await el.click({ timeout: 3000 }).catch(() => {});
      // Transitions (slide/fade) typically <= 400ms; wait long enough for the
      // panel to finish animating in before snapping a screenshot.
      await page.waitForTimeout(1500);
      const hasPopup = await page.evaluate(() => {
        const cands = document.querySelectorAll(
          '[class*="cart-detail" i], [class*="cart-panel" i], [class*="cart-popup" i], ' +
          '[class*="cart-mask" i], [class*="mask" i], [class*="drawer" i], ' +
          '[class*="popup" i], [class*="dialog" i]'
        );
        return Array.from(cands).some(p => {
          if (!p.offsetWidth || !p.offsetHeight) return false;
          const r = p.getBoundingClientRect();
          // Mask covers full screen; detail panel is usually 200+ wide.
          return r.width > 120 && r.height > 120;
        });
      }).catch(() => false);
      if (hasPopup) { opened = sel; break; }
      // Click didn't open a popup — undo any partial state before next try.
      await el.click({ timeout: 1000 }).catch(() => {});
      await page.waitForTimeout(300);
    }
    if (opened) {
      await page.screenshot({ path: cartOpenPng, fullPage: true });
      const prevPng = fs.existsSync(cartAddPng) ? cartAddPng : initialPng;
      if (fs.existsSync(cartOpenPng) && fs.existsSync(prevPng) &&
          sha1File(cartOpenPng) === sha1File(prevPng)) {
        fs.unlinkSync(cartOpenPng);
        console.log(`     ${path.basename(cartOpenPng)} skipped (identical to ${path.basename(prevPng)} despite popup via ${opened})`);
      } else {
        console.log(`     ${path.basename(cartOpenPng)} (popup via ${opened})`);
      }
    } else {
      // 没弹出就跳过——不再截一张假装成功的图
      console.log(`     ${path.basename(cartOpenPng)} skipped (no popup opened — no matching trigger)`);
    }

    if (errs.length) console.log(`     pageerrors: ${errs.length} (first: ${errs[0].slice(0, 200)})`);
  } catch (e) {
    console.error(`   [err] ${label}: ${e.message}`);
  } finally {
    await ctx.close();
    killTree(dev.child.pid);
    // give Windows a moment to release the port
    await new Promise(r => setTimeout(r, 800));
  }
  return { initialPng, cartAddPng, cartOpenPng };
}

async function screenshotConfiguredModel(browser, label, code, entryDir, outDir, port, keep, config) {
  const tag = sanitize(label);
  const steps = Array.isArray(config.steps) ? config.steps : [];
  if (!steps.length) throw new Error(`screenshot_vue config for ${label} has no steps`);
  const firstPng = path.join(outDir, `${tag}_01_${sanitize(steps[0].name || 'initial')}.png`);
  if (keep && fs.existsSync(firstPng)) {
    console.log(`   [skip] ${label} (${code}): ${path.basename(firstPng)} exists`);
    return { skipped: true };
  }
  for (const name of fs.readdirSync(outDir)) {
    if (name.startsWith(`${tag}_`) && name.endsWith('.png')) fs.unlinkSync(path.join(outDir, name));
  }

  let dev;
  try {
    if (config.server_url) {
      dev = { child: null, url: String(config.server_url) };
      console.log(`     using existing app server at ${dev.url}`);
    } else {
      const publicDir = config.static_public_dir
        ? path.resolve(entryDir, config.static_public_dir)
        : null;
      if (publicDir) {
        if (!fs.existsSync(path.join(publicDir, 'index.html'))) {
          throw new Error(`static public directory has no index.html: ${publicDir}`);
        }
        console.log(`     serving static frontend from ${publicDir}`);
        dev = await startStaticServer(publicDir, port);
      } else {
        dev = await startDevServer(entryDir, port);
      }
    }
  } catch (e) {
    console.error(`   [err] ${label}: dev server failed — ${e.message}`);
    return { error: e.message };
  }
  console.log(`     vite up at ${dev.url}`);
  const viewport = config.viewport || { width: 1440, height: 1000 };
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: config.device_scale_factor || 1 });
  const page = await ctx.newPage();
  const errs = [];
  page.on('pageerror', e => errs.push(e.message));
  let currentRoute = config.route || '';
  let captureIndex = 0;
  const minBodyTextLength = Number.isFinite(config.min_body_text_length)
    ? config.min_body_text_length
    : 30;

  try {
    for (let index = 0; index < steps.length; index++) {
      const step = steps[index] || {};
      if (index === 0 || Object.prototype.hasOwnProperty.call(step, 'goto')) {
        currentRoute = Object.prototype.hasOwnProperty.call(step, 'goto') ? step.goto : currentRoute;
        const targetUrl = new URL(currentRoute || '', dev.url).toString();
        if (page.url() === targetUrl) {
          await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
        } else {
        await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
      }
      await page.waitForFunction(
        (minLength) => document.body && document.body.innerText && document.body.innerText.length > minLength,
        minBodyTextLength, { timeout: 20000 }
      );
      }
      if (step.set_input_files) {
        const upload = typeof step.set_input_files === 'string'
          ? { path: step.set_input_files }
          : step.set_input_files;
        const uploadPath = path.resolve(entryDir, upload.path || '');
        const entryRoot = `${path.resolve(entryDir)}${path.sep}`;
        if (!uploadPath.startsWith(entryRoot) || !fs.existsSync(uploadPath)) {
          throw new Error(`invalid upload path: ${upload.path || ''}`);
        }
        const input = page.locator(upload.selector || 'input[type="file"]').first();
        await input.setInputFiles(uploadPath);
        await page.waitForTimeout(step.action_delay_ms || 700);
      }
      if (Array.isArray(step.fill)) {
        for (const field of step.fill) {
          const locator = page.locator(field.selector).first();
          await locator.waitFor({ state: 'visible', timeout: 10000 });
          await locator.fill(String(field.value || ''));
        }
        await page.waitForTimeout(step.action_delay_ms || 300);
      }
      const selectors = [];
      if (step.click) selectors.push(step.click);
      if (Array.isArray(step.clicks)) selectors.push(...step.clicks);
      for (const selector of selectors) {
        const locator = page.locator(selector).first();
        await locator.waitFor({ state: 'visible', timeout: 10000 });
        await locator.click({ timeout: 10000 });
        await page.waitForTimeout(step.action_delay_ms || 700);
      }
      if (step.select_option) {
        const selection = step.select_option;
        const locator = page.locator(selection.selector).first();
        await locator.waitFor({ state: 'visible', timeout: 10000 });
        await locator.selectOption(selection.value);
        await page.waitForTimeout(step.action_delay_ms || 700);
      }
      if (step.wait_for_text) {
        await page.getByText(step.wait_for_text, { exact: false }).first().waitFor({ state: 'visible', timeout: 10000 });
      }
      if (step.wait_for_selector) {
        await page.locator(step.wait_for_selector).first().waitFor({ state: 'visible', timeout: 10000 });
      }
      await page.waitForTimeout(step.delay_ms || 1000);
      if (step.capture === false) continue;
      captureIndex += 1;
      const name = sanitize(step.name || `step_${index + 1}`);
      const png = path.join(outDir, `${tag}_${String(captureIndex).padStart(2, '0')}_${name}.png`);
      await page.screenshot({ path: png, fullPage: step.full_page !== false });
      console.log(`     ${path.basename(png)}`);
    }
    if (errs.length) console.log(`     pageerrors: ${errs.length} (first: ${errs[0].slice(0, 200)})`);
  } catch (e) {
    console.error(`   [err] ${label}: ${e.message}`);
    return { error: e.message };
  } finally {
    await ctx.close();
    if (dev && dev.child) killTree(dev.child.pid);
    await new Promise(r => setTimeout(r, 800));
  }
  return { firstPng };
}

async function main() {
  const args = parseArgs(process.argv);
  const taskDir = path.join(REPO_ROOT, 'tasks', args.id);
  const mapPath = path.join(taskDir, 'model_map.json');
  if (!fs.existsSync(mapPath)) {
    console.error(`no ${mapPath}`);
    process.exit(2);
  }
  const map = JSON.parse(fs.readFileSync(mapPath, 'utf8'));
  const screenshotConfigPath = path.join(taskDir, 'screenshot_vue.json');
  const screenshotConfig = fs.existsSync(screenshotConfigPath)
    ? JSON.parse(fs.readFileSync(screenshotConfigPath, 'utf8'))
    : {};
  const count = Math.max(1, Object.keys(map.models || {}).length);
  const lease = await reservePortBlock(args.id, 'screenshot-vue', count, args.basePort);
  console.log(`==> reserved local ports ${lease.base}-${lease.base + count - 1} for task ${args.id}`);
  try {
    if (args.printSteps) {
      printManualSteps(args.id, map, lease.base);
      return;
    }
    const outDir = path.join(REPO_ROOT, 'delivery', args.id, 'screenshots');
    fs.mkdirSync(outDir, { recursive: true });

    const browser = await chromium.launch({ headless: true });
    try {
      let port = lease.base;
      for (const [col, info] of Object.entries(map.models)) {
        if (args.only && col !== args.only) continue;
        if (info.missing) {
          console.log(`==> ${col} (${info.code || col}) skipped (not submitted)`);
          continue;
        }
        if (args.ifAnnotatorWeb && !modelHasWebAttachment(taskDir, info.platform || info.code)) {
          console.log(`==> ${col} (${info.code})  skipped (no web-like annotator attachment)`);
          continue;
        }
        const entryDir = resolveEntryDir(taskDir, info);
        console.log(`==> ${col} (${info.code})  entry=${path.relative(path.join(taskDir, 'extracted', info.code), entryDir) || '.'}`);
        const modelConfig = (screenshotConfig.models || {})[col];
        const configuredServer = modelConfig && (modelConfig.server_url || modelConfig.static_public_dir);
        if (!fs.existsSync(path.join(entryDir, 'package.json')) && !configuredServer) {
          console.error(`   [skip] no package.json at ${entryDir}`);
          continue;
        }
        if (modelConfig) {
          await screenshotConfiguredModel(browser, col, info.code, entryDir, outDir, port, args.keep, modelConfig);
        } else {
          await screenshotModel(browser, col, info.code, entryDir, outDir, port, args.keep);
        }
        port += 1;
      }
    } finally {
      await browser.close();
    }
  } finally {
    lease.release();
  }
}
main().catch(e => { console.error(e); process.exit(1); });
