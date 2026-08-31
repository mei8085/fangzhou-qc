#!/usr/bin/env node
// Fetch Ark 38 crowdtest data from the ark.volcengine.com platform.
//
// Main use:
//   node skills/qc-eval/scripts/fetch_38_platform.js auth-from-chrome
//   node skills/qc-eval/scripts/fetch_38_platform.js auth-login
//   node skills/qc-eval/scripts/fetch_38_platform.js collect --project 256 --task-id 475 --sheet-task-id <任务ID>
//
// Outputs:
//   tasks/<TASK_ID>/ark38/model_runs.json
//   tasks/<TASK_ID>/ark38/task.json
//   tasks/<TASK_ID>/ark38/task_uploads.json
//   tasks/<TASK_ID>/ark38/task_uploads/<first-round Prompt uploads>
//   tasks/<TASK_ID>/ark38/<RUN_ID>__<CODE_NAME>/
//     model_run.json
//     evaluation.json
//     workspace_browser.json
//     workspace/<downloaded zip>
//     trajectory/sessions.json
//     trajectory/<SESSION_ID>.json
//     trajectory/trajectory.md

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const { spawnSync } = require('child_process');
const { Readable } = require('stream');
const { pipeline } = require('stream/promises');

const HOST = 'https://console.volcengine.com';
const ARK_REFERER = 'https://ark.volcengine.com/';
const API_BASE = `${HOST}/api/top/ark/cn-beijing/2024-01-01`;
const HERE = __dirname;
const SKILL_DIR = path.resolve(HERE, '..');
const REPO_ROOT = path.resolve(SKILL_DIR, '..', '..');
const DEFAULT_STATE = path.join(SKILL_DIR, '.ark_platform_state.json');
const DEFAULT_PROJECT_ID = 256;
const DEFAULT_OUTPUT_SUBDIR = 'ark38';
const G1_CONFIG_PATH = path.join(SKILL_DIR, 'config', 'g1.json');
const DOWNLOAD_LIST_ACTION = 'CaseBffV1CrowdtestTaskModelWorkspaceDownloadLatestList';

function loadG1Config() {
  if (!fs.existsSync(G1_CONFIG_PATH)) return null;
  return readJSON(G1_CONFIG_PATH);
}

function g1SheetModel(codeName, config) {
  const key = String(codeName || '').trim().toLowerCase();
  for (const model of (config && config.models) || []) {
    if (String(model.platform || '').toLowerCase() === key) return model.sheet;
    if (String(model.code || '').toLowerCase() === key) return model.sheet;
  }
  return '';
}

const VISIBLE_COLUMNS = [
  'taskAndModel',
  'reviewEntry',
  'actions',
  'runtimeStatus',
  'score',
  'duration',
  'rounds',
  'tokens',
  'creator',
  'reviewer',
];

function parseArgs(argv) {
  const opts = { cmd: argv[2], _: [] };
  for (let i = 3; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const k = a.slice(2);
      const next = argv[i + 1];
      opts[k] = next && !next.startsWith('--') ? argv[++i] : true;
    } else {
      opts._.push(a);
    }
  }
  return opts;
}

function usage(code = 2) {
  console.error(`usage:
  node skills/qc-eval/scripts/fetch_38_platform.js auth-from-chrome [--state skills/qc-eval/.ark_platform_state.json] [--profile Default] [--chrome-user-data-dir <dir>]
  node skills/qc-eval/scripts/fetch_38_platform.js auth-login [--state skills/qc-eval/.ark_platform_state.json] [--url <login-url>]
  node skills/qc-eval/scripts/fetch_g1_platform.js discover-download --task-id 4267
  node skills/qc-eval/scripts/fetch_38_platform.js collect --project 256 (--task-id 475 | --task-title <title>) --sheet-task-id <任务ID> [--state <state.json>] [--tasks-dir tasks] [--skip-workspace] [--skip-trajectory] [--keep-existing] [--runs 1702,1701]
  node skills/qc-eval/scripts/fetch_38_platform.js find-project (--task-id 475 | --task-title <title>) [--projects 230-270|256] [--state <state.json>]

notes:
  auth-from-chrome copies volcengine cookies from the local Chrome profile (Windows VSS / macOS Keychain / Linux).
  If cookie export fails, it falls back to auth-login (headed Playwright window).
  find-project probes accessible crowdtest project ids and writes tasks/_38_project_probe_<keyword>.json.
  collect reads first-round Prompt uploads, task/model rows, per-run evaluation/audit data, 下载列表, workspace zip, and session trajectory JSON.
  After CaseBffV1CrowdtestTaskGet, collect downloads and inspects first-round uploads, then scans page + uploaded text for round-quota cheating. A hit skips workspace/trajectory/download-list.
  The current fetch_g1_platform.js wrapper searches project 286 by 任务ID and expects obelisk + notch.`);
  process.exit(code);
}

function rel(p) {
  return path.relative(REPO_ROOT, p).replace(/\\/g, '/');
}

function sanitize(s) {
  return String(s || '').replace(/[^\w.-]+/g, '_').replace(/^_+|_+$/g, '') || 'unknown';
}

function safeUploadName(value, fallback) {
  const base = path.posix.basename(String(value || '').replace(/\\/g, '/'));
  const cleaned = base.replace(/[\u0000-\u001f\u007f]/g, '_').replace(/[/:*?"<>|]/g, '_').trim();
  if (!cleaned || cleaned === '.' || cleaned === '..') return fallback;
  return cleaned.slice(0, 180);
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function writeJSON(file, value) {
  ensureDir(path.dirname(file));
  fs.writeFileSync(file, JSON.stringify(value, null, 2));
}

function readJSON(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function readCachedRunRows(taskDir) {
  if (!fs.existsSync(taskDir)) return [];
  return fs.readdirSync(taskDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => path.join(taskDir, entry.name, 'model_run.json'))
    .filter((file) => fs.existsSync(file))
    .map((file) => readJSON(file));
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isTransientApiError(err) {
  const msg = String((err && err.message) || err || '');
  return /InternalServiceTimeout|AccountFlowLimitExceeded|timeout/i.test(msg);
}

function csrfFromState(statePath) {
  const state = readJSON(statePath);
  const cookie = (state.cookies || []).find((c) => c.name === 'csrfToken' && String(c.domain || '').includes('volcengine.com'));
  if (!cookie || !cookie.value) {
    throw new Error(`csrfToken cookie not found in ${statePath}; refresh auth with auth-from-chrome`);
  }
  return cookie.value;
}

function responseError(action, status, body) {
  const text = typeof body === 'string' ? body : JSON.stringify(body);
  return new Error(`${action} -> HTTP ${status}: ${text.slice(0, 800)}`);
}

async function postAction(ctx, statePath, action, data) {
  const maxAttempts = Number(process.env.ARK_FETCH_RETRIES || 4);
  let lastErr;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const resp = await ctx.request.post(`${API_BASE}/${action}`, {
        headers: {
          'content-type': 'application/json',
          'x-csrf-token': csrfFromState(statePath),
          referer: ARK_REFERER,
        },
        data,
        timeout: 120000,
      });
      const status = resp.status();
      let body;
      try {
        body = await resp.json();
      } catch {
        body = await resp.text();
      }
      if (status >= 400) throw responseError(action, status, body);
      if (body && body.ResponseMetadata && body.ResponseMetadata.Error) {
        throw new Error(`${action}: ${body.ResponseMetadata.Error.Code}: ${body.ResponseMetadata.Error.Message}`);
      }
      if (body && body.code && body.code !== 0) {
        throw new Error(`${action}: code=${body.code} message=${body.message || ''}`);
      }
      return body.data;
    } catch (err) {
      lastErr = err;
      if (attempt >= maxAttempts || !isTransientApiError(err)) break;
      const waitMs = Math.min(60000, 3000 * attempt * attempt);
      console.warn(`   [retry] ${action} attempt ${attempt}/${maxAttempts}: ${err.message}; wait ${waitMs}ms`);
      await sleep(waitMs);
    }
  }
  throw lastErr;
}

async function downloadTo(url, outPath, keepExisting) {
  if (keepExisting && fs.existsSync(outPath) && fs.statSync(outPath).size > 0) {
    console.log(`   [keep] ${rel(outPath)} (${fs.statSync(outPath).size} bytes)`);
    return { path: outPath, size: fs.statSync(outPath).size, skipped: true };
  }
  ensureDir(path.dirname(outPath));
  const tmp = `${outPath}.part`;
  const resp = await fetch(url);
  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    throw new Error(`GET ${url} -> ${resp.status} ${text.slice(0, 500)}`);
  }
  await pipeline(Readable.fromWeb(resp.body), fs.createWriteStream(tmp));
  fs.renameSync(tmp, outPath);
  const size = fs.statSync(outPath).size;
  console.log(`   [download] ${rel(outPath)} (${size} bytes)`);
  return { path: outPath, size, skipped: false };
}

function sha256File(file) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const stream = fs.createReadStream(file);
    stream.on('error', reject);
    stream.on('data', (chunk) => hash.update(chunk));
    stream.on('end', () => resolve(hash.digest('hex')));
  });
}

