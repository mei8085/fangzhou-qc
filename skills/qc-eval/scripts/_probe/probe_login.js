#!/usr/bin/env node
// Inspect the platform login page to discover input names / submit selector.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

async function main() {
  const url = 'https://sd8c3fetlp0rb5mhmacf0.apigateway-cn-shanghai.volceapi.com/login.html';
  const outDir = 'D:/fz/fangzhou/fangzhou/tasks/_probe_platform';
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(2000);

  await page.screenshot({ path: path.join(outDir, 'login.png'), fullPage: true });
  fs.writeFileSync(path.join(outDir, 'login.html'), await page.content());

  const inputs = await page.$$eval('input', els => els.map(e => ({
    type: e.type, name: e.name, id: e.id, placeholder: e.placeholder, cls: e.className,
  })));
  console.log('inputs:', JSON.stringify(inputs, null, 2));

  const buttons = await page.$$eval('button, [type="submit"]', els => els.map(e => ({
    text: (e.innerText || '').trim(), type: e.type, cls: e.className, id: e.id,
  })));
  console.log('buttons:', JSON.stringify(buttons, null, 2));

  await browser.close();
}
main().catch(e => { console.error(e); process.exit(1); });
