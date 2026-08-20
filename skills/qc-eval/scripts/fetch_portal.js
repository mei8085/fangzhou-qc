#!/usr/bin/env node
// Download attachments for a list of task IDs from the volces object-storage
// share portal. The portal renders an arco-design table; we type the task ID
// into the prefix search box, then click the "下载" button on each matching row
// and capture the download stream.
//
// Usage:
//   node fetch_portal.js --portal <portal_json> --out <tasks_dir> <TASK_ID> [<TASK_ID> ...]
//   node fetch_portal.js --out <tasks_dir> <TASK_ID> [<TASK_ID> ...]  // defaults to 30? portal
//
// portal_json must be a JSON file like { "portal_url": "https://..." }.
// Each task's files are saved into <tasks_dir>/<TASK_ID>/.

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const DEFAULT_30_PORTAL_URL =
  'https://document-share.tos-cn-beijing.volces.com/v2/index.html?token=aHR0cHM6Ly9hcmstY3Jvd2R0ZXN0LWNvZGluZy1ldmFsNy0xNC0xMDMtMTMyLTE4My0yMDI2MDYyMS50b3MtY24tc2hhbmdoYWkudm9sY2VzLmNvbT9YLVRvcy1BbGdvcml0aG09VE9TNC1ITUFDLVNIQTI1NiZYLVRvcy1DcmVkZW50aWFsPUFLTFRabVpsTkdaak5ETXdaV1ZsTkRBek5EaGtaamN6TldVNU1tRXlPRE0yTlRnJTJGMjAyNjA3MTglMkZ0b3MtY24tc2hhbmdoYWkudm9sY2VzLmNvbSUyRnRvcyUyRnJlcXVlc3QmWC1Ub3MtRGF0ZT0yMDI2MDcxOFQxNjE0MjNaJlgtVG9zLUV4cGlyZXM9ODY0MDAwJlgtVG9zLVBvbGljeT1leUpqYjI1a2FYUnBiMjV6SWpwYld5SnpkR0Z5ZEhNdGQybDBhQ0lzSWlSclpYa2lMQ0psZG1Gc2RXRjBhVzl1TFhSaGMyc3ROeTF3YUdGelpUTXdMV0ZzYkMxa1lYUmhMekl3TWpZd05qSXhMVEV5TWpVeE5pOTBZWE5yTFdGeVkyaHBkbVZ6THlKZExGc2laWEVpTENJa1luVmphMlYwSWl3aVlYSnJMV055YjNka2RHVnpkQzFqYjJScGJtY3RaWFpoYkRjdE1UUXRNVEF6TFRFek1pMHhPRE10TWpBeU5qQTJNakVpWFYxOSZYLVRvcy1TaWduYXR1cmU9NzIzZWZlOWMxMGQ5Njg2MDhlMDFjZDNmNTg2MTk5YjdmY2QxMTUxZDU4YTZhNDUwYzY3ZWJmY2U0YzFiZDc5Zg==';

function parseArgs(argv) {
  const out = { portal: null, outDir: null, ids: [], keepExisting: false, headless: true };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--portal') out.portal = argv[++i];
    else if (a === '--out') out.outDir = argv[++i];
    else if (a === '--keep-existing') out.keepExisting = true;
    else if (a === '--headed') out.headless = false;
    else out.ids.push(a);
  }
  if (!out.outDir || out.ids.length === 0) {
    console.error('usage: fetch_portal.js [--portal <portal.json>] --out <tasks_dir> <TASK_ID> [...]');
    process.exit(2);
  }
  return out;
}

async function searchAndDownload(page, taskId, outDir, { keepExisting }) {
  console.log(`\n==> ${taskId}`);
  const targetDir = path.join(outDir, taskId);
  fs.mkdirSync(targetDir, { recursive: true });

  let rows = [];
  let prefix = '';
  // Recent batches may publish archives as source-<ID> rather than task-<ID>.
  for (const candidate of [`task-${taskId}`, `source-${taskId}`]) {
    const input = page.locator('input.arco-input').first();
    await input.click();
    await input.fill('');
    await input.fill(candidate);
    await page.keyboard.press('Enter');

    // Wait for rows to refresh. The portal renders a row per file.
    // Empty-result placeholder is "暂无数据"; result rows have data-cy="table-row-...".
    await page.waitForTimeout(1500);
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});

    rows = await page.$$('tr.arco-table-tr[data-cy^="table-row-"]');
    if (rows.length > 0) {
      prefix = candidate;
      break;
    }
  }
  if (rows.length === 0) {
    console.log(`   (!) no files found for task-${taskId} or source-${taskId}`);
    return { ok: false, files: [] };
  }
  console.log(`   ${rows.length} file(s) listed (${prefix})`);

  const downloaded = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    // Filename is in the first cell's text.
    const nameCell = await row.$('td.arco-table-td');
    const filename = (await nameCell.innerText()).trim();
    const dest = path.join(targetDir, filename);

    if (keepExisting && fs.existsSync(dest) && fs.statSync(dest).size > 0) {
      console.log(`   [skip] ${filename} (exists)`);
      downloaded.push({ filename, path: dest, skipped: true });
      continue;
    }

    const btn = await row.$('button[data-testid="operation-menu-btn-id"]');
    if (!btn) {
      console.log(`   [warn] no download button on row ${i} (${filename})`);
      continue;
    }
    console.log(`   downloading ${filename} ...`);
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 120000 }),
      btn.click(),
    ]);
    await download.saveAs(dest);
    const size = fs.statSync(dest).size;
    console.log(`   [ok]  ${filename} (${(size/1024).toFixed(1)} KiB) -> ${dest}`);
    downloaded.push({ filename, path: dest, size });
  }
  return { ok: true, files: downloaded };
}

async function main() {
  const args = parseArgs(process.argv);
  const portal = args.portal
    ? JSON.parse(fs.readFileSync(args.portal, 'utf8'))
    : { portal_url: DEFAULT_30_PORTAL_URL, sheet: '30?coding??a?' };
  const url = portal.portal_url;

  fs.mkdirSync(args.outDir, { recursive: true });

  const browser = await chromium.launch({ headless: args.headless });
  const ctx = await browser.newContext({ acceptDownloads: true });
  const page = await ctx.newPage();

  console.log('==> opening portal');
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
  await page.waitForSelector('input.arco-input', { timeout: 30000 });

  const summary = {};
  for (const id of args.ids) {
    try {
      summary[id] = await searchAndDownload(page, id, args.outDir, args);
    } catch (e) {
      console.error(`[err] ${id}:`, e.message);
      summary[id] = { ok: false, error: e.message };
    }
  }

  await browser.close();

  const reportPath = path.join(args.outDir, '_portal_fetch.json');
  fs.writeFileSync(reportPath, JSON.stringify(summary, null, 2));
  console.log(`\n==> summary written to ${reportPath}`);
  const failed = Object.entries(summary).filter(([, v]) => !v.ok);
  if (failed.length) {
    console.error(`==> ${failed.length} task(s) failed`);
    process.exit(1);
  }
}

main().catch(e => { console.error(e); process.exit(1); });
