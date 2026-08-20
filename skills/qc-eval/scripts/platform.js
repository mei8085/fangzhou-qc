#!/usr/bin/env node
// 方舟众测平台 (apigateway-cn-shanghai.volceapi.com) read-only helpers.
//
// Sub-commands:
//   login --user <U> --pass <P>           – log in, save storageState to .platform_state.json
//   map   --task <ID> --user <USER> [--out <task_dir>]
//          – cycle through the 4 model tabs in task.html, parse the comment
//            screenshot img src, match it to extracted/comments/<file>.png,
//            and write tasks/<TASK_ID>/model_map.json
//
// The login state is persisted in skills/qc-eval/.platform_state.json (gitignored).
// Refresh it by re-running `login` when API calls start returning 401.

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const PLATFORM_HOST = 'https://sd8c3fetlp0rb5mhmacf0.apigateway-cn-shanghai.volceapi.com';
const HERE = __dirname;
const SKILL_DIR = path.resolve(HERE, '..');
const REPO_ROOT = path.resolve(SKILL_DIR, '..', '..');
const STATE_FILE = path.join(SKILL_DIR, '.platform_state.json');

function parseArgs(argv) {
  const cmd = argv[2];
  const opts = { cmd, _: [] };
  for (let i = 3; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const k = a.slice(2);
      const v = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[++i] : true;
      opts[k] = v;
    } else opts._.push(a);
  }
  return opts;
}

async function loadContext(browser) {
  if (!fs.existsSync(STATE_FILE)) {
    throw new Error(`no storageState at ${STATE_FILE}; run "platform.js login --user X --pass Y" first`);
  }
  return browser.newContext({ storageState: STATE_FILE });
}

