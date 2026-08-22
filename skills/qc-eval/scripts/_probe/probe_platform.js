#!/usr/bin/env node
// Probe one task.html page to see its structure: tab labels, img src for the
// "comment screenshot" panel, whether auth is needed.
//
// Usage: node probe_platform.js <view_user> <task_id> <model_code>

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

async function main() {
  const [view_user, task_id, model_code] = process.argv.slice(2);
  if (!view_user || !task_id || !model_code) {
    console.error('usage: probe_platform.js <view_user> <task_id> <model_code>');
    process.exit(2);
  }
  const url = `https://sd8c3fetlp0rb5mhmacf0.apigateway-cn-shanghai.volceapi.com/task.html?view_user=${view_user}&task=${task_id}&model=${model_code}&page=trajectory`;
  console.log('url:', url);

  const outDir = path.join(path.resolve(__dirname, '..', '..', '..', '..'), 'tasks', '_probe_platform');
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  page.on('console', m => console.log('[page]', m.type(), m.text().slice(0, 200)));
  page.on('response', resp => {
    const u = resp.url();
    if (u.match(/\.(json|api)/i) || resp.status() >= 400) {
      console.log('[resp]', resp.status(), u.slice(0, 200));
    }
  });

  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(3000);

  await page.screenshot({ path: path.join(outDir, `${model_code}.png`), fullPage: true });
  fs.writeFileSync(path.join(outDir, `${model_code}.html`), await page.content());

  // Collect all img srcs + their proximity to "comment" / "效果" text
  const imgs = await page.$$eval('img', els => els.map(e => ({
    src: e.getAttribute('src'),
    alt: e.alt,
    width: e.naturalWidth,
    height: e.naturalHeight,
  })));
  console.log('imgs:', imgs.length);
  for (const i of imgs.slice(0, 30)) console.log('  ', i.width, 'x', i.height, i.src);

  // Look for tabs (model switcher)
  const tabs = await page.$$eval('[role="tab"], .tab, .ant-tabs-tab, .arco-tabs-tab', els =>
    els.map(e => ({ text: (e.innerText || '').trim(), cls: e.className })));
  console.log('tabs:', tabs.length);
  for (const t of tabs) console.log('  ', t.text);

  // Title
  console.log('title:', await page.title());

  await browser.close();
}

main().catch(e => { console.error(e); process.exit(1); });
