#!/usr/bin/env node
// One-off: start each model's Vite dev server, navigate, click 文件入库 tab,
// screenshot it. Used only for AUJ16L to differentiate the "async ingestion"
// panel across 4 models.

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require(path.join(__dirname, '..', '..', 'node_modules', 'playwright'));

const taskId = 'AUJ16L';
const taskDir = path.resolve(__dirname, '..', '..', '..', '..', 'tasks', taskId);
const mapPath = path.join(taskDir, 'model_map.json');
const outDir = path.resolve(__dirname, '..', '..', '..', '..', 'delivery', taskId, 'screenshots');
if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

const map = JSON.parse(fs.readFileSync(mapPath, 'utf-8'));

function stripAnsi(s) { return s.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, ''); }

async function waitForLocal(child, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    let buf = '';
    const timer = setTimeout(() => reject(new Error('timeout waiting Local:')), timeoutMs);
    const on = (data) => {
      buf += stripAnsi(String(data));
      const m = buf.match(/Local:\s+(http:\/\/[^\s]+)/);
      if (m) {
        clearTimeout(timer);
        child.stdout.off && child.stdout.off('data', on);
        child.stderr.off && child.stderr.off('data', on);
        resolve(m[1].trim());
      }
    };
    child.stdout.on('data', on);
    child.stderr.on('data', on);
    child.on('exit', () => reject(new Error('vite exited')));
  });
}

async function killTree(pid) {
  if (process.platform === 'win32') {
    await new Promise((r) => spawn('taskkill', ['/F', '/T', '/PID', String(pid)]).on('exit', r));
  } else {
    try { process.kill(-pid); } catch {}
  }
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const cols = map.sheet_columns;
  const models = map.models;

  for (let i = 0; i < cols.length; i++) {
    const col = cols[i];
    const info = models[col];
    const entryDir = path.join(taskDir, 'extracted', info.code, info.entry || '.');
    const port = 5190 + i;
    console.log(`==> ${col} (${info.code}) entry=${info.entry} port=${port}`);
    let dev;
    try {
      dev = spawn('npm', ['run', 'dev', '--', '--port', String(port), '--strictPort'], {
        cwd: entryDir, shell: true, detached: process.platform !== 'win32',
      });
      dev.stdout.pipe(process.stdout);
      dev.stderr.pipe(process.stderr);
      const url = await waitForLocal(dev, 40000);
      console.log('   local:', url);
      const page = await context.newPage();
      page.on('pageerror', (e) => console.log('   pageerror:', e.message.slice(0, 120)));
      await page.goto(url, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(1500);
      // Try clicking "文件入库" tab
      const clicked = await page.evaluate(() => {
        const btns = Array.from(document.querySelectorAll('button, a, div, span'));
        const t = btns.find((b) => b.textContent && b.textContent.trim() === '文件入库');
        if (t) { t.click(); return true; }
        return false;
      });
      console.log('   clicked 文件入库:', clicked);
      await page.waitForTimeout(1200);
      const outFile = path.join(outDir, `${col.replace(/\s+/g, '_')}_04_upload_tab.png`);
      await page.screenshot({ path: outFile, fullPage: true });
      console.log('   saved', path.basename(outFile));
      await page.close();
    } catch (e) {
      console.log('   ERR', e.message);
    } finally {
      if (dev) { await killTree(dev.pid); }
    }
  }

  await browser.close();
  console.log('done');
})().catch((e) => { console.error(e); process.exit(1); });