function taskUploadField(task) {
  if (task && Object.prototype.hasOwnProperty.call(task, 'attachments')) {
    if (!Array.isArray(task.attachments)) throw new Error('CaseBffV1CrowdtestTaskGet.attachments is not an array');
    return { field: 'attachments', items: task.attachments };
  }
  if (task && task.task && Object.prototype.hasOwnProperty.call(task.task, 'attachments')) {
    if (!Array.isArray(task.task.attachments)) throw new Error('CaseBffV1CrowdtestTaskGet.task.attachments is not an array');
    return { field: 'task.attachments', items: task.task.attachments };
  }
  throw new Error('CaseBffV1CrowdtestTaskGet did not report an attachments field; cannot verify 首轮 Prompt / 上传产物');
}

async function collectTaskUploads(task, taskDir, opts) {
  const uploadField = taskUploadField(task);
  const uploadsDir = path.join(taskDir, 'task_uploads');
  const manifestPath = path.join(taskDir, 'task_uploads.json');
  let previousManifest = null;
  if (fs.existsSync(manifestPath)) {
    try {
      previousManifest = readJSON(manifestPath);
    } catch {
      previousManifest = null;
    }
  }
  ensureDir(uploadsDir);
  const manifest = {
    schema_version: 1,
    source: `CaseBffV1CrowdtestTaskGet.${uploadField.field}`,
    source_label: '首轮 Prompt / 上传产物',
    reported_count: uploadField.items.length,
    status: 'downloading',
    items: [],
    started_at: new Date().toISOString(),
  };
  writeJSON(manifestPath, manifest);
  console.log(`==> first-round task uploads: ${uploadField.items.length} item(s)`);

  try {
    for (const [index, att] of uploadField.items.entries()) {
      const url = att.downloadUrl || att.previewUrl || att.url;
      const fileName = safeUploadName(
        att.fileName || att.relativePath || att.name,
        `upload_${String(index + 1).padStart(2, '0')}.bin`,
      );
      if (!url) throw new Error(`task upload ${index + 1} (${fileName}) has no download URL`);
      const localName = `${String(index + 1).padStart(2, '0')}_${fileName}`;
      const outPath = path.join(uploadsDir, localName);
      const expectedSize = Number(att.sizeBytes || att.fileSize || att.size || 0);
      const previous = ((previousManifest && previousManifest.items) || []).find((item) => (
        Number(item.index) === index + 1
        && item.local_path === path.posix.join('task_uploads', localName)
        && String(item.object_key || '') === String(att.objectKey || '')
        && String(item.etag || '') === String(att.etag || '')
        && Number(item.expected_size_bytes || 0) === expectedSize
      ));
      const downloaded = await downloadTo(url, outPath, Boolean(opts.keepExisting && previous));
      if (expectedSize > 0 && downloaded.size !== expectedSize) {
        throw new Error(`task upload size mismatch for ${fileName}: expected ${expectedSize}, got ${downloaded.size}`);
      }
      const digest = await sha256File(outPath);
      if (downloaded.skipped && previous.sha256 && previous.sha256 !== digest) {
        throw new Error(`cached task upload checksum changed for ${fileName}; rerun without --keep-existing`);
      }
      manifest.items.push({
        index: index + 1,
        id: att.id == null ? null : att.id,
        file_name: fileName,
        original_relative_path: att.relativePath || '',
        local_path: path.posix.join('task_uploads', localName),
        content_type: att.contentType || '',
        source: att.source || '',
        object_key: att.objectKey || '',
        etag: att.etag || '',
        expected_size_bytes: expectedSize || null,
        size_bytes: downloaded.size,
        sha256: digest,
        reused_existing: Boolean(downloaded.skipped),
      });
      writeJSON(manifestPath, manifest);
    }
    manifest.status = 'downloaded';
    manifest.downloaded_at = new Date().toISOString();
    writeJSON(manifestPath, manifest);
  } catch (err) {
    manifest.status = 'download_failed';
    manifest.error = String((err && err.message) || err);
    manifest.failed_at = new Date().toISOString();
    writeJSON(manifestPath, manifest);
    throw err;
  }

  const status = runPythonQc('inspect_task_uploads.py', ['--task-dir', taskDir]);
  if (status !== 0) {
    throw new Error(`first-round task upload inspection failed (exit ${status}); stop before prompt/product review`);
  }
  const completed = readJSON(manifestPath);
  if (completed.status !== 'complete' || Number(completed.reported_count) !== completed.items.length) {
    throw new Error('first-round task upload manifest is incomplete; stop before prompt/product review');
  }
  console.log(
    `==> first-round task uploads complete: ${completed.items.length} file(s), `
    + `${completed.text_material_count || 0} text path(s), `
    + `${completed.unique_text_material_count || 0} unique text material(s)`,
  );
  return completed;
}

function msToISO(ms) {
  if (!ms) return '';
  try {
    return new Date(ms).toISOString();
  } catch {
    return '';
  }
}

function truncateForMarkdown(value, limit = 50000) {
  const s = value == null ? '' : String(value);
  if (s.length <= limit) return s;
  return `${s.slice(0, limit)}\n\n[truncated ${s.length - limit} chars; see raw JSON for full data]`;
}

