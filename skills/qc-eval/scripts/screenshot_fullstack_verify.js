#!/usr/bin/env node
// Route-driven Playwright screenshotter for the fullstack verify pipeline.
//
// Reads tasks/<TASK_ID>/verify_routes.json:
//
//   {
//     "login": {
//       "path": "/#/login",
//       "steps": [
//         {"fill": "input[placeholder='用户名']", "value": "admin"},
//         {"fill": "input[type='password']", "value": "admin123"},
//         {"click": "button[type='submit']"}
//       ],
//       "wait_for": "text=控制台"
//     },
//     "routes": [
//       {"name": "01_dashboard", "path": "/#/dashboard", "wait_for": "canvas"},
//       {"name": "02_report", "path": "/#/report",     "wait_ms": 1500}
//     ]
//   }
//
// Output: <out-dir>/<CODE>_verify_NN_<name>.png
// A failed route saves <CODE>_verify_NN_<name>_error.png with page as-is.
//
// Usage:
//   node screenshot_fullstack_verify.js --task T841IB --code 5SIDV \
//        --vue-url http://localhost:5173 --api-port 8000 \
//        --routes tasks/T841IB/verify_routes.json --out-dir delivery/T841IB/screenshots

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) out[a.slice(2)] = argv[++i];
  }
  for (const k of ['task', 'code', 'vue-url', 'routes', 'out-dir']) {
    if (!out[k]) { console.error(`missing --${k}`); process.exit(2); }
  }
  return out;
}

async function runStep(page, step) {
  if (step.fill) {
    await page.locator(step.fill).first().fill(step.value ?? '');
    return;
  }
  if (step.click) {
    await page.locator(step.click).first().click();
    return;
  }
  if (step.press) {
    await page.keyboard.press(step.press);
    return;
  }
  if (step.wait_ms) {
    await page.waitForTimeout(step.wait_ms);
    return;
  }
  throw new Error(`unknown step: ${JSON.stringify(step)}`);
}

async function waitFor(page, spec, opts = {}) {
  const timeout = opts.timeout ?? 8000;
  if (typeof spec === 'string') {
    if (spec.startsWith('text=')) {
      await page.getByText(spec.slice(5)).first().waitFor({ timeout });
    } else {
      await page.locator(spec).first().waitFor({ timeout });
    }
  }
}

async function main() {
  const args = parseArgs(process.argv);
  const routesCfg = JSON.parse(fs.readFileSync(args.routes, 'utf-8'));
  const outDir = args['out-dir'];
  fs.mkdirSync(outDir, { recursive: true });
  const codeTag = args.code;

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();
  const consoleLog = [];
  page.on('console', (m) => consoleLog.push(`[${m.type()}] ${m.text()}`));
  page.on('pageerror', (e) => consoleLog.push(`[pageerror] ${e.message}`));

  const base = args['vue-url'].replace(/\/$/, '');
  const results = [];

  // login (optional)
  if (routesCfg.login) {
    try {
      await page.goto(base + (routesCfg.login.path ?? '/'), { waitUntil: 'domcontentloaded' });
      for (const s of (routesCfg.login.steps ?? [])) {
        await runStep(page, s);
      }
      if (routesCfg.login.wait_for) {
        await waitFor(page, routesCfg.login.wait_for);
      }
      results.push({ step: 'login', ok: true });
    } catch (e) {
      results.push({ step: 'login', ok: false, err: String(e) });
      const p = path.join(outDir, `${codeTag}_verify_00_login_error.png`);
      await page.screenshot({ path: p, fullPage: false });
    }
  }

  // routes
  for (const r of routesCfg.routes ?? []) {
    const target = base + r.path;
    const outPath = path.join(outDir, `${codeTag}_verify_${r.name}.png`);
    try {
      await page.goto(target, { waitUntil: 'domcontentloaded' });
      if (r.wait_for) await waitFor(page, r.wait_for);
      if (r.wait_ms) await page.waitForTimeout(r.wait_ms);
      await page.screenshot({ path: outPath, fullPage: false });
      results.push({ route: r.name, ok: true, path: outPath });
    } catch (e) {
      const errPath = path.join(outDir, `${codeTag}_verify_${r.name}_error.png`);
      try { await page.screenshot({ path: errPath, fullPage: false }); } catch (_) {}
      results.push({ route: r.name, ok: false, err: String(e), path: errPath });
    }
  }

  // per-code console log
  const logPath = path.join(outDir, `..`, 'logs', `${codeTag}_console.log`);
  fs.mkdirSync(path.dirname(logPath), { recursive: true });
  fs.writeFileSync(logPath, consoleLog.join('\n'), 'utf-8');

  await context.close();
  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log(JSON.stringify({ code: codeTag, results }, null, 2));
  process.exit(failed.length === 0 ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
