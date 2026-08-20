#!/usr/bin/env node
// Download 33/34期 source/model artifact zips from the 方舟众测平台.
//
// Writes under tasks/<TASK_ID>/platform_artifacts/:
//   source-<TASK_ID>.zip
//   <MODEL_ID>.zip
//   artifact_index.json
//
// The matching extractor is extract_platform_artifacts.py.

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { Readable } = require('stream');
const { pipeline } = require('stream/promises');

const HOST = 'https://sd8c3fetlp0rb5mhmacf0.apigateway-cn-shanghai.volceapi.com';
const HERE = __dirname;
const SKILL_DIR = path.resolve(HERE, '..');
const REPO_ROOT = path.resolve(SKILL_DIR, '..', '..');
const STATE_FILE = path.join(SKILL_DIR, '.platform_state.json');

function parseArgs(argv) {
  const opts = {
    ids: [],
    tasksDir: path.join(REPO_ROOT, 'tasks'),
    keepExisting: false,
    skipSource: false,
    forcePackage: false,
  };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--tasks-dir') opts.tasksDir = argv[++i];
    else if (a === '--keep-existing') opts.keepExisting = true;
    else if (a === '--skip-source') opts.skipSource = true;
    else if (a === '--force-package') opts.forcePackage = true;
    else opts.ids.push(a);
  }
  if (!opts.ids.length) {
    console.error('usage: fetch_platform_artifacts.js <TASK_ID> [...] [--tasks-dir tasks] [--keep-existing] [--skip-source] [--force-package]');
    process.exit(2);
  }
  return opts;
}

function rel(p) {
  return path.relative(REPO_ROOT, p).replace(/\\/g, '/');
}

function sanitizeFileName(s) {
  return String(s || '').replace(/[^\w.\-]+/g, '_');
}

async function requestOK(req, method, url, options = {}) {
  const r = method === 'POST' ? await req.post(url, options) : await req.get(url, options);
  if (r.status() >= 400) {
    throw new Error(`${method} ${url} -> ${r.status()} ${await r.text()}`);
  }
  return r;
}

async function downloadTo(req, url, outPath, keepExisting) {
  if (keepExisting && fs.existsSync(outPath) && fs.statSync(outPath).size > 0) {
    console.log(`   [keep] ${rel(outPath)} (${Math.round(fs.statSync(outPath).size / 1024)} KiB)`);
    return { path: outPath, size: fs.statSync(outPath).size, skipped: true };
  }
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  const tmpPath = `${outPath}.part`;
  const cookie = cookieHeader();
  const resp = await fetch(url, { headers: cookie ? { Cookie: cookie } : {} });
  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    throw new Error(`GET ${url} -> ${resp.status} ${text.slice(0, 500)}`);
  }
  await pipeline(Readable.fromWeb(resp.body), fs.createWriteStream(tmpPath));
  fs.renameSync(tmpPath, outPath);
  const size = fs.statSync(outPath).size;
  console.log(`   [download] ${rel(outPath)} (${Math.round(size / 1024)} KiB)`);
  return { path: outPath, size, skipped: false };
}

function cookieHeader() {
  if (!fs.existsSync(STATE_FILE)) return '';
  const state = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  return (state.cookies || [])
    .filter(c => c.domain && HOST.includes(c.domain.replace(/^\./, '')))
    .map(c => `${c.name}=${c.value}`)
    .join('; ');
}

async function ensureArtifactPackage(req, taskId, modelId, forcePackage, folderTaskId = taskId) {
  const folderName = `${folderTaskId}/${modelId}`;
  async function requestPackage(mode) {
    return requestOK(req, 'POST', `${HOST}/api/download_zip_jobs`, {
      timeout: 60 * 1000,
      headers: { 'Content-Type': 'application/json' },
      data: { folderName, mode, force: forcePackage === true },
    });
  }
  let post = await requestPackage('full');
  let info = await post.json();
  if (!info.canDownload && !info.jobId && Array.isArray(info.availableModes) && info.availableModes.includes('quick')) {
    console.log(`   [package] full unavailable for ${folderName}; falling back to quick mode`);
    post = await requestPackage('quick');
    info = await post.json();
  }
  const started = Date.now();
  while (!info.canDownload && info.jobId && !['completed', 'failed'].includes(info.status)) {
    if (Date.now() - started > 10 * 60 * 1000) {
      throw new Error(`download package timed out for ${folderName} (job ${info.jobId})`);
    }
    await new Promise(resolve => setTimeout(resolve, 2500));
    const poll = await requestOK(req, 'GET', `${HOST}/api/download_zip_jobs/${encodeURIComponent(info.jobId)}`, {
      timeout: 60 * 1000,
    });
    info = await poll.json();
  }
  if (!info.canDownload || !info.downloadUrl) {
    throw new Error(`artifact package not downloadable for ${folderName}: ${JSON.stringify(info).slice(0, 500)}`);
  }
  return info;
}

