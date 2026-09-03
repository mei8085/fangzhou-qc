#!/usr/bin/env python3
"""Run Next.js / Node verification for one QC task on the u03l test host.

This is a centralized helper for tasks where the user explicitly asks to use
u03l for Node/Next verification even though no Postgres/Redis/Celery stack is
required. It syncs extracted model workspaces through u03l.py, runs dependency
installation, build, and safe verification scripts on u03l, then stores
sanitized logs under tasks/<TASK_ID>/logs/ for compose_cli.py.

Usage:
  python3 skills/qc-eval/scripts/verify_next_u03l.py <TASK_ID>
  python3 skills/qc-eval/scripts/verify_next_u03l.py <TASK_ID> --only <MODEL>
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
REPO_ROOT = SKILL_DIR.parent.parent
sys.path.insert(0, str(HERE))

from lib import remote_config as rc  # noqa: E402

SSH_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8",
    "-o", "StrictHostKeyChecking=accept-new",
]
DEFAULT_REMOTE_CHROME = "/home/fz/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome"


def run_local(cmd: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def ssh(cmd: str, *, timeout: int = 240) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", *SSH_OPTS, rc.SSH_HOST, cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def load_models(task_id: str) -> dict[str, dict]:
    path = REPO_ROOT / "tasks" / task_id / "model_map.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("models") or {}


def package_scripts(local_code_dir: Path) -> dict[str, str]:
    pkg = local_code_dir / "package.json"
    if not pkg.exists():
        return {}
    return json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}


def choose_commands(model: str, local_code_dir: Path) -> list[list[str]]:
    """Pick commands that are useful and reasonably bounded for QC evidence."""
    commands: list[list[str]] = [["npm", "ci"], ["npm", "run", "build"]]
    scripts = package_scripts(local_code_dir)
    if "typecheck" in scripts:
        commands.append(["npm", "run", "typecheck"])
    verify_scripts = [name for name in scripts if name.startswith("verify") and name != "verify:render"]
    for name in sorted(verify_scripts):
        commands.append(["npm", "run", name])

    if not verify_scripts:
        scripts_dir = local_code_dir / "scripts"
        if (scripts_dir / "verify-batch.mjs").exists():
            if (scripts_dir / "ts-resolve-hook.mjs").exists():
                commands.append(["node", "--experimental-strip-types", "scripts/verify-batch.mjs"])
            else:
                commands.append(["node", "scripts/verify-batch.mjs"])
        if (scripts_dir / "verify-qc.mjs").exists():
            if (scripts_dir / "ts-resolve-hook.mjs").exists():
                commands.append([
                    "node", "--experimental-strip-types", "--import",
                    "./scripts/ts-resolve-hook.mjs", "scripts/verify-qc.mjs",
                ])
            else:
                commands.append(["node", "scripts/verify-qc.mjs"])
        for name in ("verify-library.mjs", "verify-assets.mjs"):
            if (scripts_dir / name).exists():
                if (scripts_dir / "ts-resolve-hook.mjs").exists():
                    commands.append([
                        "node", "--experimental-strip-types", "--import",
                        "./scripts/ts-resolve-hook.mjs", f"scripts/{name}",
                    ])
                else:
                    commands.append(["node", f"scripts/{name}"])
    return commands


def sanitize_log(text: str, task_id: str, model: str) -> str:
    remote_code = str(rc.remote_model_dir(task_id, model) / "project" / "code")
    remote_model = str(rc.remote_model_dir(task_id, model))
    text = text.replace(remote_code, f"<repo>/tasks/{task_id}/extracted/{model}/project/code")
    text = text.replace(remote_model, f"<repo>/tasks/{task_id}/extracted/{model}")
    # u03l temporary directories are not relevant to the QC conclusion.
    text = text.replace("/home/fz/qc-eval", "<u03l-qc-eval>")
    text = text.replace("/fz-workspace/qc-eval", "<u03l-qc-eval>")
    return text


def run_remote_command(task_id: str, model: str, cmd: list[str], timeout: int) -> tuple[int, str]:
    remote_code = rc.remote_model_dir(task_id, model) / "project" / "code"
    shell_cmd = (
        f"cd {shlex.quote(str(remote_code))} && "
        f"export CHROME_PATH={shlex.quote(DEFAULT_REMOTE_CHROME)} "
        f"PUPPETEER_EXECUTABLE_PATH={shlex.quote(DEFAULT_REMOTE_CHROME)}; "
        f"PATH=/usr/local/bin:/usr/bin:/bin:$PATH "
        f"{shlex.join(cmd)}"
    )
    proc = ssh(shell_cmd, timeout=timeout)
    out = f"$ {shlex.join(cmd)}\n{proc.stdout}{proc.stderr}"
    return proc.returncode, sanitize_log(out, task_id, model)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--only", default="", help="只验证指定表头模型名")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()

    check = run_local([sys.executable, str(HERE / "u03l.py"), "check-host"], timeout=30)
    if check.returncode != 0:
        sys.stderr.write(check.stdout + check.stderr)
        return check.returncode

    models = load_models(args.task_id)
    if args.only:
        models = {k: v for k, v in models.items() if k == args.only or v.get("code") == args.only}
    if not models:
        print("ERROR: no model matched", file=sys.stderr)
        return 2

    codes = list(models.keys())
    sync = run_local([sys.executable, str(HERE / "u03l.py"), "sync-code", args.task_id, *codes], timeout=300)
    if sync.returncode != 0:
        sys.stderr.write(sync.stdout + sync.stderr)
        return sync.returncode

    log_dir = REPO_ROOT / "tasks" / args.task_id / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    summary: list[dict] = []
    for model in codes:
        local_code_dir = REPO_ROOT / "tasks" / args.task_id / "extracted" / model / "project" / "code"
        lines: list[str] = [f"# u03l verification for {model}", ""]
        for cmd in choose_commands(model, local_code_dir):
            print(f"==> {model}: {shlex.join(cmd)}")
            try:
                rc_code, text = run_remote_command(args.task_id, model, cmd, args.timeout)
            except subprocess.TimeoutExpired:
                rc_code, text = 124, f"$ {shlex.join(cmd)}\n[TIMEOUT after {args.timeout}s]\n"
            lines.append(text.rstrip())
            lines.append(f"exit={rc_code}")
            lines.append("")
            summary.append({"model": model, "command": shlex.join(cmd), "exit": rc_code})
        out = log_dir / f"{model}-cli-u03l.log"
        out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        print(f"    wrote {out.relative_to(REPO_ROOT)}")

    summary_path = REPO_ROOT / "tasks" / args.task_id / "logs" / "u03l_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"==> wrote {summary_path.relative_to(REPO_ROOT)}")
    failures = [item for item in summary if item["exit"] != 0]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