function renderTrajectoryMarkdown(run, sessionList, detailsBySession) {
  const lines = [];
  lines.push(`# Session trajectory for run ${run.modelRun.taskModelRunId}`);
  lines.push('');
  lines.push(`- task: ${run.task.id} ${run.task.title}`);
  lines.push(`- model: ${run.modelRun.realName} (${run.modelRun.codeName})`);
  lines.push(`- framework: ${run.task.framework}`);
  lines.push(`- sessions: ${sessionList.totalCount || (sessionList.items || []).length || 0}`);
  lines.push('');

  for (const [index, item] of (sessionList.items || []).entries()) {
    const detail = detailsBySession[item.sessionId] || {};
    const traces = detail.sessionTraces || [];
    lines.push(`## Session ${index + 1}`);
    lines.push('');
    lines.push(`- sessionId: ${item.sessionId}`);
    lines.push(`- userId: ${item.userId || ''}`);
    lines.push(`- time: ${msToISO(item.sessionStartTime)} -> ${msToISO(item.sessionEndTime)}`);
    lines.push(`- traces: ${item.traceCount || traces.length}`);
    lines.push(`- tokens: input=${item.inputTokens || 0}, output=${item.outputTokens || 0}, total=${item.totalTokens || 0}`);
    lines.push('');

    for (const [tIndex, trace] of traces.entries()) {
      lines.push(`### Trace ${tIndex + 1}: ${trace.traceId || ''}`);
      lines.push('');
      lines.push(`- start: ${msToISO(trace.startTime)}`);
      lines.push(`- durationMs: ${trace.duration || ''}`);
      lines.push(`- tokens: input=${trace.inputTokens || 0}, output=${trace.outputTokens || 0}, total=${trace.totalTokens || 0}`);
      if (trace.input) {
        lines.push('');
        lines.push('#### Input');
        lines.push('');
        lines.push('```text');
        lines.push(truncateForMarkdown(trace.input));
        lines.push('```');
      }
      if (trace.output) {
        lines.push('');
        lines.push('#### Output');
        lines.push('');
        lines.push('```text');
        lines.push(truncateForMarkdown(trace.output));
        lines.push('```');
      }
      for (const key of ['toolCalls', 'tool_calls', 'spans', 'events', 'messages']) {
        if (Array.isArray(trace[key]) && trace[key].length) {
          lines.push('');
          lines.push(`#### ${key}`);
          lines.push('');
          lines.push('```json');
          lines.push(truncateForMarkdown(JSON.stringify(trace[key], null, 2)));
          lines.push('```');
        }
      }
      lines.push('');
    }
  }
  return `${lines.join('\n').trim()}\n`;
}

function latestDownloadItems(latestList) {
  if (!latestList) return [];
  if (Array.isArray(latestList)) return latestList;
  return latestList.jobs || latestList.items || latestList.result || latestList.list || latestList.records || [];
}

function latestItemForRun(latestList, runId) {
  return latestDownloadItems(latestList).find((item) => (
    String(item.taskModelRunId || item.modelRunId || (item.modelRun && item.modelRun.taskModelRunId) || '') === String(runId)
  )) || null;
}

async function fetchLatestDownloadList(ctx, statePath, taskId, runIds, taskDir) {
  const data = {
    taskId: Number(taskId),
    taskModelRunIds: runIds.map((id) => Number(id)),
  };
  const result = await postAction(ctx, statePath, DOWNLOAD_LIST_ACTION, data);
  writeJSON(path.join(taskDir, 'download_list.json'), {
    action: DOWNLOAD_LIST_ACTION,
    data,
    result,
    saved_at: new Date().toISOString(),
  });
  const items = latestDownloadItems(result);
  console.log(`==> download list: ${items.length} item(s)`);
  for (const item of items) {
    console.log(`   run ${item.taskModelRunId || item.modelRunId} status=${item.status || item.workspaceStatus || ''} ready=${item.downloadReady} file=${item.fileName || ''}`);
  }
  return result;
}

async function downloadEvaluationAttachments(evaluation, runDir, opts) {
  const attachments = (evaluation && evaluation.evaluation && evaluation.evaluation.attachments) || [];
  if (!attachments.length) return;
  const outDir = path.join(runDir, 'evaluation_attachments');
  ensureDir(outDir);
  writeJSON(path.join(outDir, 'attachments.json'), attachments);
  for (const [index, att] of attachments.entries()) {
    const url = att.previewUrl || att.downloadUrl || att.url;
    if (!url) continue;
    const ext = path.extname(att.fileName || '') || '.bin';
    const name = sanitize(`${String(index).padStart(2, '0')}_${att.fileName || att.id || 'file'}`) || `file${index}${ext}`;
    await downloadTo(url, path.join(outDir, name), opts.keepExisting);
  }
}

async function fetchWorkspaceZip(ctx, statePath, run, runDir, opts) {
  const runId = run.modelRun.taskModelRunId;
  const workspaceDir = path.join(runDir, 'workspace');
  ensureDir(workspaceDir);
  const latestItem = latestItemForRun(opts.latestDownloadList, runId);
  if (latestItem) {
    writeJSON(path.join(workspaceDir, 'latest_list_item.json'), latestItem);
  }

  const expired = Boolean(
    latestItem && latestItem.expiresAt && Number(latestItem.expiresAt) < Date.now(),
  );
  let job = expired ? null : latestItem;
  const latestUrl = !expired && latestItem && (latestItem.downloadUrl || latestItem.url || latestItem.packageUrl);
  if (latestUrl) {
    const fileName = sanitize(latestItem.fileName || `${run.task.id}-${runId}-${run.modelRun.codeName}.zip`);
    return downloadTo(latestUrl, path.join(workspaceDir, fileName), opts.keepExisting);
  }

  if (!job || !job.jobId || latestItem && latestItem.downloadReady === false && !latestItem.jobId) {
    if (expired) {
      console.log(`   [workspace] run ${runId} latest package expired, starting a new job`);
    }
    job = await postAction(ctx, statePath, 'CaseBffV1CrowdtestTaskModelWorkspaceDownloadStart', { taskModelRunId: runId });
  }
  const started = Date.now();
  while (job && !job.downloadReady && !['completed', 'failed'].includes(job.status)) {
    if (Date.now() - started > opts.timeoutMs) {
      throw new Error(`workspace download timed out for run ${runId}, job ${job.jobId}`);
    }
    await new Promise((resolve) => setTimeout(resolve, opts.pollMs));
    job = await postAction(ctx, statePath, 'CaseBffV1CrowdtestTaskModelWorkspaceDownloadStatus', {
      taskModelRunId: runId,
      jobId: job.jobId,
    });
    console.log(`   [workspace] run ${runId} ${job.status}/${job.phase} ${job.progressPct || 0}%`);
  }
  if (!job || !job.downloadReady) {
    throw new Error(`workspace package failed for run ${runId}: ${(job && job.errorType) || ''} ${(job && job.errorMessage) || ''}`);
  }
  writeJSON(path.join(workspaceDir, 'download_job.json'), job);
  const got = await postAction(ctx, statePath, 'CaseBffV1CrowdtestTaskModelWorkspaceDownloadGet', {
    taskModelRunId: runId,
    jobId: job.jobId,
  });
  writeJSON(path.join(workspaceDir, 'download_url.json'), { ...got, saved_at: new Date().toISOString() });
  const fileName = sanitize(job.fileName || `${run.task.id}-${runId}-${run.modelRun.codeName}.zip`);
  return downloadTo(got.downloadUrl, path.join(workspaceDir, fileName), opts.keepExisting);
}

async function fetchDownloadList(ctx, statePath, run, runDir, opts) {
  const runId = run.modelRun.taskModelRunId;
  const outPath = path.join(runDir, 'download_list.json');
  const latestItem = latestItemForRun(opts.latestDownloadList, runId);
  if (latestItem) {
    writeJSON(outPath, { action: DOWNLOAD_LIST_ACTION, item: latestItem, saved_at: new Date().toISOString() });
    console.log(`   [download-list] run ${runId} ${latestItem.status || latestItem.phase || 'ok'}`);
    return latestItem;
  }
  const result = await postAction(ctx, statePath, DOWNLOAD_LIST_ACTION, {
    taskId: Number(run.task && run.task.id),
    taskModelRunIds: [Number(runId)],
  });
  writeJSON(outPath, { action: DOWNLOAD_LIST_ACTION, result, saved_at: new Date().toISOString() });
  console.log(`   [download-list] ${DOWNLOAD_LIST_ACTION} ok`);
  return result;
}

