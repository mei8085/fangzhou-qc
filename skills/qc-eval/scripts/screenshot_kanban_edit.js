#!/usr/bin/env node
// Capture real Team Kanban edit/filter interactions for B6ZOVB-style tasks.

const fs = require('fs');
const path = require('path');
const { spawn, spawnSync } = require('child_process');
const { chromium } = require('playwright');

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const TERMINAL_FONT = [
  '"Cascadia Mono"',
  '"Microsoft YaHei UI"',
  '"Microsoft YaHei"',
  '"Segoe UI Symbol"',
  'Consolas',
  'monospace',
].join(', ');
const ANSI_RE = /\x1B\[[0-?]*[ -/]*[@-~]/g;

function safe(name) {
  return String(name).replace(/[^0-9A-Za-z_.-]+/g, '_');
}

function killTree(pid) {
  if (!pid) return;
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/F', '/T', '/PID', String(pid)], { stdio: 'ignore' });
  } else {
    try { process.kill(-pid); } catch (_) {}
    try { process.kill(pid); } catch (_) {}
  }
}

function startDev(cwd, port) {
  const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const child = spawn(npm, ['run', 'dev', '--', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
    cwd,
    shell: process.platform === 'win32',
    env: { ...process.env, BROWSER: 'none', CI: '1' },
    windowsHide: true,
  });
  let output = '';
  child.stdout.on('data', d => { output += d.toString(); });
  child.stderr.on('data', d => { output += d.toString(); });
  return { child, output: () => output };
}

function runBuild(cwd) {
  const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const res = spawnSync(npm, ['run', 'build'], {
    cwd,
    shell: process.platform === 'win32',
    env: { ...process.env, BROWSER: 'none', CI: '1', FORCE_COLOR: '0' },
    encoding: 'utf8',
    errors: 'replace',
    maxBuffer: 20 * 1024 * 1024,
    windowsHide: true,
  });
  const output = [res.stdout || '', res.stderr || ''].filter(Boolean).join('\n').replace(ANSI_RE, '');
  return [`> ${npm} run build`, output.trim()].filter(Boolean).join('\n\n');
}

async function renderTerminal(browser, text, outPath) {
  const page = await browser.newPage({ viewport: { width: 1320, height: 900 }, deviceScaleFactor: 1 });
  try {
    await page.setContent(`<!doctype html>
<meta charset="utf-8">
<style>
  body{margin:0;background:#0d1117;color:#e6edf3;font-family:${TERMINAL_FONT};font-size:18px;line-height:1.45}
  pre{margin:0;padding:22px;white-space:pre-wrap;word-break:break-word}
</style>
<pre></pre>`);
    await page.locator('pre').evaluate((el, value) => { el.textContent = value; }, text);
    await page.screenshot({ path: outPath, fullPage: true });
  } finally {
    await page.close();
  }
}

async function waitForServer(proc, port, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  const url = `http://127.0.0.1:${port}`;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url);
      if (res.status < 500) return url;
    } catch (_) {}
    if (proc.child.exitCode !== null) break;
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error(proc.output() || `dev server not ready on ${port}`);
}

function isoDate(offsetDays) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

async function maybeSelectByText(page, labelText, optionText) {
  const field = page.locator('label').filter({ hasText: labelText }).locator('select').first();
  if (await field.count()) {
    await field.selectOption({ label: optionText }).catch(async () => {
      const values = await field.locator('option').evaluateAll(opts => opts.map(o => ({ value: o.value, text: o.textContent })));
      const found = values.find(o => (o.text || '').includes(optionText));
      if (found) await field.selectOption(found.value);
    });
  }
}

async function fillCardForm(page, { title, priority = '高', dueDate, description }) {
  const panel = page.locator('.dialog-panel, [role="dialog"]').last();
  const titleInput = panel.getByPlaceholder(/请输入任务标题/).first();
  await titleInput.waitFor({ state: 'visible', timeout: 10000 });
  await titleInput.fill(title);

  const prioritySelect = panel.locator('label').filter({ hasText: '优先级' }).locator('select').first();
  if (await prioritySelect.count()) {
    await prioritySelect.selectOption({ label: priority }).catch(async () => {
      const values = await prioritySelect.locator('option').evaluateAll(opts => opts.map(o => ({ value: o.value, text: o.textContent })));
      const found = values.find(o => (o.text || '').includes(priority));
      if (found) await prioritySelect.selectOption(found.value);
    });
  }

  const date = panel.locator('input[type="date"]').first();
  if (await date.count()) {
    await date.fill(dueDate);
  }

  const desc = panel.locator('textarea').first();
  if (await desc.count()) {
    await desc.fill(description);
  }
}

