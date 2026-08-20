#!/usr/bin/env node
// Probe the attachment download portal so we can write a stable downloader.
// Usage: node probe_portal.js <portal_url_file> <search_term>

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

async function main() {
  const portalFile = process.argv[2];
  const searchTerm = process.argv[3] || 'task-F1T7UJ';
  if (!portalFile) {
    console.error('usage: probe_portal.js <portal_url_file> [search_term]');
    process.exit(2);
  }
  const meta = JSON.parse(fs.readFileSync(portalFile, 'utf8'));
  const url = meta.portal_url;
  console.log('portal url len:', url.length);

  const outDir = path.join(path.dirname(portalFile), '_probe');
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ acceptDownloads: true });
  const page = await ctx.newPage();

  page.on('console', msg => console.log('[page]', msg.type(), msg.text()));
  page.on('request', req => {
    if (req.url().match(/\.(zip|tar|gz|json|xml)|api|search/i)) {
      console.log('[req]', req.method(), req.url().slice(0, 200));
    }
  });

  console.log('==> goto');
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(2000);

  await page.screenshot({ path: path.join(outDir, '01_landing.png'), fullPage: true });
  fs.writeFileSync(path.join(outDir, '01_landing.html'), await page.content());
  console.log('saved landing screenshot + html');

  // Try to find a search input
  const inputs = await page.$$('input');
  console.log('inputs found:', inputs.length);
  for (let i = 0; i < inputs.length; i++) {
    const attrs = await inputs[i].evaluate(el => ({
      type: el.type, placeholder: el.placeholder, name: el.name, id: el.id, cls: el.className,
    }));
    console.log(`  input[${i}]:`, attrs);
  }

  // Type the search term in the first non-hidden input
  let target = null;
  for (const inp of inputs) {
    const visible = await inp.isVisible().catch(() => false);
    const t = await inp.evaluate(el => el.type).catch(() => '');
    if (visible && t !== 'hidden') { target = inp; break; }
  }
  if (target) {
    console.log('==> typing search term:', searchTerm);
    await target.click();
    await target.fill(searchTerm);
    await page.keyboard.press('Enter');
    await page.waitForTimeout(3000);
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.screenshot({ path: path.join(outDir, '02_search.png'), fullPage: true });
    fs.writeFileSync(path.join(outDir, '02_search.html'), await page.content());
    console.log('saved search results screenshot + html');
  } else {
    console.log('no visible input found');
  }

  await browser.close();
}

main().catch(e => { console.error(e); process.exit(1); });