async function discoverDownloadList(opts) {
  const cfg = loadG1Config();
  const projectId = Number(opts.project || (cfg && cfg.project_id) || 281);
  const taskId = opts['task-id'] || opts['sheet-task-id'];
  if (!taskId) usage();
  const statePath = path.resolve(opts.state || DEFAULT_STATE);
  if (!fs.existsSync(statePath)) {
    throw new Error(`state file not found: ${statePath}; run auth-from-chrome first`);
  }
  const outDir = path.resolve(
    opts['tasks-dir'] || path.join(REPO_ROOT, 'tasks'),
    String(taskId),
    opts['output-subdir'] || 'ark_g1',
  );
  ensureDir(outDir);

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ storageState: statePath });
  const page = await ctx.newPage();
  const calls = [];
  page.on('request', (req) => {
    const url = req.url();
    if (!url.includes('/api/top/ark/') && !url.includes('tos-cn-beijing') && !url.includes('download')) return;
    const action = url.split('/').pop().split('?')[0];
    calls.push({
      action,
      url: url.slice(0, 300),
      method: req.method(),
      postData: req.postData(),
    });
  });

  const url = `https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/myprojects/${projectId}/task/${taskId}`;
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await sleep(4000);
  await page.screenshot({ path: path.join(outDir, '_discover_task.png'), fullPage: true });

  const labels = await page.evaluate(() => {
    const nodes = Array.from(document.querySelectorAll('button, a, [role="button"], span, div'));
    return nodes
      .map((el) => ({
        tag: el.tagName,
        text: (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80),
        cls: String(el.className || '').slice(0, 120),
      }))
      .filter((n) => n.text && /下载|模型运行|workspace|Workspace/i.test(n.text))
      .slice(0, 80);
  });
  console.log(`==> download-related labels: ${labels.length}`);
  for (const item of labels) console.log(`   [${item.tag}] ${item.text}`);

  const locators = page.locator('text=下载列表');
  const count = await locators.count();
  console.log(`==> locator 下载列表 count=${count}`);
  const clickResults = [];
  for (let i = 0; i < Math.min(count, 5); i++) {
    const before = calls.length;
    try {
      await locators.nth(i).click({ timeout: 5000 });
      await sleep(2500);
      await page.screenshot({ path: path.join(outDir, `_discover_download_${i}.png`) });
      clickResults.push({ index: i, ok: true, newCalls: calls.length - before });
      console.log(`   clicked 下载列表 #${i}, new network calls=${calls.length - before}`);
      await page.keyboard.press('Escape').catch(() => {});
      await sleep(500);
    } catch (err) {
      clickResults.push({ index: i, ok: false, error: String((err && err.message) || err).slice(0, 200) });
    }
  }

  const actions = [...new Set(calls.map((c) => c.action).filter(Boolean))];
  writeJSON(path.join(outDir, 'download_list_discover.json'), {
    url,
    labels,
    clickResults,
    actions,
    calls,
    saved_at: new Date().toISOString(),
  });
  console.log(`==> after click APIs: ${actions.join(', ') || '(none)'}`);
  console.log(`==> wrote ${rel(path.join(outDir, 'download_list_discover.json'))}`);
  await browser.close();
}

async function probeTaskDetailNetwork(ctx, projectId, taskId, taskDir) {
  const page = await ctx.newPage();
  const calls = [];
  page.on('request', (req) => {
    const url = req.url();
    if (!url.includes('/api/top/ark/')) return;
    const action = url.split('/').pop().split('?')[0];
    calls.push({
      action,
      method: req.method(),
      postData: req.postData(),
    });
  });
  const urls = [
    `https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/myprojects/${projectId}/task/${taskId}`,
    `https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/projects/${projectId}?tab=review`,
  ];
  try {
    await page.goto(urls[0], { waitUntil: 'domcontentloaded', timeout: 60000 });
    await sleep(4000);
  } catch (err) {
    calls.push({ error: String((err && err.message) || err), url: urls[0] });
    try {
      await page.goto(urls[1], { waitUntil: 'domcontentloaded', timeout: 60000 });
      await sleep(3000);
    } catch (err2) {
      calls.push({ error: String((err2 && err2.message) || err2), url: urls[1] });
    }
  }
  const actions = [...new Set(calls.map((c) => c.action).filter(Boolean))];
  writeJSON(path.join(taskDir, 'task_detail_network.json'), {
    urls,
    actions,
    calls,
    saved_at: new Date().toISOString(),
  });
  console.log(`==> task-detail APIs: ${actions.join(', ') || '(none captured)'}`);
  await page.close();
  return calls;
}

async function collectOneRun(ctx, statePath, run, taskDir, opts) {
  const runId = run.modelRun.taskModelRunId;
  const tag = `${runId}__${sanitize(run.modelRun.codeName)}`;
  const runDir = path.join(taskDir, tag);
  ensureDir(runDir);
  console.log(`\n==> run ${runId}: ${run.modelRun.realName} (${run.modelRun.codeName})`);
  writeJSON(path.join(runDir, 'model_run.json'), run);

  const evaluationPath = path.join(runDir, 'evaluation.json');
  if (opts.keepExisting && fs.existsSync(evaluationPath)) {
    console.log(`   [keep] ${rel(evaluationPath)}`);
  } else {
    const evaluation = await postAction(ctx, statePath, 'CaseBffV1CrowdtestTaskModelEvaluationGet', { taskModelRunId: runId });
    writeJSON(evaluationPath, evaluation);
  }
  try {
    const evaluation = readJSON(evaluationPath);
    await downloadEvaluationAttachments(evaluation, runDir, opts);
  } catch (err) {
    console.warn(`   [attachments] ${err.message}`);
  }

  const auditPath = path.join(runDir, 'audit.json');
  if (opts.keepExisting && fs.existsSync(auditPath)) {
    console.log(`   [keep] ${rel(auditPath)}`);
  } else {
    const audit = await postAction(ctx, statePath, 'CaseBffV1CrowdtestTaskModelAuditGet', { taskModelRunId: runId });
    writeJSON(auditPath, audit);
  }

  const workspaceBrowserPath = path.join(runDir, 'workspace_browser.json');
  if (opts.keepExisting && fs.existsSync(workspaceBrowserPath)) {
    console.log(`   [keep] ${rel(workspaceBrowserPath)}`);
  } else {
    const workspaceBrowser = await postAction(ctx, statePath, 'CaseBffV1CrowdtestTaskModelWorkspaceBrowserGet', { taskModelRunId: runId });
    writeJSON(workspaceBrowserPath, workspaceBrowser);
  }

  if (!opts.skipTrajectory) {
    const trajDir = path.join(runDir, 'trajectory');
    ensureDir(trajDir);
    const sessionsPath = path.join(trajDir, 'sessions.json');
    let sessions;
    if (opts.keepExisting && fs.existsSync(sessionsPath)) {
      sessions = readJSON(sessionsPath);
      console.log(`   [keep] ${rel(sessionsPath)}`);
    } else {
      sessions = await postAction(ctx, statePath, 'CaseBffV1CrowdtestTaskModelByteHouseSessionListGet', { taskModelRunId: runId });
      writeJSON(sessionsPath, sessions);
    }
    const detailsBySession = {};
    for (const item of sessions.items || []) {
      const detailPath = path.join(trajDir, `${sanitize(item.sessionId)}.json`);
      let detail;
      if (opts.keepExisting && fs.existsSync(detailPath)) {
        detail = readJSON(detailPath);
        console.log(`   [keep] ${rel(detailPath)}`);
      } else {
        detail = await postAction(ctx, statePath, 'CaseBffV1CrowdtestTaskModelByteHouseSessionDetailGet', {
          taskModelRunId: runId,
          sessionId: item.sessionId,
        });
        writeJSON(detailPath, detail);
      }
      detailsBySession[item.sessionId] = detail;
      console.log(`   [trajectory] session ${item.sessionId} traces=${(detail.sessionTraces || []).length}`);
    }
    fs.writeFileSync(path.join(trajDir, 'trajectory.md'), renderTrajectoryMarkdown(run, sessions, detailsBySession));
  } else {
    console.log('   [trajectory] skipped by --skip-trajectory');
  }

  if (!opts.skipDownloadList) {
    await fetchDownloadList(ctx, statePath, run, runDir, opts);
  }

  if (!opts.skipWorkspace) {
    await fetchWorkspaceZip(ctx, statePath, run, runDir, opts);
  }
}

