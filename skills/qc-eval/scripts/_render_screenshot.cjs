
const fs = require('fs');
const { chromium } = require('playwright');
(async () => {
  const items = JSON.parse(fs.readFileSync(process.argv[2], 'utf-8'));
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 760 } });
  const page = await ctx.newPage();
  for (const it of items) {
    try {
      const url = 'file:///' + it.html.replace(/\\/g, '/');
      await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
    } catch (e) { console.log('goto warn', it.html, e.message); }
    await page.waitForTimeout(2500);
    try {
      await page.screenshot({ path: it.png, fullPage: false });
      console.log('shot', it.png);
    } catch (e) { console.log('shot fail', it.png, e.message); }
  }
  await browser.close();
})().catch(e => { console.error(e); process.exit(2); });
