#!/usr/bin/env node
// Capture real OpenCode web UI evidence for tasks whose artifact is a full
// OpenCode repository rather than a small Vite demo.

const fs = require("fs");
const path = require("path");
const http = require("http");
const { spawn, spawnSync } = require("child_process");
const { chromium } = require("../node_modules/playwright");
const { preferredPortBase } = require("./lib/concurrency");

const repoRoot = path.resolve(__dirname, "../../..");

function usage() {
  console.error("usage: node screenshot_opencode_app.js <TASK_ID> [--only COL_OR_CODE] [--base-port PORT]");
  process.exit(2);
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function safeTag(label) {
  return label.replace(/ /g, "_");
}

function bunCmd() {
  return process.platform === "win32" ? "bun.cmd" : "bun";
}

function run(cmd, args, cwd, timeoutMs) {
  const res = spawnSync(cmd, args, {
    cwd,
    encoding: "utf8",
    timeout: timeoutMs,
    shell: false,
    stdio: "pipe",
  });
  return {
    code: res.status ?? 1,
    stdout: res.stdout || "",
    stderr: res.stderr || "",
    error: res.error,
  };
}

async function waitForHttp(url, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const ok = await new Promise((resolve) => {
      const req = http.get(url, (res) => {
        res.resume();
        resolve(res.statusCode && res.statusCode < 500);
      });
      req.on("error", () => resolve(false));
      req.setTimeout(2000, () => {
        req.destroy();
        resolve(false);
      });
    });
    if (ok) return true;
    await new Promise((r) => setTimeout(r, 1000));
  }
  return false;
}

async function clickText(page, labels) {
  for (const label of labels) {
    const loc = page.getByText(label, { exact: true });
    const count = await loc.count().catch(() => 0);
    if (!count) continue;
    try {
      await loc.first().click({ timeout: 3000 });
      return label;
    } catch {}
  }
  return null;
}

async function screenshot(page, file) {
  await page.screenshot({ path: file, fullPage: false });
  console.log(`     ${path.basename(file)}`);
}

async function captureModel(taskId, col, info, idx, basePort, only) {
  if (only && only !== col && only !== info.code) return;

  const taskDir = path.join(repoRoot, "tasks", taskId);
  const modelDir = path.join(taskDir, "extracted", info.code);
  const appDir = path.join(modelDir, "packages", "app");
  const outDir = path.join(repoRoot, "delivery", taskId, "screenshots");
  fs.mkdirSync(outDir, { recursive: true });

  const tag = safeTag(col);
  for (const name of fs.readdirSync(outDir)) {
    if (name.startsWith(`${tag}_`) && name.endsWith(".png")) {
      fs.rmSync(path.join(outDir, name), { force: true });
    }
  }

  console.log(`==> ${col} (${info.code})`);
  if (!fs.existsSync(path.join(appDir, "package.json"))) {
    console.log("   [skip] packages/app/package.json not found");
    return;
  }

  if (!fs.existsSync(path.join(modelDir, "node_modules"))) {
    console.log("   installing deps with bun install --ignore-scripts");
    const install = run(bunCmd(), ["install", "--ignore-scripts"], modelDir, 600000);
    if (install.code !== 0) {
      console.log((install.stdout + install.stderr).trim());
      throw new Error(`bun install failed for ${col}`);
    }
  }

  const port = basePort + idx;
  const logPath = path.join(taskDir, `opencode-${info.code}-dev.log`);
  const errPath = path.join(taskDir, `opencode-${info.code}-dev.err.log`);
  const log = fs.openSync(logPath, "w");
  const errLog = fs.openSync(errPath, "w");
  const child = spawn(
    bunCmd(),
    ["--cwd", "packages/app", "dev", "--host", "127.0.0.1", "--port", String(port)],
    {
      cwd: modelDir,
      stdio: ["ignore", log, errLog],
      detached: false,
      windowsHide: true,
      shell: process.platform === "win32",
    },
  );

  let browser;
  try {
    const url = `http://127.0.0.1:${port}/`;
    if (!(await waitForHttp(url, 90000))) {
      throw new Error(`dev server not reachable at ${url}; see ${logPath}`);
    }

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1280, height: 840 }, deviceScaleFactor: 1 });
    page.setDefaultTimeout(5000);
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(2500);
    await screenshot(page, path.join(outDir, `${tag}_01_home.png`));

    await clickText(page, ["设置", "Settings"]);
    await page.waitForTimeout(1200);
    await screenshot(page, path.join(outDir, `${tag}_02_settings.png`));

    if (await clickText(page, ["模型", "Models"])) {
      await page.waitForTimeout(1200);
      await screenshot(page, path.join(outDir, `${tag}_03_models.png`));
    }

    if (await clickText(page, ["智能体", "Agents"])) {
      await page.waitForTimeout(1200);
      await screenshot(page, path.join(outDir, `${tag}_04_agents.png`));
    }
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (process.platform === "win32") {
      spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    } else {
      child.kill();
    }
    fs.closeSync(log);
    fs.closeSync(errLog);
  }
}

async function main() {
  const args = process.argv.slice(2);
  const taskId = args.shift();
  if (!taskId) usage();
  let only = "";
  let basePort = null;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--only") only = args[++i] || "";
    else if (args[i] === "--base-port") basePort = Number(args[++i]);
    else usage();
  }

  const mapPath = path.join(repoRoot, "tasks", taskId, "model_map.json");
  basePort ??= preferredPortBase(taskId, 'screenshot-opencode-app', 8);
  const modelMap = readJson(mapPath);
  const entries = Object.entries(modelMap.models);
  for (let i = 0; i < entries.length; i++) {
    const [col, info] = entries[i];
    await captureModel(taskId, col, info, i, basePort, only);
  }
}

main().catch((err) => {
  console.error(err.stack || err.message || String(err));
  process.exit(1);
});