async function collect(opts) {
  const projectId = Number(opts.project || DEFAULT_PROJECT_ID);
  const statePath = path.resolve(opts.state || DEFAULT_STATE);
  if (!fs.existsSync(statePath)) {
    throw new Error(`state file not found: ${statePath}; run auth-from-chrome first`);
  }
  const tasksDir = path.resolve(opts['tasks-dir'] || path.join(REPO_ROOT, 'tasks'));
  const taskKeyword = opts['task-id'] ? String(opts['task-id']) : opts['task-title'];
  if (!taskKeyword) usage();
  const sheetTaskId = opts['sheet-task-id'] || opts['task-id'];
  if (!sheetTaskId) {
    throw new Error('missing --task-id or --sheet-task-id <任务ID>; 本地目录必须使用源表任务ID');
  }
  const localId = String(sheetTaskId);
  const outputSubdir = opts['output-subdir'] || DEFAULT_OUTPUT_SUBDIR;
  const taskDir = path.join(tasksDir, localId, outputSubdir);
  const g1Config = loadG1Config();
  const wantedRuns = opts.runs ? new Set(String(opts.runs).split(',').map((s) => s.trim()).filter(Boolean)) : null;
  const runOpts = {
    skipWorkspace: Boolean(opts['skip-workspace']),
    skipTrajectory: Boolean(opts['skip-trajectory']),
    skipDownloadList: Boolean(opts['skip-download-list']),
    keepExisting: Boolean(opts['keep-existing']),
    promptCheat: false,
    pollMs: Number(opts['poll-ms'] || 2500),
    timeoutMs: Number(opts['timeout-ms'] || 10 * 60 * 1000),
  };

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ storageState: statePath, acceptDownloads: true });
  try {
    const modelRunsPath = path.join(taskDir, 'model_runs.json');
    let list;
    try {
      list = await postAction(ctx, statePath, 'CaseBffV1CrowdtestTaskModelRunList', {
        projectId,
        page: 1,
        pageSize: 20,
        taskKeyword,
        visibleColumns: VISIBLE_COLUMNS,
      });
    } catch (err) {
      if (!runOpts.keepExisting || !fs.existsSync(modelRunsPath) || !isTransientApiError(err)) throw err;
      console.warn(`   [cache] model run list failed: ${err.message}; using ${rel(modelRunsPath)}`);
      list = readJSON(modelRunsPath);
    }
    let rows = list.result || [];
    if (runOpts.keepExisting) {
      const byRunId = new Map(rows.map((r) => [String(r.modelRun && r.modelRun.taskModelRunId), r]));
      for (const cached of readCachedRunRows(taskDir)) {
        const id = String(cached.modelRun && cached.modelRun.taskModelRunId);
        if (id && !byRunId.has(id)) byRunId.set(id, cached);
      }
      rows = Array.from(byRunId.values());
    }
    if (opts['task-id']) rows = rows.filter((r) => String(r.task && r.task.id) === String(opts['task-id']));
    if (opts['task-title']) {
      const exactTitleRows = rows.filter((r) => (r.task && r.task.title) === opts['task-title']);
      if (exactTitleRows.length) rows = exactTitleRows;
    }
    if (wantedRuns) rows = rows.filter((r) => wantedRuns.has(String(r.modelRun && r.modelRun.taskModelRunId)));
    if (!rows.length && wantedRuns && runOpts.keepExisting) {
      rows = readCachedRunRows(taskDir).filter((r) => wantedRuns.has(String(r.modelRun && r.modelRun.taskModelRunId)));
      if (rows.length) console.warn(`   [cache] using ${rows.length} cached model_run.json file(s)`);
    }
    if (!rows.length) throw new Error(`no model runs found for keyword: ${taskKeyword}`);

    const taskId = rows[0].task.id;
    ensureDir(taskDir);
    if (!wantedRuns || !fs.existsSync(modelRunsPath)) {
      writeJSON(modelRunsPath, { query: { projectId, taskKeyword, localId }, ...list, result: rows });
    }

    const expectedCodes = opts['expect-platform-codes']
      ? String(opts['expect-platform-codes']).split(',').map((s) => s.trim().toLowerCase()).filter(Boolean)
      : [];
    if (expectedCodes.length) {
      const got = rows.map((r) => String((r.modelRun && r.modelRun.codeName) || '').toLowerCase());
      const missing = expectedCodes.filter((code) => !got.includes(code));
      const extra = got.filter((code) => code && !expectedCodes.includes(code));
      console.log(`==> expected models: ${expectedCodes.join(', ')}`);
      console.log(`==> got models: ${got.join(', ') || '(none)'}`);
      if (missing.length || extra.length) {
        const msg = `model set mismatch missing=${missing.join(',') || '-'} extra=${extra.join(',') || '-'}`;
        if (opts['allow-partial']) console.warn(`   [warn] ${msg}`);
        else throw new Error(`${msg}; pass --allow-partial to continue`);
      }
    }

    const taskPath = path.join(taskDir, 'task.json');
    let task;
    try {
      // Task upload URLs are signed and short-lived, so always refresh task.json.
      task = await postAction(ctx, statePath, 'CaseBffV1CrowdtestTaskGet', { taskId });
      writeJSON(taskPath, task);
    } catch (err) {
      if (!runOpts.keepExisting || !fs.existsSync(taskPath) || !isTransientApiError(err)) throw err;
      console.warn(`   [cache] task detail refresh failed: ${err.message}; using ${rel(taskPath)}`);
      task = readJSON(taskPath);
    }

    // "首轮 Prompt / 上传产物" is independent from model Workspace/download-list.
    // Download and inspect it before any prompt gate or product review.
    await collectTaskUploads(task, taskDir, runOpts);

    if (scanPromptCheat(localId)) {
      console.log('==> PROMPT CHEAT: skip workspace / trajectory / download-list; do not retest products');
      runOpts.skipWorkspace = true;
      runOpts.skipTrajectory = true;
      runOpts.skipDownloadList = true;
      runOpts.promptCheat = true;
    }

    console.log(`==> task ${taskId}: ${rows[0].task.title}`);
    console.log(`==> runs: ${rows.map((r) => `${r.modelRun.taskModelRunId}/${r.modelRun.codeName}/${r.modelRun.realName}`).join(', ')}`);
    if (!opts['skip-detail-probe']) {
      await probeTaskDetailNetwork(ctx, projectId, taskId, taskDir);
    }
    if (!runOpts.skipDownloadList) {
      runOpts.latestDownloadList = await fetchLatestDownloadList(
        ctx,
        statePath,
        taskId,
        rows.map((r) => r.modelRun.taskModelRunId),
        taskDir,
      );
    }
    const modelMap = {};
    for (const run of rows) {
      const sheetModel = g1SheetModel(run.modelRun.codeName, g1Config);
      if (sheetModel) {
        const meta = ((g1Config && g1Config.models) || []).find((m) => m.sheet === sheetModel) || {};
        modelMap[sheetModel] = {
          code: meta.code || '',
          platform: run.modelRun.codeName,
          real_name: run.modelRun.realName,
          task_model_run_id: run.modelRun.taskModelRunId,
          audit_url: `https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/projects/${projectId}/review/${run.modelRun.taskModelRunId}?mode=audit`,
        };
      }
      await collectOneRun(ctx, statePath, run, taskDir, runOpts);
    }
    writeJSON(path.join(tasksDir, localId, 'model_map.json'), {
      period: (g1Config && g1Config.period) || '',
      project_id: projectId,
      sheet_columns: Object.keys(modelMap),
      prompt_cheat: Boolean(runOpts.promptCheat),
      models: modelMap,
      generated_at: new Date().toISOString(),
    });
    if (runOpts.promptCheat) {
      screenshotPromptCheat(localId);
    }
    writeJSON(path.join(taskDir, '_summary.json'), {
      sheet_task_id: localId,
      ark_task_id: taskId,
      project_id: projectId,
      title: rows[0].task.title,
      runs: rows.map((r) => ({
        task_model_run_id: r.modelRun.taskModelRunId,
        code_name: r.modelRun.codeName,
        real_name: r.modelRun.realName,
        sheet_model: g1SheetModel(r.modelRun.codeName, g1Config),
        path: rel(path.join(taskDir, `${r.modelRun.taskModelRunId}__${sanitize(r.modelRun.codeName)}`)),
      })),
      generated_at: new Date().toISOString(),
    });
    console.log(`\n==> wrote ${rel(taskDir)}`);
  } finally {
    await browser.close();
  }
}

