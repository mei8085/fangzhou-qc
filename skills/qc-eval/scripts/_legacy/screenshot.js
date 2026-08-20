#!/usr/bin/env node
/**
 * Take Playwright screenshots of every model under tasks/<TASK_ID>/extracted/.
 *
 * Usage:
 *   node screenshot.js <task_dir>
 *
 * Output: tasks/<TASK_ID>/screenshots/<model>/0[1-8]_*.png
 *
 * The script is generic for any 2048-style web UI in the eval set. It tries
 * common selectors for the undo button and size selector; if a model uses
 * different markup, add it to SELECTOR_CANDIDATES.
 */
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const UNDO_CANDIDATES   = ['.undo-button', '[data-action="undo"]', 'button.undo', '#undo-btn'];
const SIZE_CANDIDATES   = ['.size-selector', '.size-select', 'select[name="size"]', '#size-select'];

function usage() {
  console.error('usage: node screenshot.js <task_dir>');
  process.exit(2);
}

const TASK_DIR = process.argv[2];
if (!TASK_DIR) usage();
const absTask = path.resolve(TASK_DIR);
const extractedRoot = path.join(absTask, 'extracted');
if (!fs.existsSync(extractedRoot)) {
  console.error(`no extracted/ under ${absTask}`);
  process.exit(2);
}

async function firstMatching(page, candidates) {
  for (const sel of candidates) {
    if (await page.$(sel)) return sel;
  }
  return null;
}

async function shoot(modelDir) {
  const indexPath = path.join(extractedRoot, modelDir, 'index.html');
  if (!fs.existsSync(indexPath)) {
    console.log(`  skip ${modelDir}: no index.html`);
    return;
  }
  const outDir = path.join(absTask, 'screenshots', modelDir);
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1024, height: 900 } });
  const page = await ctx.newPage();
  page.on('pageerror', e => console.log(`    [pageerror] ${e.message}`));

  await page.goto('file://' + indexPath);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(700);   // give the game JS a beat to render initial tiles

  const undoSel = await firstMatching(page, UNDO_CANDIDATES);
  const sizeSel = await firstMatching(page, SIZE_CANDIDATES);

  const tag = async (name) => {
    const p = path.join(outDir, `${name}.png`);
    await page.screenshot({ path: p, fullPage: false });
    console.log(`  ✓ ${modelDir}/${name}.png`);
  };

  await tag('01_default_4x4');

  await page.evaluate(() => document.body.focus && document.body.focus());

  for (const k of ['ArrowUp', 'ArrowLeft', 'ArrowDown', 'ArrowRight']) {
    await page.keyboard.press(k);
    await page.waitForTimeout(120);
  }
  await tag('02_after_4_moves');

  if (undoSel) {
    await page.click(undoSel).catch(() => {});
    await page.waitForTimeout(200);
    await tag('03_after_one_undo');

    for (let i = 0; i < 3; i++) {
      await page.click(undoSel).catch(() => {});
      await page.waitForTimeout(150);
    }
    await tag('04_undo_exhausted_disabled');
  }

  await page.keyboard.press('ArrowUp');
  await page.waitForTimeout(120);
  await page.keyboard.press('ArrowRight');
  await page.waitForTimeout(120);
  await page.keyboard.down('Control');
  await page.keyboard.press('KeyZ');
  await page.keyboard.up('Control');
  await page.waitForTimeout(200);
  await tag('05_ctrl_z');

  if (sizeSel) {
    for (const [n, label] of [['3', '06_size_3x3'], ['5', '07_size_5x5'], ['4', '08_size_4x4_again']]) {
      try {
        await page.selectOption(sizeSel, n);
        await page.waitForTimeout(400);
        await tag(label);
      } catch (e) {
        console.log(`  ! size ${n} failed: ${e.message}`);
      }
    }
  } else {
    console.log(`  ! no size selector found on ${modelDir}`);
  }

  await browser.close();
}

(async () => {
  const models = fs.readdirSync(extractedRoot).filter(name => {
    return fs.statSync(path.join(extractedRoot, name)).isDirectory();
  });
  for (const m of models) {
    console.log(`\n=== ${m} ===`);
    try { await shoot(m); }
    catch (e) { console.log(`  ✗ ${e.message}`); }
  }
})();
