#!/usr/bin/env python3
"""Run ELADMIN Vue frontends on u03l and capture governance page screenshots.

This is a task-specific verifier for ELADMIN-style projects where the normal
FastAPI/Vite full-stack verifier does not apply. It works on temporary copies:

1. copy each model's eladmin-web-master into tmp/
2. inject a preview /governance route and mock governance API responses
3. sync the temporary copies to u03l
4. run npm/vue-cli-service on u03l
5. capture screenshots locally through an SSH tunnel with Playwright
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(HERE))

import u03l  # noqa: E402
from lib import remote_config as rc  # noqa: E402


SSH_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=5",
    "-o", "StrictHostKeyChecking=accept-new",
]


def log(msg: str) -> None:
    print(f"  [eladmin-front] {msg}", flush=True)


def run(cmd: list[str], *, timeout: int = 60, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=check)


def ssh(cmd: str, *, timeout: int = 60, check: bool = True) -> subprocess.CompletedProcess:
    return run(["ssh", *SSH_OPTS, rc.SSH_HOST, cmd], timeout=timeout, check=check)


def pick_free_port(start: int) -> int:
    for port in range(start, start + 200):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"no free port from {start}")


def sync_dir(local_dir: Path, remote_dir: str) -> None:
    ssh(f"rm -rf {quote(remote_dir)} && mkdir -p {quote(remote_dir)}", timeout=60)
    proc = subprocess.Popen(
        ["ssh", *SSH_OPTS, rc.SSH_HOST, f"tar -x -C {quote(remote_dir)}"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert proc.stdin is not None
        with tarfile.open(fileobj=proc.stdin, mode="w|") as tf:
            for item in sorted(local_dir.rglob("*")):
                rel = item.relative_to(local_dir)
                parts = set(rel.parts)
                if parts & {"node_modules", "dist", ".git"}:
                    continue
                tf.add(item, arcname=str(rel))
        proc.stdin.close()
        stdout, stderr = proc.communicate(timeout=300)
    except Exception:
        proc.kill()
        raise
    if proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, proc.args, stdout, stderr)


def quote(s: str) -> str:
    import shlex
    return shlex.quote(str(s))


MOCK_REQUEST = r"""
const sampleAssets = [
  { id: 1, uid: 'LOCAL:1', assetKey: 'LOCAL:1', source: 'LOCAL', name: 'contract.pdf', fileName: 'contract.pdf', realName: '合同扫描件.pdf', category: '文档', suffix: 'pdf', extension: 'pdf', type: 'pdf', size: '2.4 MB', createBy: 'ops_admin', uploadBy: 'ops_admin', createTime: '2026-08-01 10:12:00', uploadTime: '2026-08-01 10:12:00', lifeStatus: 'ACTIVE', lifecycleState: 'ACTIVE', overSize: false, overRetention: false, purgeDueInDays: 12 },
  { id: 2, uid: 'S3:2', assetKey: 'S3:2', source: 'S3', name: 'archive.zip', fileName: 'archive.zip', realName: '历史归档.zip', category: '其他', suffix: 'zip', extension: 'zip', type: 'zip', size: '86 MB', createBy: 'maintainer', uploadBy: 'maintainer', createTime: '2026-07-12 09:20:00', uploadTime: '2026-07-12 09:20:00', lifeStatus: 'RECYCLED', lifecycleState: 'RECYCLED', recycledAt: '2026-08-10 14:22:00', recycledTime: '2026-08-10 14:22:00', recycleTime: '2026-08-10 14:22:00', purgeDueInDays: -2 },
  { id: 3, uid: 'LOCAL:3', assetKey: 'LOCAL:3', source: 'LOCAL', name: 'photo.png', fileName: 'photo.png', realName: '现场照片.png', category: '图片', suffix: 'png', extension: 'png', type: 'png', size: '640 KB', createBy: 'operator', uploadBy: 'operator', createTime: '2026-08-08 16:45:00', uploadTime: '2026-08-08 16:45:00', lifeStatus: 'ACTIVE', lifecycleState: 'ACTIVE', overSize: true, overRetention: true, purgeDueInDays: 30 }
]
const policies = [
  { id: 1, category: '*', extension: null, retainDays: -1, maxSizeMb: null, recycleEnabled: true, recycleRetentionDays: 30, enabled: true, description: '安全默认策略' },
  { id: 2, category: '图片', extension: 'png', retainDays: 180, maxSizeMb: 20, recycleEnabled: true, recycleRetentionDays: 45, enabled: true, description: '图片文件保留规则' }
]
const operations = [
  { id: 1, createBy: 'ops_admin', operator: 'ops_admin', operationType: 'PRECHECK', action: 'PRECHECK', source: 'ALL', affectedCount: 3, successCount: 3, failCount: 0, failedCount: 0, status: 'SUCCESS', criteriaSummary: 'source=ALL, lifecycle=ACTIVE', failReasonSummary: '', startTime: '2026-08-16 10:00:00', endTime: '2026-08-16 10:00:01' },
  { id: 2, createBy: 'ops_admin', operator: 'ops_admin', operationType: 'RECYCLE', action: 'RECYCLE', source: 'LOCAL', affectedCount: 1, successCount: 1, failCount: 0, failedCount: 0, status: 'SUCCESS', criteriaSummary: 'asset=LOCAL:1', failReasonSummary: '', startTime: '2026-08-16 10:01:00', endTime: '2026-08-16 10:01:02' }
]
const page = data => ({ content: data, totalElements: data.length, total: data.length, records: data, rows: data })
function precheckResult() {
  return {
    snapshotToken: 'mock-preview-token',
    token: 'mock-preview-token',
    totalCount: 3,
    operableCount: 2,
    inoperableCount: 1,
    successCount: 0,
    failCount: 0,
    bySource: { LOCAL: 2, S3: 1 },
    byCategory: { 文档: 1, 图片: 1, 其他: 1 },
    objectStorageAvailable: false,
    operablePreview: sampleAssets.slice(0, 2),
    inoperableItems: [{ ...sampleAssets[1], reason: '已在回收站，不能重复回收' }],
    inoperableTruncated: false,
    items: sampleAssets,
    details: sampleAssets.map(item => ({ ...item, success: true, message: '可操作' }))
  }
}
function executeResult() {
  return {
    status: 'SUCCESS',
    successCount: 2,
    failCount: 0,
    failedCount: 0,
    failedItems: [],
    details: [{ success: true, message: '操作成功' }]
  }
}
function respond(config) {
  const url = String((config && config.url) || '')
  const method = String((config && config.method) || 'get').toLowerCase()
  if (/stats|overview/.test(url)) return { localActiveCount: 8, localRecycledCount: 2, s3ActiveCount: 5, s3RecycledCount: 1, overRetentionCount: 3, totalCount: 16 }
  if (/policy|policies/.test(url) && method === 'get') return page(policies)
  if (/log|operation|history/.test(url)) return page(operations)
  if (/recycleBin|recycle-bin/.test(url)) return page(sampleAssets.filter(x => x.lifecycleState === 'RECYCLED' || x.lifeStatus === 'RECYCLED'))
  if (/asset|fileGovernance/.test(url) && method === 'get') return page(sampleAssets)
  if (/precheck|preview/.test(url)) return precheckResult()
  if (/execute|recycle|restore|purge/.test(url)) return executeResult()
  return page(sampleAssets)
}
export default function request(config) {
  return Promise.resolve(respond(config || {}))
}
"""


MOCK_GOVERNANCE_API = r"""
const assets = [
  { id: 1, assetKey: 'LOCAL:1', source: 'LOCAL', fileName: 'contract.pdf', name: 'contract.pdf', realName: '合同扫描件.pdf', category: '文档', extension: 'pdf', suffix: 'pdf', type: 'pdf', size: '2.4 MB', uploadBy: 'ops_admin', createBy: 'ops_admin', uploadTime: '2026-08-01 10:12:00', createTime: '2026-08-01 10:12:00', lifecycleState: 'ACTIVE', lifeStatus: 'ACTIVE', purgeDueInDays: 12 },
  { id: 2, assetKey: 'S3:2', source: 'S3', fileName: 'archive.zip', name: 'archive.zip', realName: '历史归档.zip', category: '其他', extension: 'zip', suffix: 'zip', type: 'zip', size: '86 MB', uploadBy: 'maintainer', createBy: 'maintainer', uploadTime: '2026-07-12 09:20:00', createTime: '2026-07-12 09:20:00', lifecycleState: 'RECYCLED', lifeStatus: 'RECYCLED', recycledAt: '2026-08-10 14:22:00', recycleTime: '2026-08-10 14:22:00', purgeDueInDays: -2 }
]
const policies = [
  { id: 1, category: '*', extension: null, retainDays: -1, maxSizeMb: null, recycleEnabled: true, recycleRetentionDays: 30, enabled: true, description: '安全默认策略' },
  { id: 2, category: '图片', extension: 'png', retainDays: 180, maxSizeMb: 20, recycleEnabled: true, recycleRetentionDays: 45, enabled: true, description: '图片文件保留规则' }
]
const operations = [
  { id: 1, createBy: 'ops_admin', operationType: 'PRECHECK', source: 'ALL', affectedCount: 2, successCount: 2, failedCount: 0, failCount: 0, status: 'SUCCESS', criteriaSummary: 'source=ALL', failReasonSummary: '', startTime: '2026-08-16 10:00:00', endTime: '2026-08-16 10:00:01' }
]
const page = data => ({ content: data, totalElements: data.length, total: data.length, records: data, rows: data })
const precheckResult = () => ({ snapshotToken: 'mock-token', token: 'mock-token', totalCount: 2, operableCount: 1, inoperableCount: 1, bySource: { LOCAL: 1, S3: 1 }, byCategory: { 文档: 1, 其他: 1 }, objectStorageAvailable: false, operablePreview: [assets[0]], inoperableItems: [{ ...assets[1], reason: '已在回收站' }], inoperableTruncated: false, items: assets })
const executeResult = () => ({ status: 'SUCCESS', successCount: 1, failCount: 0, failedCount: 0, failedItems: [], details: [{ success: true, message: '操作成功' }] })
export function getAssets() { return Promise.resolve(page(assets)) }
export function getPolicies() { return Promise.resolve(page(policies)) }
export function addPolicy() { return Promise.resolve({}) }
export function editPolicy() { return Promise.resolve({}) }
export function delPolicy() { return Promise.resolve({}) }
export function delPolicies() { return Promise.resolve({}) }
export function getOperations() { return Promise.resolve(page(operations)) }
export function getStats() { return Promise.resolve({ localActiveCount: 8, localRecycledCount: 2, s3ActiveCount: 5, s3RecycledCount: 1, overRetentionCount: 3 }) }
export function overview() { return Promise.resolve({ localActiveCount: 8, localRecycledCount: 2, s3ActiveCount: 5, s3RecycledCount: 1, overRetentionCount: 3 }) }
export function precheck() { return Promise.resolve(precheckResult()) }
export function precheckRecycle() { return Promise.resolve(precheckResult()) }
export function precheckPurge() { return Promise.resolve(precheckResult()) }
export function previewRecycle() { return Promise.resolve(precheckResult()) }
export function execute() { return Promise.resolve(executeResult()) }
export function executeRecycle() { return Promise.resolve(executeResult()) }
export function executeRestore() { return Promise.resolve(executeResult()) }
export function executePurge() { return Promise.resolve(executeResult()) }
export function recycle() { return Promise.resolve(executeResult()) }
export function restore() { return Promise.resolve(executeResult()) }
export function purge() { return Promise.resolve(executeResult()) }
export function restoreRecords() { return Promise.resolve(executeResult()) }
export function purgeRecords() { return Promise.resolve(executeResult()) }
export function getRecycleBin() { return Promise.resolve(page(assets.filter(x => x.lifecycleState === 'RECYCLED'))) }
export function getGovernanceLogs() { return Promise.resolve(page(operations)) }
export function createHold() { return Promise.resolve({}) }
export function releaseHolds() { return Promise.resolve(executeResult()) }
export default { getAssets, getPolicies, addPolicy, editPolicy, delPolicy, delPolicies, getOperations, getStats, overview, precheck, execute, recycle, restore, purge, precheckRecycle, precheckPurge, previewRecycle, executeRecycle, executeRestore, executePurge, restoreRecords, purgeRecords, getRecycleBin, getGovernanceLogs, createHold, releaseHolds }
"""


def patch_frontend(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns("node_modules", "dist", ".git", ".cache"),
    )

    main = dst / "src" / "main.js"
    text = main.read_text(encoding="utf-8")
    text = text.replace("import './router/index' // permission control", "// preview mode: permission control disabled")
    main.write_text(text, encoding="utf-8")

    user = dst / "src" / "store" / "modules" / "user.js"
    text = user.read_text(encoding="utf-8")
    text = text.replace("roles: [],", "roles: ['admin'],")
    user.write_text(text, encoding="utf-8")

    routers = dst / "src" / "router" / "routers.js"
    text = routers.read_text(encoding="utf-8")
    text = text.replace("redirect: '/dashboard',", "redirect: '/governance/index',", 1)
    route = """
  {
    path: '/governance',
    component: Layout,
    redirect: '/governance/index',
    children: [
      {
        path: 'index',
        component: (resolve) => require(['@/views/tools/governance/index'], resolve),
        name: 'FileGovernancePreview',
        meta: { title: '文件资产治理', icon: 'file', noCache: true }
      }
    ]
  }