function parseProjectSpec(value) {
  const raw = String(value || '230-270').trim();
  const ids = [];
  for (const part of raw.split(',')) {
    const s = part.trim();
    if (!s) continue;
    const range = s.match(/^(\d+)-(\d+)$/);
    if (range) {
      const start = Number(range[1]);
      const end = Number(range[2]);
      const step = start <= end ? 1 : -1;
      for (let id = start; step > 0 ? id <= end : id >= end; id += step) ids.push(id);
    } else {
      ids.push(Number(s));
    }
  }
  return [...new Set(ids.filter((id) => Number.isFinite(id)))];
}

async function findProject(opts) {
  const statePath = path.resolve(opts.state || DEFAULT_STATE);
  if (!fs.existsSync(statePath)) {
    throw new Error(`state file not found: ${statePath}; run auth-from-chrome first`);
  }
  const taskKeyword = opts['task-id'] ? String(opts['task-id']) : opts['task-title'];
  if (!taskKeyword) usage();
  const projectIds = parseProjectSpec(opts.projects);
  const pageSize = Number(opts['page-size'] || 20);
  const outDir = path.resolve(opts['tasks-dir'] || path.join(REPO_ROOT, 'tasks'));
  ensureDir(outDir);

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ storageState: statePath, acceptDownloads: true });
  const attempts = [];
  const matches = [];
  try {
    for (const projectId of projectIds) {
      try {
        const list = await postAction(ctx, statePath, 'CaseBffV1CrowdtestTaskModelRunList', {
          projectId,
          page: 1,
          pageSize,
          taskKeyword,
          visibleColumns: VISIBLE_COLUMNS,
        });
        let rows = list.result || [];
        if (opts['task-id']) rows = rows.filter((r) => String(r.task && r.task.id) === String(opts['task-id']));
        if (opts['task-title']) {
          const exactTitleRows = rows.filter((r) => (r.task && r.task.title) === opts['task-title']);
          if (exactTitleRows.length) rows = exactTitleRows;
        }
        attempts.push({ projectId, total: list.total || list.totalCount || rows.length || 0, returned: rows.length });
        if (rows.length) {
          const found = rows.map((r) => ({
            projectId,
            taskId: r.task && r.task.id,
            taskTitle: r.task && r.task.title,
            taskModelRunId: r.modelRun && r.modelRun.taskModelRunId,
            codeName: r.modelRun && r.modelRun.codeName,
            realName: r.modelRun && r.modelRun.realName,
          }));
          matches.push(...found);
          console.log(`[match] project=${projectId} rows=${rows.length} task=${found[0].taskId} ${found[0].taskTitle}`);
        } else {
          console.log(`[empty] project=${projectId}`);
        }
      } catch (e) {
        attempts.push({ projectId, error: e.message });
        console.log(`[error] project=${projectId} ${e.message.slice(0, 160)}`);
      }
    }
  } finally {
    await browser.close();
  }
  const outPath = path.join(outDir, `_38_project_probe_${sanitize(taskKeyword)}.json`);
  writeJSON(outPath, { query: { taskKeyword, projectIds }, matches, attempts, generated_at: new Date().toISOString() });
  console.log(`==> wrote ${rel(outPath)}`);
  if (!matches.length) throw new Error(`no project matched keyword: ${taskKeyword}`);
}

function runPythonQc(scriptName, args) {
  const py = pythonCmd();
  const script = path.join(HERE, scriptName);
  const r = spawnSync(py, [script, ...args], {
    cwd: REPO_ROOT,
    encoding: 'utf8',
  });
  if (r.stdout) process.stdout.write(r.stdout);
  if (r.stderr) process.stderr.write(r.stderr);
  return r.status == null ? 1 : r.status;
}

function scanPromptCheat(taskId) {
  try {
    const status = runPythonQc('check_prompt_cheat.py', [String(taskId), '--scan-only']);
    if (status === 10) return true;
    if (status !== 0) {
      console.warn(`   [prompt-cheat] scan exit ${status}; continue collect without skipping products`);
    }
    return false;
  } catch (err) {
    console.warn(`   [prompt-cheat] scan skipped: ${err.message}`);
    return false;
  }
}

function screenshotPromptCheat(taskId) {
  try {
    const status = runPythonQc('check_prompt_cheat.py', [String(taskId)]);
    if (status !== 0 && status !== 10) {
      console.warn(`   [prompt-cheat] screenshot exit ${status}`);
    }
  } catch (err) {
    console.warn(`   [prompt-cheat] screenshot skipped: ${err.message}`);
  }
}