async function submitDialog(page, label) {
  const panel = page.locator('.dialog-panel, [role="dialog"]').last();
  const submit = panel.locator('button[type="submit"]').last();
  const button = await submit.count()
    ? submit
    : panel.getByRole('button', { name: new RegExp(label) }).last();
  await button.waitFor({ state: 'visible', timeout: 10000 });
  await button.click();
}

async function processModel(browser, taskId, col, info, port, outDir) {
  const tag = safe(col);
  const cwd = path.join(REPO_ROOT, 'tasks', taskId, 'extracted', info.code);
  await renderTerminal(browser, runBuild(cwd), path.join(outDir, `${tag}_01_build_output.png`));
  const dev = startDev(cwd, port);
  try {
    const base = await waitForServer(dev, port);
    const context = await browser.newContext({ viewport: { width: 1500, height: 1100 }, deviceScaleFactor: 1 });
    await context.addInitScript(() => localStorage.clear());
    const page = await context.newPage();
    await page.goto(base, { waitUntil: 'networkidle', timeout: 60000 });
    await page.getByRole('button', { name: /添加卡片/ }).first().click();
    await fillCardForm(page, {
      title: '排查 ERROR 日志',
      priority: '高',
      dueDate: isoDate(0),
      description: '需要补充描述摘要并验证今日到期状态。',
    });
    await submitDialog(page, '添加');
    await page.waitForTimeout(1000);
    if (!(await page.locator('body').innerText()).includes('排查 ERROR 日志')) {
      await page.screenshot({ path: path.join(outDir, `${tag}_debug_after_add.png`), fullPage: false });
      throw new Error(`${tag}: card was not added`);
    }
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(outDir, `${tag}_02_page_added_card.png`), fullPage: false });

    const edit = page.getByLabel(/编辑任务.*排查 ERROR 日志/).first()
      .or(page.getByRole('button', { name: /编辑任务|编辑/ }).first())
      .first();
    if (await edit.count()) {
      await edit.click();
      await page.getByText(/编辑任务/).first().waitFor({ state: 'visible', timeout: 10000 }).catch(() => {});
      await page.screenshot({ path: path.join(outDir, `${tag}_03_page_edit_dialog.png`), fullPage: false });
      await fillCardForm(page, {
        title: '排查 ERROR 日志已编辑',
        priority: '低',
        dueDate: isoDate(5),
        description: '编辑后描述摘要会回写到任务卡片，用于验证保存链路。',
      });
      await submitDialog(page, '保存|更新|确定');
      await page.getByText('排查 ERROR 日志已编辑').first().waitFor({ state: 'visible', timeout: 10000 });
      await page.waitForTimeout(500);
    }
    await page.screenshot({ path: path.join(outDir, `${tag}_04_page_saved_card.png`), fullPage: false });

    await maybeSelectByText(page, '截止状态', '未来到期');
    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(outDir, `${tag}_05_page_due_filter.png`), fullPage: false });
    await context.close();
  } finally {
    killTree(dev.child.pid);
    await new Promise(r => setTimeout(r, 600));
  }
}

async function main() {
  const taskId = process.argv[2];
  if (!taskId) {
    console.error('usage: node screenshot_kanban_edit.js <TASK_ID>');
    process.exit(2);
  }
  const taskDir = path.join(REPO_ROOT, 'tasks', taskId);
  const outDir = path.join(REPO_ROOT, 'delivery', taskId, 'screenshots');
  fs.mkdirSync(outDir, { recursive: true });
  const mm = JSON.parse(fs.readFileSync(path.join(taskDir, 'model_map.json'), 'utf8'));
  for (const f of fs.readdirSync(outDir)) {
    if (
      f.endsWith('.png') &&
      (/_0[2-5]_page_/.test(f) || /_0[12]_(initial|cart_added)\.png$/.test(f) || /_debug_/.test(f))
    ) {
      fs.unlinkSync(path.join(outDir, f));
    }
  }
  const browser = await chromium.launch({ headless: true });
  try {
    let port = 5560;
    for (const col of mm.sheet_columns) {
      await processModel(browser, taskId, col, mm.models[col], port++, outDir);
    }
  } finally {
    await browser.close();
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