"""
    marker = "\n]\n\nexport default"
    if marker not in text:
        raise RuntimeError(f"router marker not found in {routers}")
    text = text.replace(marker, ",\n" + route + marker, 1)
    routers.write_text(text, encoding="utf-8")

    request = dst / "src" / "utils" / "request.js"
    request.write_text(MOCK_REQUEST.strip() + "\n", encoding="utf-8")

    api_dir = dst / "src" / "api" / "tools"
    api_dir.mkdir(parents=True, exist_ok=True)
    (api_dir / "fileGovernance.js").write_text(MOCK_GOVERNANCE_API.strip() + "\n", encoding="utf-8")
    (api_dir / "governance.js").write_text(MOCK_GOVERNANCE_API.strip() + "\n", encoding="utf-8")


def load_frontends(task_id: str) -> dict[str, Path]:
    mm = json.loads((REPO_ROOT / "tasks" / task_id / "model_map.json").read_text(encoding="utf-8"))
    out: dict[str, Path] = {}
    for model in mm["sheet_columns"]:
        entry = REPO_ROOT / mm["models"][model]["entry"]
        front = entry / "eladmin-web-master"
        if not front.exists():
            raise FileNotFoundError(front)
        out[model] = front
    return out


def install_remote(remote_base: str, models: list[str]) -> None:
    model_list = " ".join(models)
    cmd = f"""
