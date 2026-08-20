#!/usr/bin/env node
// Probe the platform's "产物反馈" tab to discover its routing + DOM.
//
// usage: node probe_feedback.js <task_id> <view_user> <model_code>

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const HOST = 'https://sd8c3fetlp0rb5mhmacf0.apigateway-cn-shanghai.volceapi.com';
const STATE = path.join(__dirname, '..', '.platform_state.json');

async function main() {
  const [task_id, view_user, model_code] = process.argv.slice(2);
  if (!task_id || !view_user || !model_code) {
    console.error('usage: probe_feedback.js <task_id> <view_user> <model_code>');
    process.exit(2);
  }
  const outDir = 'D:/fz/fangzhou/fangzhou/tasks/_probe_platform';
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ storageState: STATE });
  const page = await ctx.newPage();

  page.on('response', resp => {
    const u = resp.url();
    if (u.includes('/api/') || resp.status() >= 400) {
      console.log('[resp]', resp.status(), u.slice(0, 250));
    }
  });

  const url = `${HOST}/task.html?view_user=${view_user}&task=${task_id}&model=${model_code}&page=trajectory`;
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(2000);

  // Click the "产物反馈" tab
  const tab = await page.evaluateHandle(() => {
    const cands = Array.from(document.querySelectorAll('*'));
    return cands.find(el => (el.innerText || '').trim() === '产物反馈' && el.children.length < 3) || null;
  });
  const el = tab.asElement();
  if (!el) {
    console.error('no 产物反馈 tab found');
    await browser.close();
    process.exit(3);
  }
  await el.click();
  await page.waitForTimeout(2500);
  await page.waitForLoadState('networkidle').catch(() => {});

  console.log('url after click:', page.url());
  fs.writeFileSync(path.join(outDir, `feedback_${task_id}_${model_code}.html`), await page.content());
  await page.screenshot({ path: path.join(outDir, `feedback_${task_id}_${model_code}.png`), fullPage: true });

  // Try to read the main feedback area text
  const text = await page.evaluate(() => {
    // Heuristic: pick the largest visible "content" panel; fall back to body
    const main = document.querySelector('.tab-content, .main-content, #content, .feedback-section, body');
    return main ? main.innerText : document.body.innerText;
  });
  console.log('--- visible text (truncated to 3000) ---');
  console.log(text.slice(0, 3000));

  await browser.close();
}
main().catch(e => { console.error(e); process.exit(1); });
