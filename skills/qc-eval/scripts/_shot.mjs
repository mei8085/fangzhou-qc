import { chromium } from 'playwright';

const [,, url, out, mode] = process.argv;
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
p.on('pageerror', e => console.error('pageerror:', e.message));
p.on('console', m => { if (m.type() === 'error') console.error('console err:', m.text().slice(0, 200)); });
try {
  await p.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
} catch (e) {
  console.error('goto:', e.message);
}
await p.waitForTimeout(3000);
if (mode === 'trades') {
  const clicked = await p.evaluate(() => {
    const els = [...document.querySelectorAll('a,button,li,div,span')];
    const cand = els.find(e => /^(明细|交易明细|明細|Trades|详情)/.test((e.textContent || '').trim()));
    if (cand) { cand.click(); return cand.textContent.trim(); }
    return null;
  });
  if (clicked) console.error('clicked:', clicked);
  await p.waitForTimeout(1500);
}
if (mode === 'analytics' || mode === 'deep') {
  const clicked = await p.evaluate(() => {
    const els = [...document.querySelectorAll('a,button,li,div,span')];
    const cand = els.find(e => /深度分析|分析|指标|Analytics/.test((e.textContent || '').trim())) ||
                 els.find(e => (e.getAttribute('href') || '').includes('analytics'));
    if (cand) { cand.click(); return cand.textContent.trim().slice(0, 40); }
    return null;
  });
  if (clicked) console.error('clicked:', clicked);
  await p.waitForTimeout(2000);
}
await p.screenshot({ path: out, fullPage: true });
await b.close();
console.log('shot:', out);
