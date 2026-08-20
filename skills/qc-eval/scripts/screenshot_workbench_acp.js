#!/usr/bin/env node
// Screenshot Vue intelligent-advisor workbench tasks with a mocked ACP backend.
// Usage: node skills/qc-eval/scripts/screenshot_workbench_acp.js <TASK_ID>

const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const REPO_ROOT = path.resolve(HERE, '..', '..', '..');

function sanitize(s) {
  return s.replace(/[^A-Za-z0-9._-]+/g, '_');
}

function stripAnsi(s) {
  return s.replace(/\x1b\[[0-9;]*m/g, '');
}

function killTree(pid) {
  if (!pid) return;
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/F', '/T', '/PID', String(pid)], { stdio: 'ignore' });
  } else {
    try { process.kill(-pid); } catch {}
    try { process.kill(pid); } catch {}
  }
}

async function waitForViteUrl(child, timeoutMs = 90000) {
  return new Promise((resolve, reject) => {
    let buf = '';
    const timer = setTimeout(() => reject(new Error(`vite timeout. last output:\n${buf.slice(-1000)}`)), timeoutMs);
    const onData = chunk => {
      buf += chunk.toString();
      const m = stripAnsi(buf).match(/Local:\s*(https?:\/\/[^\s]+?\/)/);
      if (m) {
        clearTimeout(timer);
        resolve(m[1]);
      }
    };
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
    child.on('exit', code => {
      clearTimeout(timer);
      reject(new Error(`vite exited with code ${code}. last output:\n${buf.slice(-1000)}`));
    });
  });
}

function ensureNodeModules(entryDir) {
  if (fs.existsSync(path.join(entryDir, 'node_modules', 'vite', 'package.json'))) return;
  console.log(`  npm install in ${entryDir}`);
  const r = spawnSync('npm.cmd', ['install', '--prefer-offline', '--no-audit', '--no-fund'], {
    cwd: entryDir,
    stdio: 'inherit',
    shell: true,
  });
  if (r.status !== 0) throw new Error(`npm install failed in ${entryDir}`);
}

async function startVite(entryDir, port) {
  ensureNodeModules(entryDir);
  const child = spawn('npm.cmd', ['run', 'dev', '--', '--port', String(port), '--strictPort'], {
    cwd: entryDir,
    shell: true,
    windowsHide: true,
  });
  const url = await waitForViteUrl(child).catch(e => {
    killTree(child.pid);
    throw e;
  });
  return { child, url };
}

function acpResponse() {
  return {
    jsonrpc: '2.0',
    id: '1',
    result: {
      id: 'task-demo-1',
      contextId: 'ctx-demo-1',
      history: [
        {
          role: 'user',
          parts: [{ type: 'text', text: '复盘黄金并给出今日跟进建议' }],
        },
        {
          role: 'agent',
          parts: [
            { type: 'text', text: '先读取实时行情和持仓情绪，再汇总成投顾建议。' },
            { type: 'data', data: { id: 'quote-1', name: 'market.quote', args: { symbol: 'XAUUSD', range: '1d' } } },
            {
              type: 'data',
              data: {
                id: 'quote-1',
                name: 'market.quote',
                response: '| 指标 | 数值 |\n| --- | --- |\n| 现价 | 2340 |\n| 波动 | 偏强震荡 |',
              },
            },
          ],
        },
      ],
      artifacts: [
        {
          parts: [
            {
              type: 'text',
              text: '## 今日跟进建议\n- 黄金短线仍在高位震荡，先看 2340 附近支撑。\n> 若美元指数继续走弱，可以提高黄金股关注优先级。\n\n| 维度 | 判断 |\n| --- | --- |\n| 趋势 | 偏强 |\n| 风险 | 追高回撤 |',
            },
          ],
        },
      ],
    },
  };
}

async function shootModel(browser, taskId, col, code, port) {
  const entryDir = path.join(REPO_ROOT, 'tasks', taskId, 'extracted', code);
  const outDir = path.join(REPO_ROOT, 'delivery', taskId, 'screenshots');
  fs.mkdirSync(outDir, { recursive: true });
  const safe = sanitize(col);

  console.log(`==> ${col} (${code})`);
  const dev = await startVite(entryDir, port);
  const url = dev.url.replace(/\/$/, '');
  const context = await browser.newContext({ viewport: { width: 1440, height: 920 }, deviceScaleFactor: 1 });
  await context.addInitScript(() => {
    localStorage.setItem('hxstock-logged-in', '1');
  });
  const page = await context.newPage();
  page.on('console', msg => {
    if (['error', 'warning'].includes(msg.type())) console.log(`  [${msg.type()}] ${msg.text().slice(0, 400)}`);
  });
  page.on('pageerror', err => console.log(`  [pageerror] ${err.message.slice(0, 400)}`));
  await page.route('**/api/', route => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(acpResponse()),
    });
  });

  try {
    await page.goto(`${url}/#/workbench`, { waitUntil: 'networkidle', timeout: 60000 });
    await page.waitForTimeout(1200);
    await page.screenshot({ path: path.join(outDir, `${safe}_01_welcome.png`), fullPage: true });

    const textarea = page.locator('textarea').first();
    await textarea.fill('复盘黄金并给出今日跟进建议');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(2500);
    await page.screenshot({ path: path.join(outDir, `${safe}_02_chat.png`), fullPage: true });
    console.log(`  ${safe}_01_welcome.png`);
    console.log(`  ${safe}_02_chat.png`);
  } finally {
    await context.close();
    killTree(dev.child.pid);
    await new Promise(resolve => setTimeout(resolve, 800));
  }
}

async function main() {
  const taskId = process.argv[2];
  if (!taskId) {
    console.error('usage: screenshot_workbench_acp.js <TASK_ID>');
    process.exit(2);
  }
  const map = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, 'tasks', taskId, 'model_map.json'), 'utf8'));
  const browser = await chromium.launch({ headless: true });
  let port = 5210;
  try {
    for (const col of map.sheet_columns || Object.keys(map.models)) {
      const info = map.models[col];
      await shootModel(browser, taskId, col, info.code, port++);
    }
  } finally {
    await browser.close();
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
