#!/usr/bin/env python3
"""SSH port-forward lifecycle for a task's postgres/redis on u03l.

State kept in ~/.qc-eval/tunnels/<TASK_ID>.json so parallel sessions don't
clobber each other (each task has its own file).

Tunnels are long-running background ssh processes. On Windows we spawn them
DETACHED so they survive the launcher (verify_fullstack.py) exiting; we only
kill them on explicit `close`.

CLI
    python tunnel.py open  TASK_ID --postgres-remote N --redis-remote M
    python tunnel.py close TASK_ID
    python tunnel.py status TASK_ID
    python tunnel.py heal  TASK_ID
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from lib import port_alloc, remote_config as rc

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

STATE_DIR = Path.home() / ".qc-eval" / "tunnels"
STATE_DIR.mkdir(parents=True, exist_ok=True)


def _state_path(task_id: str) -> Path:
    return STATE_DIR / f"{task_id}.json"


def _load(task_id: str) -> dict:
    p = _state_path(task_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save(task_id: str, state: dict) -> None:
    _state_path(task_id).write_text(json.dumps(state, indent=2), encoding="utf-8")


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        # Windows: `tasklist` filter on PID
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True,
        )
        return str(pid) in r.stdout
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _tcp_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _spawn_ssh_forward(local_port: int, remote_port: int) -> int:
    """Spawn `ssh -N -L localport:localhost:remoteport u03l` detached.

    Returns the process PID. The child will keep running after this process
    exits. Kill via `close(task_id)`.
    """
    args = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-N",
        "-L", f"{local_port}:localhost:{remote_port}",
        rc.SSH_HOST,
    ]
    if os.name == "nt":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        p = subprocess.Popen(
            args,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    else:
        p = subprocess.Popen(
            args,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    # give it a moment to bind
    time.sleep(0.6)
    return p.pid


def _kill(pid: int) -> None:
    if not pid:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                       capture_output=True, text=True)
    else:
        try:
            os.kill(pid, 15)
            time.sleep(0.3)
            os.kill(pid, 9)
        except OSError:
            pass


# ---------- public ----------

def open(task_id: str, postgres_remote: int, redis_remote: int,
         *, force: bool = False) -> dict:
    """Idempotent: reuse alive tunnels; spawn missing / dead ones."""
    state = _load(task_id)
    base = port_alloc.base_for(task_id)

    updated = {}
    for kind, remote in [("postgres", postgres_remote), ("redis", redis_remote)]:
        prev = state.get(kind, {})
        if not force and prev.get("remote") == remote and _pid_alive(prev.get("pid", 0)):
            # already forwarded; check the local port is still bound (from OUR side)
            # If port is free, ssh died silently — respawn.
            if not _tcp_free(prev["local"]):
                updated[kind] = prev
                continue
            _kill(prev["pid"])
        # spawn fresh
        local = port_alloc.pick_free(base[kind])
        pid = _spawn_ssh_forward(local, remote)
        updated[kind] = {"pid": pid, "local": local, "remote": remote}

    state.update(updated)
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save(task_id, state)
    return {k: state[k] for k in ("postgres", "redis")}


def close(task_id: str) -> None:
    state = _load(task_id)
    for kind in ("postgres", "redis"):
        info = state.get(kind, {})
        _kill(info.get("pid", 0))
    p = _state_path(task_id)
    if p.exists():
        p.unlink()


def status(task_id: str) -> dict:
    state = _load(task_id)
    out = {}
    for kind in ("postgres", "redis"):
        info = state.get(kind, {})
        pid = info.get("pid", 0)
        alive = _pid_alive(pid) if pid else False
        listening = not _tcp_free(info["local"]) if "local" in info else False
        out[kind] = {**info, "alive": alive, "listening": listening}
    return out


def heal(task_id: str) -> bool:
    """Respawn any tunnel whose pid is dead or whose local port is not bound."""
    state = _load(task_id)
    changed = False
    for kind in ("postgres", "redis"):
        info = state.get(kind, {})
        if "remote" not in info:
            continue
        pid = info.get("pid", 0)
        if _pid_alive(pid) and not _tcp_free(info["local"]):
            continue
        _kill(pid)
        local = port_alloc.pick_free(port_alloc.base_for(task_id)[kind])
        info["local"] = local
        info["pid"] = _spawn_ssh_forward(local, info["remote"])
        state[kind] = info
        changed = True
    if changed:
        state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _save(task_id, state)
    return changed


# ---------- CLI ----------

def _cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="tunnel.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("open")
    sp.add_argument("task_id")
    sp.add_argument("--postgres-remote", type=int, required=True)
    sp.add_argument("--redis-remote", type=int, required=True)
    sp.add_argument("--force", action="store_true")

    sp = sub.add_parser("close")
    sp.add_argument("task_id")

    sp = sub.add_parser("status")
    sp.add_argument("task_id")

    sp = sub.add_parser("heal")
    sp.add_argument("task_id")

    args = p.parse_args(argv)
    if args.cmd == "open":
        r = open(args.task_id, args.postgres_remote, args.redis_remote, force=args.force)
        print(json.dumps(r, indent=2))
        return 0
    if args.cmd == "close":
        close(args.task_id)
        print("closed")
        return 0
    if args.cmd == "status":
        print(json.dumps(status(args.task_id), indent=2))
        return 0
    if args.cmd == "heal":
        print("healed" if heal(args.task_id) else "already healthy")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