set -e
cd {quote(remote_base)}
if [ ! -x _deps/node_modules/.bin/vue-cli-service ]; then
  rm -rf _deps
  mkdir -p _deps
  cp summit/package.json _deps/package.json
  if [ -f summit/package-lock.json ]; then cp summit/package-lock.json _deps/package-lock.json; fi
  if [ -f summit/postcss.config.js ]; then cp summit/postcss.config.js _deps/postcss.config.js; fi
  cd _deps
  npm install --legacy-peer-deps --no-audit --no-fund
  cd ..
fi
if [ -f summit/postcss.config.js ]; then cp summit/postcss.config.js _deps/postcss.config.js; fi
for m in {model_list}; do
  rm -rf "$m/node_modules"
  ln -s ../_deps/node_modules "$m/node_modules"
done
"""
    r = ssh("bash -lc " + quote(cmd), timeout=600, check=False)
    if r.returncode:
        raise RuntimeError(f"remote npm install failed\nstdout:\n{r.stdout[-4000:]}\nstderr:\n{r.stderr[-4000:]}")


def start_tunnel(local_port: int, remote_port: int) -> subprocess.Popen:
    return subprocess.Popen(
        ["ssh", *SSH_OPTS, "-N", "-L", f"{local_port}:localhost:{remote_port}", rc.SSH_HOST],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def start_remote_dev(remote_dir: str, remote_port: int) -> subprocess.Popen:
    cmd = (
        f"cd {quote(remote_dir)} && "
        "export NODE_OPTIONS=--openssl-legacy-provider && "
        f"./node_modules/.bin/vue-cli-service serve --host 127.0.0.1 --port {remote_port} --no-open"
    )
    return subprocess.Popen(
        ["ssh", *SSH_OPTS, rc.SSH_HOST, "bash -lc " + quote(cmd)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def wait_http(url: str, timeout: int = 120) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if 200 <= r.status < 500:
                    return True
        except Exception:
            time.sleep(1)
    return False


def capture(url: str, out: Path) -> None:
    pw = (REPO_ROOT / "skills" / "qc-eval" / "node_modules" / "playwright").as_posix()
    js = f"""
