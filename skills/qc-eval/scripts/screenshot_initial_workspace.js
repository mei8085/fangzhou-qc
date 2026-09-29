#!/usr/bin/env node
// Capture the actual Ark initial-workspace page after reviewer confirmation.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const readline = require('readline/promises');

async function main() {
  const [taskId, flag, url] = process.argv.slice(2);
  if (!taskId || flag !== '--url' || !url || !/^[A-Za-z0-9_-]+$/.test(taskId)) {
    throw new Error('usage: screenshot_initial_workspace.js <任务ID> --url <平台任务页面URL>');
  }
  const target = new URL(url);
  if (target.protocol !== 'https:' || target.hostname !== 'ark.volcengine.com') {
    throw new Error('必须使用 Ark 平台 HTTPS 页面');
  }

  const root = path.resolve(__dirname, '../../..');
  const taskDir = path.join(root, 'tasks', taskId);
  const readJson = (file) => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
  const qc = readJson(path.join(taskDir, 'qc_cells.json'));
  const sheet = qc.sheet || {};
  const redline = String(
    sheet.redline_issue || sheet.redline_problem || sheet.red_flag_issue || ''
  );
  if (!redline.split(/[，,；;、\n]+/).map((item) => item.trim()).includes('0-1题目')) {
    throw new Error('需先在 qc_cells.json 中明确记录 0-1题目，不自动推断空仓');
  }

  const models = Object.keys(sheet.models || {});
  if (models.length !== 4) throw new Error('必须填写全部 4 个模型条目');
  const tags = models.map((name) => String(name).trim().replace(/[^0-9A-Za-z_.-]+/g, '_'));
  if (new Set(tags).size !== models.length) throw new Error('模型截图文件名冲突');

  const output = path.join(root, 'delivery', taskId, 'screenshots');
  const browser = await chromium.launch({ headless: false });
  const terminal = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    const context = await browser.newContext({
      storageState: path.resolve(__dirname, '../.ark_platform_state.json'),
      viewport: { width: 1440, height: 1000 },
    });
    const page = await context.newPage();
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    const answer = await terminal.question(
      '请在浏览器定位本任务初始代码仓，确认已加载且为空，并保留任务身份和空状态。输入 EMPTY 确认截图，其他输入取消：'
    );
    if (answer.trim() !== 'EMPTY') throw new Error('已取消截图');
    if (new URL(page.url()).hostname !== 'ark.volcengine.com') {
      throw new Error('当前不是 Ark 平台页面');
    }

    const screenshot = await page.screenshot({ fullPage: true });
    fs.mkdirSync(output, { recursive: true });
    for (const tag of tags) {
      fs.writeFileSync(path.join(output, `${tag}_01_initial_workspace_empty.png`), screenshot);
      fs.writeFileSync(path.join(output, `${tag}_verify.png`), screenshot);
    }
    console.log(`已保存 4 个模型的平台初始空仓截图：${output}；请核对截图内容并运行截图检查。`);
  } finally {
    terminal.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