function run(command, args, options = {}) {
  const r = spawnSync(command, args, {
    encoding: 'utf8',
    stdio: options.stdio || 'pipe',
    env: options.env || process.env,
  });
  if (r.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed (${r.status})\n${r.stdout || ''}\n${r.stderr || ''}`);
  }
  return r.stdout;
}

function pythonCmd() {
  if (process.env.QC_PYTHON) return process.env.QC_PYTHON;
  const cmds = process.platform === 'win32' ? ['python', 'python3'] : ['python3', 'python'];
  for (const cmd of cmds) {
    const r = spawnSync(cmd, ['-c', 'import sys; print(sys.version_info[0])'], { encoding: 'utf8' });
    if (r.status === 0 && String(r.stdout || '').trim().startsWith('3')) return cmd;
  }
  throw new Error('Python 3 not found (tried python3/python). Set QC_PYTHON to the interpreter path.');
}

function defaultChromeUserDataDir() {
  const home = os.homedir();
  if (process.platform === 'darwin') {
    const candidates = [
      path.join(home, 'Library', 'Application Support', 'Google', 'Chrome'),
      path.join(home, 'Library', 'Application Support', 'Chromium'),
    ];
    return candidates.find((p) => fs.existsSync(p)) || candidates[0];
  }
  if (process.platform === 'linux') {
    const candidates = [
      path.join(home, '.config', 'google-chrome'),
      path.join(home, '.config', 'chromium'),
    ];
    return candidates.find((p) => fs.existsSync(p)) || candidates[0];
  }
  return path.join(home, 'AppData', 'Local', 'Google', 'Chrome', 'User Data');
}

function copyChromeCookieFiles(userDataDir, profile, tempDir) {
  const profileDir = path.join(userDataDir, profile);
  const cookieDirs = [path.join(profileDir, 'Network'), profileDir];
  let copied = false;
  for (const dir of cookieDirs) {
    const src = path.join(dir, 'Cookies');
    if (!fs.existsSync(src)) continue;
    for (const name of ['Cookies', 'Cookies-journal', 'Cookies-wal']) {
      const from = path.join(dir, name);
      if (fs.existsSync(from)) fs.copyFileSync(from, path.join(tempDir, name));
    }
    copied = true;
    break;
  }
  const localState = path.join(userDataDir, 'Local State');
  if (!fs.existsSync(localState)) {
    throw new Error(`Chrome Local State not found: ${localState}`);
  }
  fs.copyFileSync(localState, path.join(tempDir, 'Local State'));
  if (!copied) {
    throw new Error(`Chrome Cookies DB not found under ${profileDir}`);
  }
  return {
    cookieCopy: path.join(tempDir, 'Cookies'),
    localStateCopy: path.join(tempDir, 'Local State'),
  };
}

function chromeSafeStoragePassword(userDataDir) {
  const isChromium = /chromium/i.test(userDataDir);
  if (process.platform === 'darwin') {
    const service = isChromium ? 'Chromium Safe Storage' : 'Chrome Safe Storage';
    const account = isChromium ? 'Chromium' : 'Chrome';
    return run('security', ['find-generic-password', '-w', '-s', service, '-a', account]).trim();
  }
  if (process.platform === 'linux') {
    try {
      const app = isChromium ? 'chromium' : 'chrome';
      return run('secret-tool', ['lookup', 'application', app]).trim();
    } catch {
      return 'peanuts';
    }
  }
  return '';
}

const COOKIE_EXPORT_PY = String.raw`
import base64, hashlib, json, os, sqlite3, sys
from hashlib import pbkdf2_hmac

cookies_db, local_state, out, platform_name = sys.argv[1:5]
ls = json.load(open(local_state, encoding='utf-8'))

def chrome_time_to_unix(t):
    return -1 if not t else max(0, int(t / 1000000 - 11644473600))

def same_site(n):
    if n == 2:
        return 'Strict'
    if n == 0:
        return 'None'
    return 'Lax'

def decrypt_windows(host, value, encrypted, key):
    import win32crypt
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if value:
        return value
    if not encrypted:
        return ''
    if encrypted.startswith(b'v10') or encrypted.startswith(b'v11'):
        plain = AESGCM(key).decrypt(encrypted[3:15], encrypted[15:], None)
        digest = hashlib.sha256(host.encode()).digest()
        if plain.startswith(digest):
            plain = plain[32:]
        return plain.decode('utf-8', errors='replace')
    return win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1].decode('utf-8', errors='replace')

def decrypt_unix(host, value, encrypted, key):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    if value:
        return value
    if not encrypted:
        return ''
    if encrypted.startswith(b'v20'):
        raise ValueError('v20 app-bound cookie')
    if not (encrypted.startswith(b'v10') or encrypted.startswith(b'v11')):
        return ''
    iv = b' ' * 16
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    plain = decryptor.update(encrypted[3:]) + decryptor.finalize()
    pad = plain[-1]
    if isinstance(pad, str):
        pad = ord(pad)
    if 1 <= pad <= 16:
        plain = plain[:-pad]
    digest = hashlib.sha256(host.encode()).digest()
    if plain.startswith(digest):
        plain = plain[32:]
    return plain.decode('utf-8', errors='replace')

if platform_name == 'win32':
    import win32crypt
    enc_key = base64.b64decode(ls['os_crypt']['encrypted_key'])
    if enc_key.startswith(b'DPAPI'):
        enc_key = enc_key[5:]
    key = win32crypt.CryptUnprotectData(enc_key, None, None, None, 0)[1]
    decrypt = lambda host, value, encrypted: decrypt_windows(host, value, encrypted, key)
else:
    password = os.environ.get('CHROME_SAFE_STORAGE_PASSWORD') or 'peanuts'
    rounds = 1003 if platform_name == 'darwin' else 1
    key = pbkdf2_hmac('sha1', password.encode('utf-8'), b'saltysalt', rounds, dklen=16)
    decrypt = lambda host, value, encrypted: decrypt_unix(host, value, encrypted, key)

con = sqlite3.connect(cookies_db)
con.row_factory = sqlite3.Row
rows = con.execute("""
select host_key,name,value,encrypted_value,path,expires_utc,is_secure,is_httponly,samesite
from cookies
where host_key like '%volcengine.com'
   or host_key like 'ark.volcengine.com'
   or host_key like 'console.volcengine.com'
   or host_key like 'signin.volcengine.com'
""").fetchall()
cookies = []
for r in rows:
    try:
        val = decrypt(r['host_key'], r['value'], r['encrypted_value'])
    except Exception:
        continue
    if not val:
        continue
    cookies.append({
        'name': r['name'],
        'value': val,
        'domain': r['host_key'],
        'path': r['path'] or '/',
        'expires': chrome_time_to_unix(r['expires_utc']),
        'httpOnly': bool(r['is_httponly']),
        'secure': bool(r['is_secure']),
        'sameSite': same_site(r['samesite']),
    })
os.makedirs(os.path.dirname(out), exist_ok=True)
json.dump({'cookies': cookies, 'origins': []}, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(len(cookies))
`;

function exportCookiesWithPython(cookieCopy, localStateCopy, statePath, extraEnv = {}) {
  const pyFile = path.join(path.dirname(cookieCopy), 'export_state.py');
  fs.writeFileSync(pyFile, COOKIE_EXPORT_PY);
  const env = { ...process.env, ...extraEnv };
  const count = run(pythonCmd(), [pyFile, cookieCopy, localStateCopy, statePath, process.platform], { env }).trim();
  csrfFromState(statePath);
  return count;
}

function authFromChromeWindows(opts) {
  const statePath = path.resolve(opts.state || DEFAULT_STATE);
  const profile = opts.profile || 'Default';
  const userDataDir = opts['chrome-user-data-dir'] ||
    path.join(os.homedir(), 'AppData', 'Local', 'Google', 'Chrome', 'User Data');
  const resolvedUserDataDir = path.resolve(userDataDir);
  const driveMatch = resolvedUserDataDir.match(/^([A-Za-z]):\\(.*)$/);
  if (!driveMatch) {
    throw new Error(`unsupported Chrome user data dir for VSS copy: ${resolvedUserDataDir}`);
  }
  const volume = `${driveMatch[1].toUpperCase()}:\\`;
  const shadowSuffix = driveMatch[2];
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ark38-chrome-'));
  const cookieCopy = path.join(tempDir, 'Cookies');
  const localStateCopy = path.join(tempDir, 'Local State');
  let shadowId = null;
  try {
    const ps = `
$ErrorActionPreference='Stop'
$r = Invoke-CimMethod -ClassName Win32_ShadowCopy -MethodName Create -Arguments @{Volume='${volume.replace(/'/g, "''")}'; Context='ClientAccessible'}
$id = $r.ShadowID
$shadow = Get-CimInstance Win32_ShadowCopy | Where-Object { $_.ID -eq $id }
$base = $shadow.DeviceObject + '\\${shadowSuffix}'
Copy-Item -LiteralPath ($base + '\\${profile.replace(/'/g, "''")}\\Network\\Cookies') -Destination '${cookieCopy.replace(/'/g, "''")}' -Force
Copy-Item -LiteralPath ($base + '\\Local State') -Destination '${localStateCopy.replace(/'/g, "''")}' -Force
Write-Output $id
`;
    shadowId = run('powershell', ['-NoProfile', '-Command', ps]).trim().split(/\r?\n/).pop();
    const count = exportCookiesWithPython(cookieCopy, localStateCopy, statePath);
    console.log(`==> wrote ${rel(statePath)} (${count} cookies)`);
  } finally {
    if (shadowId) {
      spawnSync('powershell', ['-NoProfile', '-Command', `Get-CimInstance Win32_ShadowCopy | Where-Object { $_.ID -eq '${shadowId}' } | Remove-CimInstance`], { stdio: 'ignore' });
    }
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

function authFromChromeUnix(opts) {
  const statePath = path.resolve(opts.state || DEFAULT_STATE);
  const profile = opts.profile || 'Default';
  const userDataDir = path.resolve(opts['chrome-user-data-dir'] || defaultChromeUserDataDir());
  if (!fs.existsSync(userDataDir)) {
    throw new Error(`Chrome user data dir not found: ${userDataDir}`);
  }
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ark38-chrome-'));
  try {
    const { cookieCopy, localStateCopy } = copyChromeCookieFiles(userDataDir, profile, tempDir);
    const password = chromeSafeStoragePassword(userDataDir);
    const count = exportCookiesWithPython(cookieCopy, localStateCopy, statePath, {
      CHROME_SAFE_STORAGE_PASSWORD: password,
    });
    console.log(`==> wrote ${rel(statePath)} (${count} cookies)`);
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

async function authLogin(opts) {
  const statePath = path.resolve(opts.state || DEFAULT_STATE);
  const loginUrl = opts.url
    || 'https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/projects/256?tab=review';
  const timeoutMs = Number(opts.timeout || 300000);
  ensureDir(path.dirname(statePath));
  let browser;
  try {
    browser = await chromium.launch({ headless: false, channel: 'chrome' });
  } catch {
    browser = await chromium.launch({ headless: false });
  }
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto(loginUrl, { waitUntil: 'domcontentloaded', timeout: 120000 });
  console.log('==> waiting for volcengine login in the opened browser window');
  console.log('    sign in, then leave the window open until csrfToken is captured');
  const started = Date.now();
  try {
    while (Date.now() - started < timeoutMs) {
      const cookies = await ctx.cookies();
      const csrf = cookies.find((c) => c.name === 'csrfToken' && String(c.domain || '').includes('volcengine.com'));
      if (csrf && csrf.value) {
        await ctx.storageState({ path: statePath });
        csrfFromState(statePath);
        console.log(`==> wrote ${rel(statePath)} (${cookies.length} cookies)`);
        return;
      }
      await sleep(1500);
    }
    throw new Error(`timed out waiting for csrfToken after ${timeoutMs}ms; re-run auth-login after signing in`);
  } finally {
    await browser.close();
  }
}

async function discoverAuditForm(opts) {
  const cfg = loadG1Config();
  const projectId = Number(opts.project || (cfg && cfg.project_id) || 281);
  const runId = opts['run-id'] || opts['task-model-run-id'] || opts['task-id'];
  if (!runId) usage();
  const statePath = path.resolve(opts.state || DEFAULT_STATE);
  if (!fs.existsSync(statePath)) {
    throw new Error(`state file not found: ${statePath}; run auth-from-chrome first`);
  }
  const outDir = path.resolve(
    opts['tasks-dir'] || path.join(REPO_ROOT, 'tasks'),
    opts['sheet-task-id'] ? String(opts['sheet-task-id']) : '4267',
    opts['output-subdir'] || 'ark_g1',
  );
  ensureDir(outDir);

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ storageState: statePath });
  const page = await ctx.newPage();
  const calls = [];
  page.on('request', (req) => {
    const url = req.url();
    if (!url.includes('/api/top/ark/')) return;
    calls.push({
      action: url.split('/').pop().split('?')[0],
      method: req.method(),
      postData: req.postData(),
    });
  });
  const url = `https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/projects/${projectId}/review/${runId}?mode=audit`;
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await sleep(5000);
  await page.screenshot({ path: path.join(outDir, `_audit_form_${runId}.png`), fullPage: true });
  fs.writeFileSync(path.join(outDir, `_audit_form_${runId}.html`), await page.content());

  const snapshot = await page.evaluate(() => {
    const textOf = (el) => ((el && (el.innerText || el.textContent)) || '').replace(/\s+/g, ' ').trim();
    const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,.arco-form-item-label,label,.arco-radio-group'))
      .map((el) => ({ tag: el.tagName, cls: String(el.className || '').slice(0, 120), text: textOf(el).slice(0, 400) }))
      .filter((x) => x.text)
      .slice(0, 120);
    const radios = Array.from(document.querySelectorAll('.arco-radio, [role="radio"], input[type="radio"]')).map((el) => ({
      text: textOf(el).slice(0, 200) || (el.getAttribute && el.getAttribute('value')) || '',
      checked: !!(el.checked || (el.getAttribute && el.getAttribute('aria-checked') === 'true')),
      cls: String(el.className || '').slice(0, 120),
    }));
    const radioGroups = Array.from(document.querySelectorAll('.arco-radio-group, [role="radiogroup"], .arco-form-item')).map((g) => ({
      cls: String(g.className || '').slice(0, 160),
      text: textOf(g).slice(0, 800),
    })).filter((g) => g.text).slice(0, 40);
    const textareas = Array.from(document.querySelectorAll('textarea, .arco-textarea')).map((el) => ({
      placeholder: el.getAttribute('placeholder') || '',
      value: (el.value || textOf(el)).slice(0, 300),
      maxLength: el.getAttribute('maxlength') || '',
    }));
    const selects = Array.from(document.querySelectorAll('.arco-select, select')).map((el) => ({
      text: textOf(el).slice(0, 400),
      placeholder: el.getAttribute('placeholder') || el.getAttribute('aria-placeholder') || '',
    }));
    const checkboxes = Array.from(document.querySelectorAll('.arco-checkbox, input[type="checkbox"]')).map((el) => ({
      text: textOf(el.parentElement || el).slice(0, 200),
      checked: !!(el.checked || (el.getAttribute && el.getAttribute('aria-checked') === 'true')),
    }));
    const buttons = Array.from(document.querySelectorAll('button, .arco-btn')).map((el) => textOf(el)).filter(Boolean).slice(0, 40);
    const bodyText = textOf(document.body).slice(0, 8000);
    return { headings, radios, radioGroups, textareas, selects, checkboxes, buttons, bodyText };
  });

  const audit = await postAction(ctx, statePath, 'CaseBffV1CrowdtestTaskModelAuditGet', {
    taskModelRunId: Number(runId),
  });
  writeJSON(path.join(outDir, `audit_get_${runId}.json`), audit);

  const payload = {
    url,
    projectId,
    runId: Number(runId),
    actions: [...new Set(calls.map((c) => c.action).filter(Boolean))],
    calls,
    snapshot,
    saved_at: new Date().toISOString(),
  };
  writeJSON(path.join(outDir, `audit_form_${runId}.json`), payload);
  console.log(`==> audit url ${url}`);
  console.log(`==> APIs: ${payload.actions.join(', ') || '(none)'}`);
  console.log(`==> radioGroups=${snapshot.radioGroups.length} radios=${snapshot.radios.length} textareas=${snapshot.textareas.length} selects=${snapshot.selects.length}`);
  for (const g of snapshot.radioGroups.slice(0, 15)) {
    console.log(`   [group] ${g.text.slice(0, 160)}`);
  }
  for (const t of snapshot.textareas) {
    console.log(`   [textarea] placeholder=${JSON.stringify(t.placeholder)} value=${JSON.stringify(t.value.slice(0, 80))}`);
  }
  console.log(`==> wrote ${rel(path.join(outDir, `audit_form_${runId}.json`))}`);
  await browser.close();
}

async function authFromChrome(opts) {
  try {
    if (process.platform === 'win32') authFromChromeWindows(opts);
    else authFromChromeUnix(opts);
  } catch (err) {
    console.error(`==> Chrome cookie export failed: ${err.message}`);
    console.error('==> falling back to interactive Playwright login (auth-login)');
    await authLogin(opts);
  }
}

async function main() {
  const opts = parseArgs(process.argv);
  if (opts.cmd === 'auth-from-chrome') return authFromChrome(opts);
  if (opts.cmd === 'auth-login') return authLogin(opts);
  if (opts.cmd === 'find-project') return findProject(opts);
  if (opts.cmd === 'collect') return collect(opts);
  if (opts.cmd === 'discover-download') return discoverDownloadList(opts);
  if (opts.cmd === 'discover-audit') return discoverAuditForm(opts);
  usage();
}

main().catch((e) => {
  console.error(e.stack || e.message || e);
  process.exit(1);
});