const {{ chromium }} = require({json.dumps(pw)});
(async () => {{
  const browser = await chromium.launch({{ headless: true }});
  const page = await browser.newPage({{ viewport: {{ width: 1440, height: 1000 }}, deviceScaleFactor: 1 }});
  page.on('pageerror', err => console.log('pageerror:', err.message));
  page.on('console', msg => console.log('console:', msg.type(), msg.text()));
  await page.goto({json.dumps(url)}, {{ waitUntil: 'networkidle', timeout: 90000 }});
  await page.waitForTimeout(2500);
  await page.screenshot({{ path: {json.dumps(str(out))}, fullPage: true }});
  await browser.close();
}})().catch(err => {{ console.error(err); process.exit(1); }});
"""
    r = run(["node", "-e", js], timeout=120, check=False)
    if r.returncode:
        raise RuntimeError(f"playwright capture failed\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}")


def compose_horizontal(paths: list[Path], out: Path) -> None:
    from PIL import Image
    imgs = [Image.open(p).convert("RGB") for p in paths]
    h = max(i.height for i in imgs)
    w = sum(i.width for i in imgs)
    dst = Image.new("RGB", (w, h), (18, 22, 28))
    x = 0
    for im in imgs:
        dst.paste(im, (x, 0))
        x += im.width
    dst.save(out)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("task_id")
    p.add_argument("--only", choices=["summit", "rudder", "quarry", "pelican"])
    args = p.parse_args(argv)

    task_id = args.task_id
    u03l.check_host()

    frontends = load_frontends(task_id)
    models = [args.only] if args.only else ["summit", "rudder", "quarry", "pelican"]
    tmp_base = REPO_ROOT / "tmp" / "eladmin_front_preview" / task_id
    if tmp_base.exists():
        shutil.rmtree(tmp_base)
    tmp_base.mkdir(parents=True, exist_ok=True)

    for model in models:
        log(f"patch temp frontend: {model}")
        patch_frontend(frontends[model], tmp_base / model)

    remote_base = f"/home/fz/qc-eval/tasks/{task_id}_eladmin_front"
    log(f"sync temp frontends to u03l: {remote_base}")
    sync_dir(tmp_base, remote_base)

    log("npm install shared dependencies on u03l")
    install_remote(remote_base, models)

    out_dir = REPO_ROOT / "delivery" / task_id / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict[str, str]] = {}

    for idx, model in enumerate(models):
        remote_port = 18130 + idx
        local_port = pick_free_port(19130 + idx)
        remote_dir = f"{remote_base}/{model}"
        dev = None
        tunnel = None
        try:
            log(f"{model}: start vue-cli on u03l :{remote_port}")
            dev = start_remote_dev(remote_dir, remote_port)
            tunnel = start_tunnel(local_port, remote_port)
            url = f"http://127.0.0.1:{local_port}/"
            if not wait_http(url, timeout=150):
                raise RuntimeError(f"{model}: frontend server did not become ready")
            out = out_dir / f"{model}_03_frontend.png"
            log(f"{model}: capture {url}")
            capture(url, out)
            existing = [out_dir / f"{model}_01_cli.png", out_dir / f"{model}_02_cli.png", out]
            existing = [x for x in existing if x.exists()]
            compose_horizontal(existing, out_dir / f"{model}_verify.png")
            summary[model] = {"status": "ok", "screenshot": str(out.relative_to(REPO_ROOT))}
        except Exception as exc:
            summary[model] = {"status": "failed", "error": str(exc)}
            print(f"  [eladmin-front][fail] {model}: {exc}", file=sys.stderr)
        finally:
            if dev and dev.poll() is None:
                dev.terminate()
                try:
                    dev.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    dev.kill()
            if tunnel and tunnel.poll() is None:
                tunnel.terminate()
                try:
                    tunnel.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    tunnel.kill()
            ssh(f"pkill -f 'vue-cli-service serve.*{remote_port}' || true", timeout=20, check=False)

    summary_path = REPO_ROOT / "tasks" / task_id / "logs" / "eladmin_frontend_u03l_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"summary -> {summary_path.relative_to(REPO_ROOT)}")
    return 0 if all(v.get("status") == "ok" for v in summary.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
