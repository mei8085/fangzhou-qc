#!/usr/bin/env node
// Probe the 反馈质检 tab on the platform to discover the 3 input fields.
// Usage: node probe_qc_tab.js <task_id> <view_user> <model_code>

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const HOST = 'https://sd8c3fetlp0rb5mhmacf0.apigateway-cn-shanghai.volceapi.com';
const STATE = path.join(__dirname, '..', '.platform_state.json');

async function main() {
  const [task_id, view_user, model_code] = process.argv.slice(2);
  if (!task_id || !view_user || !model_code) {
    console.error('usage: probe_qc_tab.js <task_id> <view_user> <model_code>');
    process.exit(2);
  }
  const outDir = path.join(path.resolve(__dirname, '..', '..', '..', '..'), 'tasks', '_probe_platform');
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ storageState: STATE });
  const page = await ctx.newPage();

  page.on('response', resp => {
    const u = resp.url();
    if (u.includes('/api/quality') || u.includes('/api/qc') || u.includes('/api/inspection') ||
        u.includes('/api/feedback') || u.includes('/api/review')) {
      console.log('[resp]', resp.status(), u.slice(0, 250));
    }
  });

  const url = `${HOST}/task.html?view_user=${view_user}&task=${task_id}&model=${model_code}&page=trajectory`;
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(2000);

  // Click 反馈质检
  const tab = await page.evaluateHandle(() => {
    const cands = Array.from(document.querySelectorAll('*'));
    return cands.find(el => (el.innerText || '').trim() === '反馈质检' && el.children.length < 3) || null;
  });
  const el = tab.asElement();
  if (!el) { console.error('no 反馈质检 tab'); await browser.close(); process.exit(3); }
  await el.click();
  await page.waitForTimeout(3000);

  fs.writeFileSync(path.join(outDir, `qc_tab_${task_id}_${model_code}.html`), await page.content());
  await page.screenshot({ path: path.join(outDir, `qc_tab_${task_id}_${model_code}.png`), fullPage: true });

  // Enumerate ALL form elements + labels + select options
  const fields = await page.evaluate(() => {
    const all = Array.from(document.querySelectorAll('input, textarea, select, [contenteditable="true"]'));
    return all.map(e => {
      const out = {
        tag: e.tagName.toLowerCase(),
        type: e.type || null,
        name: e.name || null,
        id: e.id || null,
        placeholder: e.placeholder || null,
        cls: e.className || null,
        value: (e.value || '').slice(0, 200),
        visible: !!(e.offsetWidth || e.offsetHeight),
      };
      // Try to find a nearby label
      let parent = e.parentElement, label = null;
      for (let i = 0; i < 6 && parent; i++) {
        const lbl = parent.querySelector?.('label, .label, .form-label, .title, .field-label, .question, .form-item-label');
        if (lbl && lbl.innerText) { label = lbl.innerText.trim().slice(0, 200); break; }
        parent = parent.parentElement;
      }
      out.label = label;
      // For select, collect option text
      if (e.tagName.toLowerCase() === 'select') {
        out.options = Array.from(e.querySelectorAll('option')).map(o => o.innerText.trim());
      }
      return out;
    }).filter(f => f.visible);
  });
  console.log('VISIBLE form fields:', JSON.stringify(fields, null, 2));

  // Also enumerate any "radio-like" arco-design custom radios
  const radioGroups = await page.evaluate(() => {
    const groups = Array.from(document.querySelectorAll(
      '.arco-radio-group, [role="radiogroup"], .form-question, .qc-question, .question-item'
    ));
    return groups.slice(0, 20).map(g => ({
      cls: g.className,
      text: (g.innerText || '').slice(0, 500),
    }));
  });
  console.log('possible radio groups:', JSON.stringify(radioGroups, null, 2));

  await browser.close();
}
main().catch(e => { console.error(e); process.exit(1); });
