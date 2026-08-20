// One-off: screenshot each model's SCIAgent_UI.html via file:// (Task 1 evidence)
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const REPO = 'D:/fz/fangzhou/fangzhou';
const TASK = 'J62S2J';
const OUT = path.join(REPO, 'delivery', TASK, 'screenshots');
fs.mkdirSync(OUT, { recursive: true });

const MAP = JSON.parse(fs.readFileSync(path.join(REPO, 'tasks', TASK, 'model_map.json'), 'utf-8'));

(async () => {
  const browser = await chromium.launch();
  for (const [col, info] of Object.entries(MAP.models)) {
    const code = info.code;
    const safe = col.replace(/[^A-Za-z0-9._-]+/g, '_');
    const htmlPath = path.join(REPO, 'tasks', TASK, 'extracted', code, 'SCIAgent_UI.html');
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    try {
      const fileUrl = 'file:///' + htmlPath.split(path.sep).join('/');
      await page.goto(fileUrl, { waitUntil: 'load', timeout: 20000 });
      await page.waitForTimeout(1500);
      const uiOut = path.join(OUT, `${safe}_01_ui.png`);
      await page.screenshot({ path: uiOut, fullPage: false });
      console.log(`[${col}] UI ${path.basename(uiOut)}`);
    } catch (e) {
      console.error(`[${col}] UI shot error: ${e.message}`);
    }
    await ctx.close();
  }
  await browser.close();
})();
