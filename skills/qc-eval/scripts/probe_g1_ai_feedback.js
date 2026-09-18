#!/usr/bin/env node
/**
 * Probe and optionally update the AI trajectory-quality feedback panel.
 *
 * The default mode only reads the visible Ark review page after opening
 * 「AI 质检」 and saves the panel text, page HTML, and screenshot locally.
 *
 * Update mode is deliberately narrow: it can edit only the AI accuracy radio,
 * the AI feedback reason, and click 「提交反馈」. It never edits the scoring
 * or QC form panels.
 *
 * Usage:
 *   node skills/qc-eval/scripts/probe_g1_ai_feedback.js --task-id 8818
 *   node skills/qc-eval/scripts/probe_g1_ai_feedback.js --task-id 8818 \
 *     --update --answers tasks/8818/ai_feedback_answers.json \
 *     --confirm-user-instructed
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const SKILL_DIR = path.resolve(HERE, '..');
const REPO_ROOT = path.resolve(SKILL_DIR, '..', '..');
const DEFAULT_STATE = path.join(SKILL_DIR, '.ark_platform_state.json');

function parseArgs(argv) {
  const opts = { taskId: '', state: DEFAULT_STATE, outputDir: '', answers: '', update: false };
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--task-id') opts.taskId = argv[++i] || '';
    else if (arg === '--state') opts.state = argv[++i] || DEFAULT_STATE;
    else if (arg === '--output-dir') opts.outputDir = argv[++i] || '';
    else if (arg === '--answers') opts.answers = argv[++i] || '';
    else if (arg === '--update') opts.update = true;
    else if (arg === '--confirm-user-instructed') opts.confirm = true;
    else if (arg === '--headed') opts.headed = true;
    else if (arg === '--no-screenshots') opts.noScreenshots = true;
    else if (!opts.taskId && !arg.startsWith('--')) opts.taskId = arg;
    else throw new Error(`unknown argument: ${arg}`);
  }
  if (!opts.taskId) {
    throw new Error('usage: node probe_g1_ai_feedback.js --task-id <任务ID> [--update --answers <json> --confirm-user-instructed]');
  }
  if (opts.update && (!opts.answers || !opts.confirm)) {
    throw new Error('--update requires --answers and --confirm-user-instructed');
  }
  return opts;
}

function readJSON(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function writeJSON(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

function safeName(value) {
  return String(value || '').replace(/[^A-Za-z0-9._-]+/g, '_');
}

function relative(file) {
  return path.relative(REPO_ROOT, file).replace(/\\/g, '/');
}

function loadModels(taskId) {
  const mapPath = path.join(REPO_ROOT, 'tasks', taskId, 'model_map.json');
  if (!fs.existsSync(mapPath)) throw new Error(`missing ${relative(mapPath)}; run platform collection first`);
  const map = readJSON(mapPath);
  const models = Object.entries(map.models || {})
    .map(([sheet, row]) => ({ sheet, ...row }))
    .filter((row) => row.task_model_run_id && !row.missing && !row.artifact_missing);
  if (!models.length) throw new Error(`task ${taskId} has no completed model review pages`);
  return { map, models };
}

function isIncompleteAudit(taskId, row) {
  const auditPath = path.join(
    REPO_ROOT,
    'tasks',
    taskId,
    'ark_g1',
    `${row.task_model_run_id}__${row.platform}`,
    'audit.json',
  );
  if (!fs.existsSync(auditPath)) return true;
  const audit = readJSON(auditPath);
  const trajectory = audit?.aiQc?.trajectoryResult || audit?.trajectoryResult;
  return !trajectory
    || trajectory.status !== 'success'
    || !trajectory.resultJson?.FeedbackGrade;
}

function classifyAiQcPanel(panelText) {
  const text = String(panelText || '').replace(/\s+/g, ' ').trim();
  const unavailableMarkers = [
    ['结果待复核', '结果待复核'],
    ['重试耗尽', '重试耗尽'],
    ['人工兜底', '人工兜底'],
    ['provider_job_stuck', 'provider_job_stuck'],
    ['脏数据状态未知', '脏数据状态未知'],
  ];
  for (const [marker, reason] of unavailableMarkers) {
    if (text.includes(marker)) {
      return {
        available: false,
        reason: `方舟平台 AI 质检无正常结果：${reason}`,
      };
    }
  }
  if (!text.includes('质检通过') && !text.includes('质检异常')) {
    return {
      available: false,
      reason: '方舟平台 AI 质检页面未显示正常质检结果',
    };
  }
  return { available: true, reason: '' };
}

async function openPanel(page, row) {
  await page.goto(row.audit_url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  const button = page.getByRole('button', { name: /AI 质检/ });
  await button.waitFor({ state: 'visible', timeout: 60000 });
  await button.click();
  await page.getByText('AI 轨迹质检', { exact: true })
    .waitFor({ state: 'visible', timeout: 30000 });
}

async function extractPanel(page, taskId, row, outputDir, noScreenshots) {
  fs.mkdirSync(outputDir, { recursive: true });
  const bodyText = await page.locator('body').innerText();
  const marker = bodyText.lastIndexOf('AI 轨迹质检');
  const panelText = marker >= 0 ? bodyText.slice(marker) : '';
  const htmlPath = path.join(outputDir, `${safeName(row.sheet)}__${safeName(row.platform)}.html`);
  const textPath = path.join(outputDir, `${safeName(row.sheet)}__${safeName(row.platform)}.txt`);
  const screenshotPath = path.join(outputDir, `${safeName(row.sheet)}__${safeName(row.platform)}.png`);
  fs.writeFileSync(htmlPath, await page.content(), 'utf8');
  fs.writeFileSync(textPath, panelText || bodyText, 'utf8');
  if (!noScreenshots) await page.screenshot({ path: screenshotPath, fullPage: true });

  const accuracyReason = await page.getByRole('textbox', { name: 'AI 质检反馈原因' })
    .inputValue()
    .catch(() => '');
  const checkedAccuracy = await page.locator('input[type="radio"]:checked')
    .evaluate((el) => el.getAttribute('aria-label') || el.parentElement?.innerText || '')
    .catch(() => '');
  const platformState = classifyAiQcPanel(panelText || bodyText);

  return {
    task_id: String(taskId),
    sheet: row.sheet,
    code: row.code,
    platform: row.platform,
    task_model_run_id: row.task_model_run_id,
    audit_url: row.audit_url,
    captured_at: new Date().toISOString(),
    ai_panel_text: panelText || bodyText,
    platform_ai_qc_available: platformState.available,
    platform_skip_reason: platformState.reason,
    existing_accuracy: checkedAccuracy.trim(),
    existing_reason: accuracyReason,
    files: {
      html: relative(htmlPath),
      text: relative(textPath),
      screenshot: noScreenshots ? '' : relative(screenshotPath),
    },
  };
}

function loadAnswers(file, models, taskId) {
  const data = readJSON(file);
  const source = data.models || data;
  const allowed = new Set(['准确', '不准确']);
  const out = {};
  for (const row of models) {
    const answer = source[row.sheet] || source[row.code] || source[row.platform];
    if (isIncompleteAudit(taskId, row) || answer?.platform_skip === true) {
      out[row.sheet] = null;
      continue;
    }
    if (!answer) throw new Error(`answers missing model ${row.sheet}`);
    const accuracy = String(
      answer.accuracy || answer.platform_accuracy || answer.choice || '',
    ).trim();
    const reason = String(
      answer.platform_reason || answer.reason || '',
    ).trim();
    if (!allowed.has(accuracy)) throw new Error(`${row.sheet}: accuracy must be 准确 or 不准确`);
    if (!reason || reason.length > 500) throw new Error(`${row.sheet}: reason must be 1-500 characters`);
    out[row.sheet] = { accuracy, reason };
  }
  return out;
}

async function updatePanel(page, row, answer, taskId, outputDir, noScreenshots) {
  const panelText = await page.locator('body').innerText();
  const platformState = classifyAiQcPanel(panelText);
  if (!platformState.available) {
    return {
      skipped: true,
      skip_reason: platformState.reason,
    };
  }

  const reason = page.getByRole('textbox', { name: 'AI 质检反馈原因' });
  const accuracyRadio = page.locator('label.arco-radio-button')
    .filter({ hasText: answer.accuracy })
    .first();

  await reason.waitFor({ state: 'visible', timeout: 10000 });
  await accuracyRadio.waitFor({ state: 'visible', timeout: 10000 });

  const reasonDisabled = await reason.isDisabled().catch(() => true);
  const radioDisabled = await accuracyRadio.locator('input').isDisabled().catch(() => true);

  // New tasks expose an editable feedback form immediately. Existing feedback
  // records may require reopening, so click 「重新编辑」 only when fields are locked.
  if (reasonDisabled || radioDisabled) {
    const reopen = page.getByRole('button', { name: '重新编辑', exact: true });
    if (!(await reopen.isEnabled().catch(() => false))) {
      return {
        skipped: true,
        skip_reason: '方舟平台当前账号或审核状态不支持编辑 AI 质检人工反馈',
      };
    }
    await reopen.click();
    await reason.waitFor({ state: 'visible', timeout: 10000 });
  }

  // Arco renders the input as a hidden radio and exposes the visible label
  // as the clickable control.
  await accuracyRadio.click({ force: true });
  await reason.fill(answer.reason);

  const submit = page.getByRole('button', { name: '提交反馈', exact: true });
  if (!(await submit.isEnabled())) {
    return {
      skipped: true,
      skip_reason: '方舟平台 AI 质检人工反馈提交按钮不可用',
    };
  }
  await submit.click();

  // The page already contains 「已反馈」 before editing, so waiting only for
  // that text can report success before the submit request finishes.
  await page.waitForFunction(() => {
    const textarea = document.querySelector('textarea[aria-label="AI 质检反馈原因"]');
    const buttons = [...document.querySelectorAll('button')];
    const submitButton = buttons.find((button) => button.textContent?.trim() === '提交反馈');
    return textarea?.disabled === true && submitButton?.disabled === true;
  }, undefined, { timeout: 5000 }).catch(async () => {
    await page.waitForTimeout(1500);
  });

  // Reload and read the server-rendered state. This is the authoritative save
  // check and also catches clicks that only changed the local React state.
  await page.reload({ waitUntil: 'domcontentloaded', timeout: 60000 });
  await openPanel(page, row);
  const verified = await extractPanel(page, taskId, row, outputDir, noScreenshots);
  if (verified.existing_accuracy !== answer.accuracy) {
    throw new Error(
      `${row.sheet}: platform accuracy save mismatch; ` +
      `expected=${answer.accuracy} actual=${verified.existing_accuracy}`,
    );
  }
  if (verified.existing_reason !== answer.reason) {
    throw new Error(
      `${row.sheet}: platform reason save mismatch after reload`,
    );
  }
  return verified;
}

async function main() {
  const opts = parseArgs(process.argv);
  if (!fs.existsSync(opts.state)) throw new Error(`missing Ark state: ${opts.state}`);
  const { map, models } = loadModels(opts.taskId);
  const outputDir = opts.outputDir || path.join(REPO_ROOT, 'tasks', opts.taskId, 'ark_g1', 'ai_feedback');
  const answers = opts.update ? loadAnswers(opts.answers, models, opts.taskId) : {};
  const browser = await chromium.launch({ headless: !opts.headed });
  const context = await browser.newContext({ storageState: opts.state });
  const summary = {
    task_id: String(opts.taskId),
    project_id: map.project_id || 383,
    mode: opts.update ? 'update' : 'probe',
    captured_at: new Date().toISOString(),
    models: [],
  };

  try {
    for (const row of models) {
      if (opts.update && !answers[row.sheet]) {
        console.log(`==> ${opts.taskId} ${row.sheet}：AI质检未完成，跳过平台反馈`);
        continue;
      }
      const page = await context.newPage();
      try {
        console.log(`==> ${opts.taskId} ${row.sheet} (${row.platform})`);
        await openPanel(page, row);
        const captured = await extractPanel(
          page,
          opts.taskId,
          row,
          outputDir,
          opts.noScreenshots,
        );
        if (opts.update) {
          if (!captured.platform_ai_qc_available) {
            captured.platform_feedback_skipped = true;
            console.log(`   skipped: ${captured.platform_skip_reason}`);
          } else {
            const result = await updatePanel(
              page,
              row,
              answers[row.sheet],
              opts.taskId,
              outputDir,
              opts.noScreenshots,
            );
            if (result.skipped) {
              captured.platform_feedback_skipped = true;
              captured.platform_skip_reason = result.skip_reason;
              console.log(`   skipped: ${result.skip_reason}`);
            } else {
              Object.assign(captured, result);
              captured.updated = true;
              captured.submitted_accuracy = answers[row.sheet].accuracy;
              captured.submitted_reason = answers[row.sheet].reason;
              captured.submitted_at = new Date().toISOString();
            }
          }
        }
        const modelPath = path.join(outputDir, `${safeName(row.sheet)}__${safeName(row.platform)}.json`);
        writeJSON(modelPath, captured);
        summary.models.push(captured);
        console.log(`   saved ${relative(modelPath)}`);
      } finally {
        await page.close();
      }
    }
    writeJSON(path.join(outputDir, 'summary.json'), summary);
    console.log(`==> wrote ${relative(path.join(outputDir, 'summary.json'))}`);
  } finally {
    await context.close();
    await browser.close();
  }
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.stack || error.message || error);
    process.exit(1);
  });
}

module.exports = {
  classifyAiQcPanel,
};
