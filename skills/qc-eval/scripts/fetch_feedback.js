#!/usr/bin/env node
// Pull labeler feedback from the platform for every (task, model) pair.
//
// Writes:
//   tasks/<TID>/feedback/task_details.json
//   tasks/<TID>/feedback/<COL>__<CODE>.comments.json
//   tasks/<TID>/feedback/<COL>__<CODE>.user_feedback.json
//   tasks/<TID>/feedback/<COL>__<CODE>.check.json
//
// COL is the sheet column name from model_map.json (e.g. "0614C"), CODE is the
// internal model directory code (e.g. "0F3TQ"). Two-part filename keeps both
// identifiers visible at a glance.
//
// Usage:
//   node fetch_feedback.js <TASK_ID> [<TASK_ID> ...] [--tasks-dir tasks]

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const HOST = 'https://sd8c3fetlp0rb5mhmacf0.apigateway-cn-shanghai.volceapi.com';
const HERE = __dirname;
const SKILL_DIR = path.resolve(HERE, '..');
const REPO_ROOT = path.resolve(SKILL_DIR, '..', '..');
const STATE = path.join(SKILL_DIR, '.platform_state.json');

function parseArgs(argv) {
  const opts = { ids: [], tasksDir: path.join(REPO_ROOT, 'tasks') };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--tasks-dir') opts.tasksDir = argv[++i];
    else opts.ids.push(a);
  }
  if (!opts.ids.length) {
    console.error('usage: fetch_feedback.js <TASK_ID> [...] [--tasks-dir tasks]');
    process.exit(2);
  }
  return opts;
}

function sanitize(s) {
  return s.replace(/[^A-Za-z0-9._-]+/g, '_');
}

async function getJSON(ctx, url) {
  const r = await ctx.request.get(url);
  const status = r.status();
  let body;
  try { body = await r.json(); } catch { body = await r.text(); }
  return { status, body };
}

async function fetchFor(ctx, taskId, tasksDir) {
  const taskDir = path.join(tasksDir, taskId);
  const mapPath = path.join(taskDir, 'model_map.json');
  if (!fs.existsSync(mapPath)) {
    console.error(`[skip] ${taskId}: no model_map.json (run platform.js map first)`);
    return false;
  }
  const map = JSON.parse(fs.readFileSync(mapPath, 'utf8'));
  const outDir = path.join(taskDir, 'feedback');
  fs.mkdirSync(outDir, { recursive: true });

  console.log(`==> ${taskId} (view_user=${map.view_user})`);

  // Task-wide details (model-agnostic)
  {
    const u = `${HOST}/api/task_details/${encodeURIComponent(taskId)}`;
    const { status, body } = await getJSON(ctx, u);
    console.log(`   task_details: ${status}`);
    fs.writeFileSync(path.join(outDir, 'task_details.json'), JSON.stringify(body, null, 2));
  }

  // Per-model endpoints
  const summary = { task_id: taskId, view_user: map.view_user, per_model: {} };
  for (const [col, info] of Object.entries(map.models)) {
    const code = info.code;
    const tag = `${sanitize(col)}__${code}`;
    console.log(`   model ${col} (${code}):`);
    const endpoints = {
      comments: `${HOST}/api/comments?taskId=${encodeURIComponent(taskId)}&modelId=${encodeURIComponent(code)}`,
      user_feedback: `${HOST}/api/comments/user-feedback?taskId=${encodeURIComponent(taskId)}&modelId=${encodeURIComponent(code)}`,
      check: `${HOST}/api/feedback/check?taskId=${encodeURIComponent(taskId)}&modelId=${encodeURIComponent(code)}`,
    };
    const perModel = { code };
    for (const [name, u] of Object.entries(endpoints)) {
      const { status, body } = await getJSON(ctx, u);
      const file = path.join(outDir, `${tag}.${name}.json`);
      fs.writeFileSync(file, JSON.stringify(body, null, 2));
      const sz = Array.isArray(body) ? `array(${body.length})` :
                 typeof body === 'object' && body ? `obj(keys=${Object.keys(body).length})` :
                 `${typeof body}`;
      console.log(`     ${name}: ${status} ${sz} -> ${path.basename(file)}`);
      perModel[name] = { status, file: path.relative(taskDir, file) };
    }
    summary.per_model[col] = perModel;
  }
  fs.writeFileSync(path.join(outDir, '_summary.json'), JSON.stringify(summary, null, 2));
  return true;
}

async function main() {
  const opts = parseArgs(process.argv);
  if (!fs.existsSync(STATE)) {
    console.error(`no storageState at ${STATE}; run platform.js login first`);
    process.exit(2);
  }
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ storageState: STATE });
  // Hit a verify endpoint once so the server has a user context.
  const probe = await ctx.request.get(`${HOST}/api/users/verify?username=dengquan`);
  if (probe.status() === 401) {
    console.error('session is unauthorized; re-run platform.js login');
    await browser.close();
    process.exit(3);
  }
  for (const id of opts.ids) {
    try {
      await fetchFor(ctx, id, opts.tasksDir);
    } catch (e) {
      console.error(`[err] ${id}:`, e.stack || e.message);
    }
  }
  await browser.close();
}
main().catch(e => { console.error(e); process.exit(1); });
