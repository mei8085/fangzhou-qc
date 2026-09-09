#!/usr/bin/env node
// Render original Markdown and retain source hashes alongside the screenshots.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { chromium } = require('playwright');
const { marked } = require('marked');
async function main() {
  const id = process.argv[2];
  if (!/^\d+$/.test(id || '')) throw new Error('Usage: screenshot_markdown.js TASK_ID');
  const root = path.resolve(__dirname, '../../..');
  const task = path.join(root, 'tasks', id);
  const config = JSON.parse(fs.readFileSync(path.join(task, 'screenshot_markdown.json'), 'utf8'));
  const output = path.join(root, 'delivery', id, 'screenshots');
  const renders = path.join(task, 'markdown_renders');
  fs.mkdirSync(renders, { recursive: true });
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const records = [];
  try {
    for (const item of config.documents) {
      const source = path.resolve(task, 'extracted', item.source);
      if (!source.startsWith(path.join(task, 'extracted') + path.sep) || !source.endsWith('.md')) throw new Error('Invalid source');
      if (!/^[\w.-]+_\d+_markdown$/.test(item.name)) throw new Error('Invalid screenshot name');
      const bytes = fs.readFileSync(source);
      const html = `<!doctype html><html lang="zh-CN"><meta charset="utf-8">
      <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
      <style>*{box-sizing:border-box}body{margin:0;padding:40px 48px;color:#24292f;background:white;font-family:"PingFang SC","Microsoft YaHei",sans-serif;font-size:17px;line-height:1.7}
      h1{font-size:29px}h2{font-size:24px;margin-top:30px;border-bottom:1px solid #ddd}h3{font-size:20px}
      table{border-collapse:collapse;width:100%;font-size:15px}th,td{border:1px solid #cbd0d5;padding:9px 12px;vertical-align:top;overflow-wrap:anywhere}th{background:#f3f4f5}
      pre{white-space:pre-wrap;background:#f6f8fa;padding:16px}code{font-family:Menlo,monospace;font-size:.88em;overflow-wrap:anywhere}
      blockquote{margin:16px 0;padding:0 18px;border-left:4px solid #d0d7de;color:#57606a}a{color:#0969da}img{max-width:100%}hr{border:0;border-top:1px solid #ddd}</style>
      <body><article>${marked.parse(bytes.toString('utf8'), { gfm: true })}</article></body></html>`;
      const htmlPath = path.join(renders, `${item.name}.html`);
      fs.writeFileSync(htmlPath, html);
      const page = await browser.newPage({ viewport: { width: 1200, height: 1400 }, deviceScaleFactor: 1 });
      await page.route('**/*', route => route.abort());
      await page.setContent(html, { waitUntil: 'load' });
      await page.evaluate(() => document.fonts.ready);
      const screenshot = path.join(output, `${item.name}.png`);
      const fullPage = config.full_page !== false;
      await page.screenshot({ path: screenshot, fullPage });
      records.push({ source: path.relative(root, source), sha256: crypto.createHash('sha256').update(bytes).digest('hex'), screenshot: path.relative(root, screenshot), html: path.relative(root, htmlPath), fullPage, viewport: page.viewportSize(), headings: await page.locator('h1,h2,h3').allTextContents() });
      console.log(`${item.name}: rendered ${records.at(-1).headings.length} headings`);
      await page.close();
    }
  } finally { await browser.close(); }
  fs.writeFileSync(path.join(renders, 'manifest.json'), JSON.stringify(records, null, 2));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
