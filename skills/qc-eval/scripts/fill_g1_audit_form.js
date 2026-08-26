#!/usr/bin/env node
/**
 * Fill the Ark current-period QC form from delivery/<TASK_ID>/<TASK_ID>_audit_form_fill.json
 * and click only 「保存草稿」.
 *
 * Hard safety rules:
 *   - Never click 提交审核 / 打回 / 返回列表 / 添加附件 / 上一题 / 下一题.
 *   - Never edit 「评测打分」, Session 轨迹, or Workspace.
 *   - Abort any Audit Submit / Reject API even if the UI is mis-clicked.
 *   - This script cannot submit. Humans review the draft and submit later.
 *
 * Usage:
 *   node skills/qc-eval/scripts/fill_g1_audit_form.js --task-id 4267
 *   node skills/qc-eval/scripts/fill_g1_audit_form.js --task-id 4267 --only magma
 *   node skills/qc-eval/scripts/fill_g1_audit_form.js --task-id 4267 --dry-run
 *   node skills/qc-eval/scripts/fill_g1_audit_form.js --task-id 4267 --headed
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const SKILL_DIR = path.resolve(HERE, '..');
const REPO_ROOT = path.resolve(SKILL_DIR, '..', '..');
const DEFAULT_STATE = path.join(SKILL_DIR, '.ark_platform_state.json');
const FORM_TEMPLATE = path.join(SKILL_DIR, 'config', 'g1_audit_form.json');

const AUDIT_PANEL = '[data-testid="crowdtest-review-panel-audit"]';
const EVAL_PANEL = '[data-testid="crowdtest-review-panel-evaluation"]';
const SESSION_ROOT = '[data-testid="crowdtest-session-detail-root"]';
const WORKSPACE_ROOT = '[data-testid="crowdtest-workspace-framework"]';

const LABEL = {
  taskQuality: '请选择该任务的质量',
  taskNote: '任务质量备注',
  feedbackQuality: '请选择该用户的反馈质量',
  feedbackNote: '反馈质量备注',
  auditReason: '审核理由',
  dirtyTags: '请选择脏数据标签',
};

const SAVE_DRAFT = '保存草稿';
const FORBIDDEN_BUTTONS = new Set([
  '提交审核',
  '提交',
  '打回',
  '返回列表',
  '添加附件',
  '上一题',
  '下一题',
  '重启实例',
]);

const FORBIDDEN_API = /Audit(Submit|Reject|Return)|SpotCheckSubmit|CrowdtestTaskModelAuditSubmit/i;
const DRAFT_API = /Audit(Save|Draft|Update|Upsert|Create|Put)/i;
const POINTER_LOCK_SELECTOR = [EVAL_PANEL, SESSION_ROOT, WORKSPACE_ROOT].join(', ');

function parseArgs(argv) {
  const opts = { _: [] };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const k = a.slice(2);
      const next = argv[i + 1];
      opts[k] = next && !next.startsWith('--') ? argv[++i] : true;
    } else {
      opts._.push(a);
    }
  }
  if (!opts['task-id'] && opts._[0]) opts['task-id'] = opts._[0];
  return opts;
}

function usage(code = 2) {
  console.error(`usage:
  node skills/qc-eval/scripts/fill_g1_audit_form.js --task-id <任务ID>
       [--only <platform|code|sheet|runId>] [--dry-run] [--headed]
       [--state skills/qc-eval/.ark_platform_state.json]

This command writes the QC form and clicks 「保存草稿」 only.
It cannot submit. Do not pass --submit.`);
  process.exit(code);
}

function rel(p) {
  return path.relative(REPO_ROOT, p).replace(/\\/g, '/');
}

function readJSON(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function writeJSON(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function csrfFromState(statePath) {
  const state = readJSON(statePath);
  const cookie = (state.cookies || []).find(
    (c) => c.name === 'csrfToken' && String(c.domain || '').includes('volcengine.com'),
  );
  if (!cookie || !cookie.value) {
    throw new Error(`csrfToken cookie not found in ${statePath}; run fetch_g1_platform.js auth-from-chrome`);
  }
  return cookie.value;
}

function loadFillPayload(taskId) {
  const fillPath = path.join(REPO_ROOT, 'delivery', String(taskId), `${taskId}_audit_form_fill.json`);
  if (!fs.existsSync(fillPath)) {
    throw new Error(
      `missing ${rel(fillPath)}; run python3 skills/qc-eval/scripts/generate_model_qc_platform.py ${taskId} first`,
    );
  }
  return { fillPath, payload: readJSON(fillPath) };
}

function loadTemplateOptions() {
  if (!fs.existsSync(FORM_TEMPLATE)) return {};
  const template = readJSON(FORM_TEMPLATE);
  const out = {};
  for (const field of (template.qc_form || {}).fields || []) {
    out[field.label] = field;
  }
  return out;
}

function normalizeList(value) {
  if (value == null) return [];
  if (Array.isArray(value)) return value.map((v) => String(v).trim()).filter(Boolean);
  const text = String(value).trim();
  if (!text || text === '不选' || text.startsWith('不选（')) return [];
  return text.split(/[、,，;|]+/).map((v) => v.trim()).filter(Boolean);
}

function modelMatches(row, only) {
  if (!only) return true;
  const needle = String(only).trim().toLowerCase();
  const hay = [
    row.platform,
    row.code,
    row.sheet,
    row.task_model_run_id,
    row.audit_url,
  ].map((v) => String(v || '').trim().toLowerCase());
  return hay.some((v) => v === needle || v.includes(needle));
}

function validateRow(row, fields) {
  const f = row.fields || {};
  const taskQuality = String(f[LABEL.taskQuality] || '').trim();
  const feedbackQuality = String(f[LABEL.feedbackQuality] || '').trim();
  const auditReason = String(f[LABEL.auditReason] || '').trim();
  if (!row.audit_url && !row.task_model_run_id) {
    throw new Error(`${row.sheet || row.platform}: missing audit_url / task_model_run_id`);
  }
  const taskOpts = (fields[LABEL.taskQuality] || {}).options || ['高', '中', '低', '不可用'];
  const fbOpts = (fields[LABEL.feedbackQuality] || {}).options || ['完全可用', '部分可用', '完全不可用'];
  if (!taskOpts.includes(taskQuality)) {
    throw new Error(`${row.sheet}: invalid 任务质量 ${JSON.stringify(taskQuality)}`);
  }
  if (!fbOpts.includes(feedbackQuality)) {
    throw new Error(`${row.sheet}: invalid 反馈质量 ${JSON.stringify(feedbackQuality)}`);
  }
  if (!auditReason) {
    throw new Error(`${row.sheet}: 审核理由 is required`);
  }
  const dirtyOpts = (fields[LABEL.dirtyTags] || {}).options || [];
  const dirty = normalizeList(f[LABEL.dirtyTags]);
  for (const tag of dirty) {
    if (dirtyOpts.length && !dirtyOpts.includes(tag)) {
      throw new Error(`${row.sheet}: dirty tag not on the page: ${JSON.stringify(tag)}`);
    }
  }
  return {
    taskQuality,
    taskNote: String(f[LABEL.taskNote] || ''),
    feedbackQuality,
    feedbackNote: String(f[LABEL.feedbackNote] || ''),
    auditReason,
    dirtyTags: dirty,
  };
}

function apiAction(url) {
  try {
    const clean = String(url || '').split('?')[0];
    return clean.split('/').filter(Boolean).pop() || '';
  } catch {
    return '';
  }
}

function assertAllowedButtonName(name) {
  const text = String(name || '').replace(/\s+/g, '').trim();
  if (text !== SAVE_DRAFT) {
    throw new Error(`refusing to click ${JSON.stringify(name)}; only 「${SAVE_DRAFT}」 is allowed`);
  }
}

async function installGuards(page, calls) {
  await page.route('**/api/top/ark/**', async (route) => {
    const url = route.request().url();
    const action = apiAction(url);
    if (FORBIDDEN_API.test(action) || FORBIDDEN_API.test(url)) {
      console.error(`   [block] forbidden Ark action: ${action}`);
      calls.push({
        action,
        method: route.request().method(),
        blocked: true,
        at: new Date().toISOString(),
      });
      await route.abort('failed');
      return;
    }
    await route.continue();
  });

  page.on('request', (req) => {
    const url = req.url();
    if (!url.includes('/api/top/ark/')) return;
    const action = apiAction(url);
    calls.push({
      action,
      method: req.method(),
      postData: req.postData(),
      at: new Date().toISOString(),
    });
  });

  page.on('dialog', async (dialog) => {
    const msg = dialog.message() || '';
    if (/提交|打回/.test(msg)) {
      await dialog.dismiss();
      throw new Error(`blocked confirm dialog: ${msg}`);
    }
    await dialog.dismiss();
  });
}

async function lockNonQcPanels(page) {
  await page.evaluate((selector) => {
    document.querySelectorAll(selector).forEach((el) => {
      el.setAttribute('data-qc-pointer-lock', '1');
      el.style.pointerEvents = 'none';
    });
  }, POINTER_LOCK_SELECTOR);
}

async function snapshotEvalPanel(page) {
  const panel = page.locator(EVAL_PANEL);
  if (!(await panel.count())) return { present: false, textareas: [], text: '' };
  const textareas = await panel.locator('textarea').evaluateAll((els) =>
    els.map((el) => ({
      placeholder: el.getAttribute('placeholder') || '',
      value: el.value || '',
    })),
  );
  const radios = await panel.locator('[role="radio"][aria-checked="true"]').allInnerTexts();
  return {
    present: true,
    textareas,
    radios: radios.map((t) => t.replace(/\s+/g, ' ').trim()),
  };
}

function sameEvalSnapshot(before, after) {
  return JSON.stringify(before) === JSON.stringify(after);
}

async function openAuditPage(page, row) {
  const url = row.audit_url
    || `https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/projects/281/review/${row.task_model_run_id}?mode=audit`;
  let lastErr;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
      lastErr = null;
      break;
    } catch (err) {
      lastErr = err;
      console.warn(`   [retry] goto attempt ${attempt}/3: ${err.message}`);
      await sleep(800 * attempt);
    }
  }
  if (lastErr) throw lastErr;
  const audit = page.locator(AUDIT_PANEL);
  await audit.waitFor({ state: 'visible', timeout: 60000 });
  const qualityGroup = audit.locator(`[role="radiogroup"][aria-label="${LABEL.taskQuality}"]`);
  if (!(await qualityGroup.isVisible().catch(() => false))) {
    await audit.locator('[data-review-panel-heading="true"]').click();
    await qualityGroup.waitFor({ state: 'visible', timeout: 15000 });
  }
  await qualityGroup.scrollIntoViewIfNeeded();
  return { url, audit };
}

async function clickRadio(root, ariaLabel, option) {
  const group = root.locator(`[role="radiogroup"][aria-label="${ariaLabel}"]`);
  await group.waitFor({ state: 'visible', timeout: 15000 });
  const radio = group.getByRole('radio', { name: option, exact: true });
  await radio.scrollIntoViewIfNeeded();
  if ((await radio.getAttribute('aria-checked')) === 'true') {
    return;
  }
  await radio.click();
  const checked = await radio.getAttribute('aria-checked');
  if (checked !== 'true') {
    throw new Error(`radio ${ariaLabel}=${option} did not become checked`);
  }
}

function noteTextarea(root, label) {
  if (label === LABEL.taskNote) {
    return root.locator('textarea[placeholder="请输入备注"]').nth(0);
  }
  if (label === LABEL.feedbackNote) {
    return root.locator('textarea[placeholder="请输入备注"]').nth(1);
  }
  if (label === LABEL.auditReason) {
    return root.locator('textarea[aria-label="审核理由"]');
  }
  return root.locator(`xpath=.//div[normalize-space()="${label}"]/following-sibling::textarea[1]`);
}

async function fillLabeledTextarea(root, label, value) {
  const textarea = noteTextarea(root, label);
  await textarea.waitFor({ state: 'visible', timeout: 15000 });
  await textarea.scrollIntoViewIfNeeded();
  const want = value || '';
  const disabled = await textarea.isDisabled();
  const current = await textarea.inputValue();
  if (current === want) {
    return;
  }
  if (disabled) {
    throw new Error(`${label} is disabled and does not match the fill value`);
  }
  await textarea.click();
  await textarea.fill(want);
  const got = await textarea.inputValue();
  if (got !== want) {
    await textarea.evaluate((el, v) => {
      const proto = window.HTMLTextAreaElement.prototype;
      const desc = Object.getOwnPropertyDescriptor(proto, 'value');
      desc.set.call(el, v);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }, want);
  }
}

async function fillAuditReason(root, value) {
  await fillLabeledTextarea(root, LABEL.auditReason, value);
}

function dirtySection(root) {
  return root.locator('div.rounded-lg', {
    has: root.getByText(LABEL.dirtyTags, { exact: true }),
  }).first();
}

async function setDirtyTags(root, wanted) {
  const section = dirtySection(root);
  const buttons = section.locator('button[aria-pressed]');
  const count = await buttons.count();
  const wantedSet = new Set(wanted);
  for (let i = 0; i < count; i++) {
    const btn = buttons.nth(i);
    const name = (await btn.innerText()).replace(/\s+/g, ' ').trim();
    const pressed = (await btn.getAttribute('aria-pressed')) === 'true';
    const should = wantedSet.has(name);
    if (pressed !== should) {
      await btn.scrollIntoViewIfNeeded();
      await btn.click();
    }
  }
}

async function readFilled(root) {
  const checked = async (label) => {
    const radio = root.locator(`[role="radiogroup"][aria-label="${label}"] [role="radio"][aria-checked="true"]`);
    if (!(await radio.count())) return '';
    return (await radio.innerText()).replace(/\s+/g, ' ').trim();
  };
  const note = async (label) => noteTextarea(root, label).inputValue();
  const dirty = [];
  const section = dirtySection(root);
  const buttons = section.locator('button[aria-pressed="true"]');
  const count = await buttons.count();
  for (let i = 0; i < count; i++) {
    dirty.push((await buttons.nth(i).innerText()).replace(/\s+/g, ' ').trim());
  }
  return {
    [LABEL.taskQuality]: await checked(LABEL.taskQuality),
    [LABEL.taskNote]: await note(LABEL.taskNote),
    [LABEL.feedbackQuality]: await checked(LABEL.feedbackQuality),
    [LABEL.feedbackNote]: await note(LABEL.feedbackNote),
    [LABEL.auditReason]: await noteTextarea(root, LABEL.auditReason).inputValue(),
    [LABEL.dirtyTags]: dirty,
  };
}

function filledMatches(got, want) {
  const issues = [];
  if (got[LABEL.taskQuality] !== want.taskQuality) {
    issues.push(`任务质量 got ${JSON.stringify(got[LABEL.taskQuality])}`);
  }
  if (got[LABEL.feedbackQuality] !== want.feedbackQuality) {
    issues.push(`反馈质量 got ${JSON.stringify(got[LABEL.feedbackQuality])}`);
  }
  if (String(got[LABEL.taskNote] || '') !== want.taskNote) issues.push('任务质量备注 mismatch');
  if (String(got[LABEL.feedbackNote] || '') !== want.feedbackNote) issues.push('反馈质量备注 mismatch');
  if (String(got[LABEL.auditReason] || '') !== want.auditReason) issues.push('审核理由 mismatch');
  const gotDirty = [...(got[LABEL.dirtyTags] || [])].sort().join('|');
  const wantDirty = [...want.dirtyTags].sort().join('|');
  if (gotDirty !== wantDirty) issues.push(`脏数据标签 got ${JSON.stringify(got[LABEL.dirtyTags])}`);
  return issues;
}

async function clickSaveDraft(page) {
  const footer = page.locator('.evs-footer');
  const btn = footer.getByRole('button', { name: SAVE_DRAFT, exact: true });
  await btn.waitFor({ state: 'visible', timeout: 15000 });
  const name = (await btn.innerText()).replace(/\s+/g, '').trim();
  assertAllowedButtonName(name);
  if (await btn.isDisabled()) {
    throw new Error('「保存草稿」 is disabled; refusing to click any other footer button');
  }
  const forbidden = footer.getByRole('button', { name: /提交审核|打回/ });
  const forbiddenCount = await forbidden.count();
  for (let i = 0; i < forbiddenCount; i++) {
    const other = forbidden.nth(i);
    const otherName = (await other.innerText()).replace(/\s+/g, '').trim();
    if (FORBIDDEN_BUTTONS.has(otherName) && await other.isEnabled().catch(() => false)) {
      // Enabled 提交审核 after fill is expected. Never click it.
      console.log(`   [guard] footer has enabled ${otherName}; leaving it untouched`);
    }
  }
  await btn.scrollIntoViewIfNeeded();
  await btn.click();
}

async function waitForDraftSaved(page, calls, callsLen) {
  const started = Date.now();
  const timeoutMs = 20000;
  while (Date.now() - started < timeoutMs) {
    const newCalls = calls.slice(callsLen);
    const draftCall = newCalls.find((c) => DRAFT_API.test(c.action) && !FORBIDDEN_API.test(c.action));
    if (draftCall) return { via: 'api', action: draftCall.action };
    const toast = page.locator('.arco-message, [role="alert"], .arco-notification');
    if (await toast.count()) {
      const text = (await toast.first().innerText().catch(() => '')).replace(/\s+/g, ' ').trim();
      if (text && /草稿|保存成功|已保存/.test(text) && !/提交/.test(text)) {
        return { via: 'toast', text };
      }
      if (text && /失败|错误|提交/.test(text)) {
        throw new Error(`save draft toast looks wrong: ${text}`);
      }
    }
    await sleep(300);
  }
  return { via: 'timeout' };
}

async function shot(page, outPath) {
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  await page.screenshot({ path: outPath, fullPage: true });
}

async function fillOneModel(page, row, want, opts, outDir, calls) {
  const tag = `${row.task_model_run_id || 'run'}__${row.platform || row.code || 'model'}`;
  console.log(`\n==> fill ${row.sheet} / ${row.platform} run=${row.task_model_run_id}`);
  const opened = await openAuditPage(page, row);
  await lockNonQcPanels(page);
  const evalBefore = await snapshotEvalPanel(page);

  await clickRadio(opened.audit, LABEL.taskQuality, want.taskQuality);
  console.log(`   [field] ${LABEL.taskQuality}=${want.taskQuality}`);
  await fillLabeledTextarea(opened.audit, LABEL.taskNote, want.taskNote);
  console.log(`   [field] ${LABEL.taskNote} (${want.taskNote.length} chars)`);
  await clickRadio(opened.audit, LABEL.feedbackQuality, want.feedbackQuality);
  console.log(`   [field] ${LABEL.feedbackQuality}=${want.feedbackQuality}`);
  await fillLabeledTextarea(opened.audit, LABEL.feedbackNote, want.feedbackNote);
  console.log(`   [field] ${LABEL.feedbackNote} (${want.feedbackNote.length} chars)`);
  await fillAuditReason(opened.audit, want.auditReason);
  console.log(`   [field] ${LABEL.auditReason} (${want.auditReason.length} chars)`);
  await setDirtyTags(opened.audit, want.dirtyTags);
  console.log(`   [field] ${LABEL.dirtyTags}=${want.dirtyTags.join('、') || '不选'}`);

  const got = await readFilled(opened.audit);
  const mismatches = filledMatches(got, want);
  if (mismatches.length) {
    await shot(page, path.join(outDir, `_audit_fill_mismatch_${tag}.png`));
    throw new Error(`form mismatch: ${mismatches.join('; ')}`);
  }

  const evalAfterFill = await snapshotEvalPanel(page);
  if (evalBefore.present && !sameEvalSnapshot(evalBefore, evalAfterFill)) {
    throw new Error('评测打分 panel changed; aborting before save');
  }

  const beforeShot = path.join(outDir, `_audit_fill_${tag}.png`);
  await shot(page, beforeShot);
  console.log(`   [shot] ${rel(beforeShot)}`);

  if (opts['dry-run']) {
    console.log('   [dry-run] filled QC form; not clicking 保存草稿');
    return { ok: true, dryRun: true, url: opened.url, filled: got, screenshot: beforeShot };
  }

  const callsLen = calls.length;
  await clickSaveDraft(page);
  const saved = await waitForDraftSaved(page, calls, callsLen);
  await sleep(800);
  const afterShot = path.join(outDir, `_audit_fill_saved_${tag}.png`);
  await shot(page, afterShot);

  const evalAfterSave = await snapshotEvalPanel(page);
  if (evalBefore.present && !sameEvalSnapshot(evalBefore, evalAfterSave)) {
    throw new Error('评测打分 panel changed after save');
  }
  const still = await readFilled(opened.audit);
  const stillIssues = filledMatches(still, want);
  if (stillIssues.length) {
    throw new Error(`form lost values after save: ${stillIssues.join('; ')}`);
  }

  const newActions = [...new Set(calls.slice(callsLen).map((c) => c.action))];
  if (newActions.some((a) => FORBIDDEN_API.test(a))) {
    throw new Error(`forbidden API observed: ${newActions.join(', ')}`);
  }
  console.log(`   [saved] via=${saved.via} ${saved.action || saved.text || ''} apis=${newActions.join(',') || '(none captured)'}`);
  console.log(`   [shot] ${rel(afterShot)}`);
  return {
    ok: true,
    dryRun: false,
    url: opened.url,
    saved,
    apis: newActions,
    filled: still,
    screenshot: afterShot,
  };
}

async function launchBrowser(headed) {
  const headless = !headed;
  try {
    return await chromium.launch({ headless, channel: 'chrome' });
  } catch {
    return await chromium.launch({ headless });
  }
}

async function main() {
  const opts = parseArgs(process.argv);
  if (opts.submit || opts['submit'] || opts['confirm-submit']) {
    throw new Error('this script cannot submit; only 保存草稿 is allowed');
  }
  const taskId = opts['task-id'] || opts.task;
  if (!taskId || opts.help) usage(opts.help ? 0 : 2);

  const statePath = path.resolve(opts.state || DEFAULT_STATE);
  if (!fs.existsSync(statePath)) {
    throw new Error(`state file not found: ${statePath}; run node skills/qc-eval/scripts/fetch_g1_platform.js auth-from-chrome`);
  }
  csrfFromState(statePath);

  const { fillPath, payload } = loadFillPayload(taskId);
  const fields = loadTemplateOptions();
  const rows = (payload.models || []).filter((row) => modelMatches(row, opts.only));
  if (!rows.length) {
    throw new Error(`no models matched ${JSON.stringify(opts.only || '*')} in ${rel(fillPath)}`);
  }

  const outDir = path.join(REPO_ROOT, 'tasks', String(taskId), 'ark_g1');
  fs.mkdirSync(outDir, { recursive: true });
  console.log(`==> task ${taskId} models=${rows.map((r) => r.platform || r.sheet).join(',')} dry-run=${!!opts['dry-run']}`);
  console.log(`==> fill file ${rel(fillPath)}`);

  const browser = await launchBrowser(opts.headed);
  const ctx = await browser.newContext({
    storageState: statePath,
    viewport: { width: 1600, height: 1100 },
  });
  const calls = [];
  const results = [];
  let failed = null;
  try {
    for (const row of rows) {
      const page = await ctx.newPage();
      await installGuards(page, calls);
      try {
        const want = validateRow(row, fields);
        const result = await fillOneModel(page, row, want, opts, outDir, calls);
        results.push({
          sheet: row.sheet,
          platform: row.platform,
          task_model_run_id: row.task_model_run_id,
          ...result,
        });
      } catch (err) {
        const errShot = path.join(outDir, `_audit_fill_error.png`);
        await shot(page, errShot).catch(() => {});
        const html = await page.content().catch(() => '');
        if (html) fs.writeFileSync(path.join(outDir, `_audit_fill_error.html`), html);
        throw err;
      } finally {
        await page.close().catch(() => {});
      }
    }
  } catch (err) {
    failed = err;
    console.error(`==> failed: ${err.message}`);
  }

  const summary = {
    task_id: String(taskId),
    dry_run: !!opts['dry-run'],
    fill_file: rel(fillPath),
    saved_at: new Date().toISOString(),
    ok: !failed,
    error: failed ? String(failed.message || failed) : '',
    results,
    api_actions: [...new Set(calls.map((c) => c.action))],
  };
  const summaryPath = path.join(outDir, 'audit_fill_result.json');
  writeJSON(summaryPath, summary);
  console.log(`==> wrote ${rel(summaryPath)}`);

  await browser.close();
  if (failed) process.exit(1);
}

main().catch((err) => {
  console.error(err.stack || err.message || err);
  process.exit(1);
});
