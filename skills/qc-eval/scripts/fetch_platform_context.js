#!/usr/bin/env node
// Fetch platform-backed period context that is not present in the Feishu sheet:
// data-statistics prompt/table, per-model execution trajectory, source/model
// artifact metadata, and links already captured in model_map.json.
//
// Writes under tasks/<TASK_ID>/:
//   platform_context/data_statistics.{json,txt,html}
//   trajectory/<MODEL>__<CODE>.events.json
//   trajectory/<MODEL>__<CODE>.events.txt
//   trajectory/<MODEL>__<CODE>.page.{txt,html}
//   trajectory/_summary.json

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const HOST = 'https://sd8c3fetlp0rb5mhmacf0.apigateway-cn-shanghai.volceapi.com';
const HERE = __dirname;
const SKILL_DIR = path.resolve(HERE, '..');
const REPO_ROOT = path.resolve(SKILL_DIR, '..', '..');
const STATE_FILE = path.join(SKILL_DIR, '.platform_state.json');

function parseArgs(argv) {
  const opts = {
    ids: [],
    tasksDir: path.join(REPO_ROOT, 'tasks'),
    skipDom: false,
  };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--tasks-dir') opts.tasksDir = argv[++i];
    else if (a === '--skip-dom') opts.skipDom = true;
    else opts.ids.push(a);
  }
  if (!opts.ids.length) {
    console.error('usage: fetch_platform_context.js <TASK_ID> [...] [--tasks-dir tasks] [--skip-dom]');
    process.exit(2);
  }
  return opts;
}

function rel(p) {
  return path.relative(REPO_ROOT, p).replace(/\\/g, '/');
}

function sanitize(s) {
  return String(s || '').replace(/[^A-Za-z0-9._-]+/g, '_');
}

async function requestJSON(req, url) {
  const r = await req.get(url, { timeout: 60 * 1000 });
  const status = r.status();
  let body;
  try { body = await r.json(); } catch { body = await r.text(); }
  if (status >= 400) {
    throw new Error(`GET ${url} -> ${status} ${typeof body === 'string' ? body : JSON.stringify(body).slice(0, 500)}`);
  }
  return body;
}

function pickLatestRunByModel(details) {
  const out = {};
  for (const run of details.runs || []) {
    const code = run.modelId || (run.folderName || '').split('/').pop();
    if (!code) continue;
    const prev = out[code];
    if (!prev || (run.isLatestRound && !prev.isLatestRound) || (run.roundNo || 0) > (prev.roundNo || 0)) {
      out[code] = run;
    }
  }
  return out;
}

function eventsToText(eventsBody) {
  const lines = [];
  for (const e of eventsBody.events || []) {
    if (e.synthetic && !e.preview_text) continue;
    const head = [
      e.roundNo ? `round ${e.roundNo}` : null,
      e.type || null,
      e.tool_name ? `tool=${e.tool_name}` : null,
      e.status_class || null,
    ].filter(Boolean).join(' | ');
    if (head) lines.push(`## ${head}`);
    const text = e.preview_text || e.text || e.content || '';
    if (text) lines.push(String(text));
    lines.push('');
  }
  return lines.join('\n').trim() + '\n';
}

async function clickByExactText(page, labels) {
  const clicked = await page.evaluate((labels) => {
    const wanted = new Set(labels);
    const els = Array.from(document.querySelectorAll('*'));
    const el = els.find((node) => {
      const text = (node.innerText || '').trim();
      if (!text) return false;
      if (wanted.has(text)) return true;
      return text.split(/\n+/).some((part) => wanted.has(part.trim())) && node.children.length <= 3;
    });
    if (!el) return false;
    el.click();
    return true;
  }, labels);
  if (clicked) {
    await page.waitForTimeout(1200);
    await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
  }
  return clicked;
}

async function savePageSnapshot(page, outBase) {
  const txt = await page.locator('body').innerText({ timeout: 10000 }).catch(() => '');
  fs.writeFileSync(`${outBase}.txt`, txt);
  fs.writeFileSync(`${outBase}.html`, await page.content());
}

function platformUrl(taskId, viewUser, modelCode) {
  return `${HOST}/task.html?view_user=${encodeURIComponent(viewUser)}&task=${encodeURIComponent(taskId)}&model=${encodeURIComponent(modelCode)}&page=trajectory`;
}