async function cmdLogin(opts) {
  const user = opts.user || process.env.PLATFORM_USER;
  const pass = opts.pass || process.env.PLATFORM_PASS;
  if (!user || !pass) {
    console.error('login: need --user and --pass (or PLATFORM_USER/PLATFORM_PASS)');
    process.exit(2);
  }
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  console.log('==> opening login.html');
  await page.goto(`${PLATFORM_HOST}/login.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#username', { timeout: 30000 });
  await page.fill('#username', user);
  await page.fill('#password', pass);

  // The submit may navigate; race the navigation against an error toast.
  const navP = page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => null);
  await page.click('#login-btn');
  await navP;
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});

  // Quick verification: hit a small auth-required endpoint.
  const verifyResp = await page.request.get(
    `${PLATFORM_HOST}/api/tasks/verify?taskId=__probe__&view_user=__probe__&share_user=__probe__&share_task=__probe__`
  );
  // 401 here would mean login failed. 4xx other than 401 (e.g. 404/400) is OK
  // because that just means our probe id is invalid — auth is fine.
  if (verifyResp.status() === 401) {
    console.error('login: still 401 after submit — credentials rejected?');
    await browser.close();
    process.exit(3);
  }
  await ctx.storageState({ path: STATE_FILE });
  console.log(`==> saved storageState -> ${STATE_FILE}`);
  await browser.close();
}

function platformUrl(task_id, view_user, model_code) {
  return `${PLATFORM_HOST}/task.html?view_user=${encodeURIComponent(view_user)}&task=${encodeURIComponent(task_id)}&model=${encodeURIComponent(model_code)}&page=trajectory`;
}

function isViteProject(dir) {
  if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) return false;
  return fs.existsSync(path.join(dir, 'package.json')) &&
         fs.existsSync(path.join(dir, 'index.html')) &&
         (fs.existsSync(path.join(dir, 'vite.config.js')) ||
          fs.existsSync(path.join(dir, 'vite.config.ts')));
}

function routerLooksLikeOrdering(routerFile) {
  // Cheap heuristic: the default ("/") route imports something whose name
  // does not contain "FormBuilder" / "Builder" / "VideoGenerate". Used to
  // decide whether the model's root project is actually serving the ordering
  // app or has been hijacked by an unrelated FormBuilder.
  try {
    const src = fs.readFileSync(routerFile, 'utf8');
    // Find the first "{ path: '/'" block and inspect its component name.
    const m = src.match(/path:\s*['\"]\/['\"]\s*[,\}][\s\S]{0,400}?component:\s*\(\s*\)\s*=>\s*import\(['\"]([^'\"]+)['\"]/);
    if (!m) return null; // unknown
    const importPath = m[1];
    if (/FormBuilder|VideoGenerate|Builder/i.test(importPath)) return false;
    return true;
  } catch {
    return null;
  }
}

function detectViteEntry(modelRoot, code) {
  // Returns a path RELATIVE to modelRoot (string), defaulting to '.'.
  // The relative form means downstream scripts can construct the absolute path
  // as path.join(extractedDir, code, entry).
  if (!isViteProject(modelRoot)) {
    // Root is not even a vite project; try first vite-shaped subdir.
    const subs = fs.readdirSync(modelRoot, { withFileTypes: true })
      .filter(d => d.isDirectory() && d.name !== 'node_modules')
      .map(d => d.name);
    for (const sub of subs) {
      if (isViteProject(path.join(modelRoot, sub))) return sub;
    }
    return '.';
  }
  // Root IS a vite project. Inspect router to see if it routes to the ordering
  // app at '/'. If yes, use root.
  const candidates = [
    path.join(modelRoot, 'src', 'router.js'),
    path.join(modelRoot, 'src', 'router.ts'),
    path.join(modelRoot, 'src', 'router', 'index.js'),
    path.join(modelRoot, 'src', 'router', 'index.ts'),
  ];
  let verdict = null;
  for (const r of candidates) {
    if (fs.existsSync(r)) {
      verdict = routerLooksLikeOrdering(r);
      break;
    }
  }
  if (verdict !== false) return '.'; // ordering at root, or unknown -> use root
  // Root router routes to something non-ordering. Look for a sibling vite project.
  const subs = fs.readdirSync(modelRoot, { withFileTypes: true })
    .filter(d => d.isDirectory() && d.name !== 'node_modules' && d.name !== 'src' &&
                 d.name !== 'public' && d.name !== 'dist' && d.name !== 'reports')
    .map(d => d.name);
  for (const sub of subs) {
    if (isViteProject(path.join(modelRoot, sub))) {
      console.log(`     [${code}] root routes to non-ordering; using subproject ${sub}/`);
      return sub;
    }
  }
  console.log(`     [${code}] root routes to non-ordering but no sibling vite project found`);
  return '.';
}

async function getJSON(ctx, url) {
  const r = await ctx.request.get(url);
  const status = r.status();
  if (status >= 400) throw new Error(`GET ${url} -> ${status}`);
  return r.json();
}

async function cmdMap(opts) {
  const task_id = opts.task;
  if (!task_id) {
    console.error('map: need --task <ID>');
    process.exit(2);
  }
  const tasks_dir = opts['tasks-dir'] || path.join(REPO_ROOT, 'tasks');
  const task_dir = path.join(tasks_dir, task_id);
  const extractedDir = path.join(task_dir, 'extracted');
  const commentDir = path.join(extractedDir, 'comments');

  const browser = await chromium.launch({ headless: true });
  const ctx = await loadContext(browser);

  // 1. Authoritative model mapping comes from /api/task_details.
  console.log(`==> ${task_id}: /api/task_details`);
  const details = await getJSON(ctx, `${PLATFORM_HOST}/api/task_details/${encodeURIComponent(task_id)}`);
  const taskModels = details.taskModels || [];
  if (!taskModels.length) throw new Error('task_details has no taskModels');
  // taskModels[i] = { id, modelId, name, displayName, endpointName }
  // name is the sheet column ("0614C", "0616B", ...); id/modelId is the dir code.
  console.log(`   taskModels: ${taskModels.map(m => `${m.name}=${m.id}`).join(', ')}`);

  // 2. Comment PNGs per model come from /api/comments/user-feedback. The
  //    response is task-wide regardless of which modelId we pass, so one call
  //    is enough. We still need a valid modelId for the request.
  const firstCode = taskModels[0].id;
  console.log(`==> ${task_id}: /api/comments/user-feedback`);
  const userFeedback = await getJSON(
    ctx,
    `${PLATFORM_HOST}/api/comments/user-feedback?taskId=${encodeURIComponent(task_id)}&modelId=${encodeURIComponent(firstCode)}`
  );
  // Index images by model_id.
  const imagesByCode = {};
  let viewUser = null;
  for (const e of userFeedback) {
    const imgs = e.images ? JSON.parse(e.images) : [];
    // Each img is "<TID>/comments/<file>.png"; we just want the basename.
    imagesByCode[e.model_id] = imgs.map(s => s.split('/').pop());
    if (!viewUser && e.user_name) viewUser = e.user_name;
  }
  if (opts.user) viewUser = opts.user; // explicit override wins
  console.log(`   view_user = ${viewUser}`);

  // 3. Sanity-check against extracted/comments/ if the task has been extracted.
  let extraInComments = [];
  let missingFromExtracted = [];
  if (fs.existsSync(commentDir)) {
    const have = new Set(fs.readdirSync(commentDir));
    const referenced = new Set(Object.values(imagesByCode).flat());
    extraInComments = [...have].filter(x => !referenced.has(x));
    missingFromExtracted = [...referenced].filter(x => !have.has(x));
    if (extraInComments.length) console.log(`   [warn] in extracted/comments but no API ref: ${extraInComments}`);
    if (missingFromExtracted.length) console.log(`   [warn] API references but not in extracted/comments: ${missingFromExtracted}`);
  } else {
    console.log(`   (note) ${commentDir} not present — skipping file existence check`);
  }

  // 4. Cross-check: extracted/<code>/ dirs should match taskModels[].id.
  let extractedCodes = [];
  if (fs.existsSync(extractedDir)) {
    extractedCodes = fs.readdirSync(extractedDir)
      .filter(n => !['comments', 'logs', 'source'].includes(n))
      .sort();
    const declared = new Set(taskModels.map(m => m.id));
    const extra = extractedCodes.filter(c => !declared.has(c));
    const missing = [...declared].filter(c => !extractedCodes.includes(c));
    if (extra.length) console.log(`   [warn] extracted dirs not in taskModels: ${extra}`);
    if (missing.length) console.log(`   [warn] taskModels not on disk: ${missing}`);
  }

  // 5. Detect each model's vite-runnable entry directory (so screenshot_vue.js
  //    knows where to run `npm run dev`). For models whose root router defaults
  //    to a non-ordering page (e.g. a FormBuilder hijacked the root), look for
  //    a sibling directory that itself contains package.json + vite.config.js
  //    + index.html — that's where the actual app lives.
  const entryByCode = {};
  for (const code of extractedCodes) {
    const root = path.join(extractedDir, code);
    entryByCode[code] = detectViteEntry(root, code);
  }

  // 6. Assemble model_map.json keyed by sheet column.
  const models = {};
  for (const m of taskModels) {
    const code = m.id;
    const pngs = imagesByCode[code] || [];
    models[m.name] = {
      code,
      display_name: m.displayName,
      platform_url: platformUrl(task_id, viewUser, code),
      comment_pngs: pngs.map(p => `extracted/comments/${p}`),
      entry: entryByCode[code] || '.',
    };
  }
  const out = {
    task_id,
    view_user: viewUser,
    sheet_columns: taskModels.map(m => m.name),
    models,
    extracted_codes: extractedCodes,
    extra_in_comments_dir: extraInComments,
    missing_from_extracted_dir: missingFromExtracted,
    source: 'GET /api/task_details + /api/comments/user-feedback',
    generated_at: new Date().toISOString(),
  };
  const outPath = path.join(task_dir, 'model_map.json');
  fs.mkdirSync(task_dir, { recursive: true });
  fs.writeFileSync(outPath, JSON.stringify(out, null, 2));
  console.log(`==> wrote ${outPath}`);
  await browser.close();
}

async function main() {
  const opts = parseArgs(process.argv);
  if (opts.cmd === 'login') return cmdLogin(opts);
  if (opts.cmd === 'map') return cmdMap(opts);
  console.error('usage: platform.js <login|map> [...flags]');
  process.exit(2);
}
main().catch(e => { console.error(e); process.exit(1); });
