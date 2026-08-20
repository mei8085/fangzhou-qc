#!/usr/bin/env node
// Screenshot standalone single-file HTML SPA (eat-what lottery)
// Usage: node screenshot_spa_html.js <TASK_ID>
// Loads each extracted <CODE>/index.html via file:// in mobile-viewport Chromium.
// Captures three states per model:
//   01_initial   - landing page
//   02_rolling   - during slot machine animation right after clicking main CTA
//   03_result    - after animation ends (result revealed)

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const REPO_ROOT = path.resolve(HERE, '..', '..', '..');

const CTA_SELECTORS = [
  'text=就是它了',
  'text=一键决定',
  'text=开始抽签',
  'text=开始',
  'button.btn-main',
  '#btn-roll',
  'button:has-text("抽")',
];

async function clickMainCTA(page) {
  for (const sel of CTA_SELECTORS) {
    try {
      const el = await page.$(sel);
      if (el) {
        const visible = await el.isVisible();
        if (visible) {
          await el.click({ timeout: 2000 });
          return sel;
        }
      }
    } catch (_) {}
  }
  return null;
}

async function shootModel(browser, taskId, col, code) {
  const htmlPath = path.join(REPO_ROOT, 'tasks', taskId, 'extracted', code, 'index.html');
  if (!fs.existsSync(htmlPath)) {
    console.warn(`  [skip] ${col} (${code}) — no index.html`);
    return;
  }
  const outDir = path.join(REPO_ROOT, 'delivery', taskId, 'screenshots');
  fs.mkdirSync(outDir, { recursive: true });

  const safe = col.replace(/[^A-Za-z0-9._-]+/g, '_');
  const context = await browser.newContext({
    viewport: { width: 420, height: 900 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  });
  const page = await context.newPage();
  const fileUrl = 'file:///' + htmlPath.replace(/\\/g, '/');
  console.log(`  [${col}] ${fileUrl}`);
  try {
    await page.goto(fileUrl, { waitUntil: 'load' });
  } catch (e) {
    console.warn(`  [${col}] goto failed:`, e.message);
  }
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(outDir, `${safe}_01_initial.png`), fullPage: true });

  const clicked = await clickMainCTA(page);
  if (!clicked) {
    console.warn(`  [${col}] main CTA not found`);
  } else {
    console.log(`  [${col}] clicked ${clicked}`);
  }
  // Rolling snapshot — early moment of animation
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outDir, `${safe}_02_rolling.png`), fullPage: true });
  // Wait for animation to end
  await page.waitForTimeout(5000);
  await page.screenshot({ path: path.join(outDir, `${safe}_03_result.png`), fullPage: true });
  await context.close();
}

async function main() {
  const taskId = process.argv[2];
  if (!taskId) {
    console.error('usage: screenshot_spa_html.js <TASK_ID>');
    process.exit(2);
  }
  const mapPath = path.join(REPO_ROOT, 'tasks', taskId, 'model_map.json');
  if (!fs.existsSync(mapPath)) {
    console.error(`missing ${mapPath}`);
    process.exit(2);
  }
  const map = JSON.parse(fs.readFileSync(mapPath, 'utf8'));
  const browser = await chromium.launch();
  try {
    for (const [col, info] of Object.entries(map.models)) {
      await shootModel(browser, taskId, col, info.code);
    }
  } finally {
    await browser.close();
  }
  console.log('done');
}

main().catch((e) => { console.error(e); process.exit(1); });