async function processOne(ctx, taskId, opts) {
  console.log(`\n==> ${taskId}: platform context`);
  const taskDir = path.join(opts.tasksDir, taskId);
  const mapPath = path.join(taskDir, 'model_map.json');
  const modelMap = fs.existsSync(mapPath) ? JSON.parse(fs.readFileSync(mapPath, 'utf8')) : null;
  const platformDir = path.join(taskDir, 'platform_context');
  const trajDir = path.join(taskDir, 'trajectory');
  fs.mkdirSync(platformDir, { recursive: true });
  fs.mkdirSync(trajDir, { recursive: true });

  const details = await requestJSON(ctx.request, `${HOST}/api/task_details/${encodeURIComponent(taskId)}`);
  const runsByCode = pickLatestRunByModel(details);
  const models = modelMap && modelMap.models
    ? Object.entries(modelMap.models).map(([name, info]) => ({ name, code: info.code, platform_url: info.platform_url }))
    : (details.taskModels || []).map((m) => ({ name: m.name || m.displayName || m.id, code: m.id || m.modelId }));

  const dataStats = {
    task_id: taskId,
    title: details.title || '',
    prompt: details.prompt || '',
    task_background: details.taskBackground || '',
    source_type: details.sourceType || '',
    models: models.map((m) => {
      const run = runsByCode[m.code] || {};
      return {
        name: m.name,
        code: m.code,
        run_id: run.runId || null,
        round_no: run.roundNo || null,
        status: run.status || '',
        folder_name: run.folderName || `${taskId}/${m.code}`,
        stats: run.stats || null,
      };
    }),
    source: 'GET /api/task_details + platform data-statistics tab',
    generated_at: new Date().toISOString(),
  };
  fs.writeFileSync(path.join(platformDir, 'data_statistics.json'), JSON.stringify(dataStats, null, 2));
  fs.writeFileSync(
    path.join(platformDir, 'data_statistics.txt'),
    `# ${dataStats.title} (${taskId})\n\n## Prompt\n\n${dataStats.prompt}\n`
  );

  const summary = {
    task_id: taskId,
    title: details.title || '',
    view_user: modelMap ? modelMap.view_user : null,
    models: {},
    generated_at: new Date().toISOString(),
  };

  for (const m of models) {
    const run = runsByCode[m.code];
    const tag = `${sanitize(m.name)}__${sanitize(m.code)}`;
    const entry = { code: m.code, name: m.name, run_id: run ? run.runId : null };
    if (run && run.runId) {
      const events = await requestJSON(ctx.request, `${HOST}/api/task_events/${encodeURIComponent(run.runId)}?compact=1`);
      const jsonPath = path.join(trajDir, `${tag}.events.json`);
      const txtPath = path.join(trajDir, `${tag}.events.txt`);
      fs.writeFileSync(jsonPath, JSON.stringify(events, null, 2));
      fs.writeFileSync(txtPath, eventsToText(events));
      entry.events_json = rel(jsonPath);
      entry.events_txt = rel(txtPath);
      console.log(`   events ${m.name} (${m.code}) run=${run.runId}`);
    } else {
      console.log(`   [warn] no runId for ${m.name} (${m.code})`);
    }
    summary.models[m.name] = entry;
  }

  if (!opts.skipDom && summary.view_user && models.length) {
    const page = await ctx.newPage();
    try {
      const first = models[0];
      await page.goto(platformUrl(taskId, summary.view_user, first.code), { waitUntil: 'domcontentloaded', timeout: 60000 });
      await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
      await clickByExactText(page, ['数据统计', '📈\n数据统计']);
      await savePageSnapshot(page, path.join(platformDir, 'data_statistics'));

      for (const m of models) {
        await page.goto(platformUrl(taskId, summary.view_user, m.code), { waitUntil: 'domcontentloaded', timeout: 60000 });
        await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
        await clickByExactText(page, ['执行轨迹']);
        const tag = `${sanitize(m.name)}__${sanitize(m.code)}`;
        const base = path.join(trajDir, `${tag}.page`);
        await savePageSnapshot(page, base);
        summary.models[m.name].page_txt = rel(`${base}.txt`);
        summary.models[m.name].page_html = rel(`${base}.html`);
      }
    } finally {
      await page.close();
    }
  }

  const summaryPath = path.join(trajDir, '_summary.json');
  fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2));
  console.log(`   wrote ${rel(summaryPath)}`);
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
      await processOne(ctx, id, opts);
    }
  } finally {
    await browser.close();
  }
}

main().catch(e => {
  console.error(e.stack || e.message || e);
  process.exit(1);
});