function readFeedbackTaskId(taskDir, modelName, modelId) {
  const checkPath = path.join(taskDir, 'feedback', `${modelName}__${modelId}.check.json`);
  if (!fs.existsSync(checkPath)) return null;
  try {
    const data = JSON.parse(fs.readFileSync(checkPath, 'utf8'));
    return data && typeof data.taskId === 'string' && data.taskId ? data.taskId : null;
  } catch {
    return null;
  }
}

async function processOne(req, taskId, opts) {
  console.log(`\n==> ${taskId}`);
  const taskDir = path.join(opts.tasksDir, taskId);
  const outDir = path.join(taskDir, 'platform_artifacts');
  fs.mkdirSync(outDir, { recursive: true });

  const detailsResp = await requestOK(req, 'GET', `${HOST}/api/task_details/${encodeURIComponent(taskId)}`, {
    timeout: 60 * 1000,
  });
  const details = await detailsResp.json();
  const taskModels = Array.isArray(details.taskModels) ? details.taskModels : [];
  if (!taskModels.length) throw new Error('task_details has no taskModels');

  const index = {
    task_id: taskId,
    title: details.title || '',
    source_type: details.sourceType || '',
    generated_at: new Date().toISOString(),
    source_zip: null,
    models: [],
  };

  if (!opts.skipSource && details.sourceType === 'upload') {
    const sourcePath = path.join(outDir, `source-${taskId}.zip`);
    const dl = await downloadTo(req, `${HOST}/api/tasks/${encodeURIComponent(taskId)}/download`, sourcePath, opts.keepExisting);
    index.source_zip = path.relative(taskDir, dl.path).replace(/\\/g, '/');
  } else {
    console.log(`   [source] skipped (sourceType=${details.sourceType || 'unknown'})`);
  }

  for (const m of taskModels) {
    const modelId = m.id || m.modelId;
    const name = m.name || m.displayName || modelId;
    const folderTaskId = readFeedbackTaskId(taskDir, name, modelId) || taskId;
    const folderNote = folderTaskId === taskId ? '' : ` folder=${folderTaskId}/${modelId}`;
    console.log(`   model ${name} (${modelId})`);
    if (folderNote) console.log(`      [folder] using feedback task ${folderTaskId}`);
    const pkg = await ensureArtifactPackage(req, taskId, modelId, opts.forcePackage, folderTaskId);
    const zipPath = path.join(outDir, `${sanitizeFileName(modelId)}.zip`);
    const url = pkg.downloadUrl.startsWith('http') ? pkg.downloadUrl : `${HOST}${pkg.downloadUrl}`;
    const dl = await downloadTo(req, url, zipPath, opts.keepExisting);
    index.models.push({
      code: modelId,
      name,
      display_name: m.displayName || name,
      endpoint_name: m.endpointName || '',
      folder_name: `${folderTaskId}/${modelId}`,
      zip: path.relative(taskDir, dl.path).replace(/\\/g, '/'),
      package: pkg,
    });
  }

  const indexPath = path.join(outDir, 'artifact_index.json');
  fs.writeFileSync(indexPath, JSON.stringify(index, null, 2));
  console.log(`   wrote ${rel(indexPath)}`);
}

async function main() {
  const opts = parseArgs(process.argv);
  if (!fs.existsSync(STATE_FILE)) {
    console.error(`no storageState at ${STATE_FILE}; run platform.js login first`);
    process.exit(2);
  }
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ storageState: STATE_FILE });
  try {
    for (const id of opts.ids) {
      await processOne(ctx.request, id, opts);
    }
  } finally {
    await browser.close();
  }
}

main().catch(e => {
  console.error(e.stack || e.message || e);
  process.exit(1);
});
