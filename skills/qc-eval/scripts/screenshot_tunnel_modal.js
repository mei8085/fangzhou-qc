#!/usr/bin/env node
// Capture runtime evidence for 24期 Ciconia tunnel modal reset tasks.

const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const { chromium } = require("playwright");

const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");

function safeTag(name) {
  return String(name).trim().replace(/[^0-9A-Za-z_.-]+/g, "_");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function run(cmd, args, opts = {}) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { shell: process.platform === "win32", ...opts });
    let out = "";
    child.stdout?.on("data", (d) => { out += d.toString(); });
    child.stderr?.on("data", (d) => { out += d.toString(); });
    child.on("close", (code) => resolve({ code, out }));
  });
}

async function ensureDeps(modelDir) {
  const viteCmd = process.platform === "win32"
    ? path.join(modelDir, "node_modules", ".bin", "vite.cmd")
    : path.join(modelDir, "node_modules", ".bin", "vite");
  if (fs.existsSync(viteCmd)) return;
  console.log(`   npm install in ${path.relative(REPO_ROOT, modelDir)}`);
  const r = await run("npm", ["install"], { cwd: modelDir, stdio: "pipe" });
  if (r.code !== 0) {
    throw new Error(`npm install failed\n${r.out.slice(-4000)}`);
  }
}

function startVite(modelDir, port) {
  const args = ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(port), "--strictPort"];
  const child = spawn("npm", args, {
    cwd: modelDir,
    shell: process.platform === "win32",
    stdio: ["ignore", "pipe", "pipe"],
  });
  let log = "";
  child.stdout.on("data", (d) => { log += d.toString(); });
  child.stderr.on("data", (d) => { log += d.toString(); });
  return { child, log: () => log };
}

async function waitForVite(server, port) {
  const url = `http://127.0.0.1:${port}/`;
  const started = Date.now();
  while (Date.now() - started < 120000) {
    if (server.child.exitCode !== null) {
      throw new Error(`vite exited early\n${server.log().slice(-4000)}`);
    }
    try {
      const res = await fetch(url);
      if (res.ok) return url;
    } catch (_) {
      // keep polling
    }
    await sleep(500);
  }
  throw new Error(`vite did not become ready\n${server.log().slice(-4000)}`);
}

async function stopTree(child) {
  if (!child || child.exitCode !== null) return;
  if (process.platform === "win32") {
    await run("taskkill", ["/PID", String(child.pid), "/T", "/F"]);
  } else {
    child.kill("SIGTERM");
  }
}

async function captureModel(taskId, col, code, port) {
  const modelDir = path.join(REPO_ROOT, "tasks", taskId, "extracted", code);
  const outDir = path.join(REPO_ROOT, "delivery", taskId, "screenshots");
  fs.mkdirSync(outDir, { recursive: true });
  const tag = safeTag(col);

  await ensureDeps(modelDir);
  const server = startVite(modelDir, port);
  let browser;
  try {
    const url = await waitForVite(server, port);
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
      viewport: { width: 1440, height: 1050 },
      deviceScaleFactor: 1,
    });
    await context.addInitScript(() => {
      const tunnel = {
        id: "demo-docker",
        name: "chatdoc_gfzq_test_pg",
        mode: "docker",
        ssh_host: "10.23.45.67",
        ssh_port: 22,
        ssh_username: "root",
        auth_type: "key",
        ssh_key_path: "/Users/haoyang/src/paoding/code/id_rsa",
        ssh_password: "",
        local_port: 15433,
        target_host: null,
        target_port: 5432,
        container_name: "chatdoc_gfzq_test_pg",
        container_port: 5432,
      };
      const settings = {
        launch_at_login: false,
        minimize_to_tray_on_close: false,
        keep_alive_interval: 30,
        default_ssh_key: "/Users/me/.ssh/id_rsa",
        strict_host_key_checking: false,
        connection_timeout: 10,
        auto_reconnect: true,
        theme: "dark",
        language: "en",
      };
      window.__TAURI_INTERNALS__ = {
        invoke: async (cmd, args) => {
          if (cmd === "get_tunnels") return [tunnel];
          if (cmd === "get_tunnel_status") return { is_running: false, ping: null, state: "stopped", send_bytes: 0, recv_bytes: 0 };
          if (cmd === "get_settings") return settings;
          if (cmd === "fetch_containers") return [{
            id: "pg",
            image: "registry.cheftin.cn/p/postgres14_pgvector",
            name: "chatdoc_gfzq_test_pg",
            ports: ["5432/tcp"],
            status: "running",
          }];
          if (cmd === "save_tunnel" || cmd === "delete_tunnel" || cmd === "start_tunnel" || cmd === "stop_tunnel") return null;
          if (cmd === "plugin:event|listen") return Math.floor(Math.random() * 100000);
          if (cmd === "plugin:event|unlisten") return null;
          return null;
        },
        transformCallback: () => Math.floor(Math.random() * 100000),
      };
    });

    const page = await context.newPage();
    await page.goto(url, { waitUntil: "networkidle", timeout: 120000 });
    await page.waitForSelector("text=chatdoc_gfzq_test_pg", { timeout: 30000 });
    await page.locator("text=chatdoc_gfzq_test_pg").first().hover();
    await page.locator('button[title="Edit"]').click();
    await page.waitForSelector("text=Edit Tunnel", { timeout: 10000 });
    await page.screenshot({ path: path.join(outDir, `${tag}_01_edit_dialog.png`), fullPage: true });

    await page.locator("button", { hasText: "Cancel" }).click();
    await page.locator('button[title="Add Tunnel"]').click();
    await page.waitForSelector("text=Add New Tunnel", { timeout: 10000 });
    await page.screenshot({ path: path.join(outDir, `${tag}_02_add_dialog.png`), fullPage: true });

    await browser.close();
  } finally {
    if (browser) await browser.close().catch(() => {});
    await stopTree(server.child);
  }
}

async function main() {
  const taskId = process.argv[2];
  if (!taskId) {
    console.error("Usage: screenshot_tunnel_modal.js <TASK_ID>");
    process.exit(2);
  }
  const mapPath = path.join(REPO_ROOT, "tasks", taskId, "model_map.json");
  const modelMap = JSON.parse(fs.readFileSync(mapPath, "utf8"));
  let i = 0;
  for (const col of modelMap.sheet_columns || Object.keys(modelMap.models)) {
    const m = modelMap.models[col];
    console.log(`==> ${taskId} ${col} (${m.code})`);
    await captureModel(taskId, col, m.code, 5290 + i);
    i += 1;
  }
}

main().catch((err) => {
  console.error(err.stack || err.message || String(err));
  process.exit(1);
});
