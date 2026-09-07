"""Small cross-process safety helpers used by QC workflow scripts."""

from __future__ import annotations

import atexit
import json
import os
import shutil
import socket
import tempfile
import time
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, value: Any) -> None:
    """Write JSON through a sibling temp file so readers never see partial data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def validate_task_id(task_id: str) -> str:
    value = str(task_id).strip()
    if not value or value in {".", ".."} or any(ch in value for ch in "/\\\0"):
        raise ValueError(f"invalid task id: {task_id!r}")
    return value


class DirectoryLock:
    """Portable inter-process lock based on atomic directory creation."""

    def __init__(self, path: Path, *, timeout: float = 300, stale_after: float = 3600):
        self.path = path
        self.timeout = timeout
        self.stale_after = stale_after
        self.acquired = False

    def _owner(self) -> dict[str, Any]:
        try:
            return json.loads((self.path / "owner.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _is_stale(self) -> bool:
        owner = self._owner()
        try:
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            return False
        if owner.get("host") != socket.gethostname():
            return age > self.stale_after
        try:
            pid = int(owner.get("pid", 0))
            if pid <= 0:
                return age > self.stale_after
            os.kill(pid, 0)
            return False
        except (OSError, TypeError, ValueError):
            return True

    def acquire(self) -> "DirectoryLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.path.mkdir()
                atomic_write_json(
                    self.path / "owner.json",
                    {"pid": os.getpid(), "host": socket.gethostname(), "created_at": time.time()},
                )
                self.acquired = True
                atexit.register(self.release)
                return self
            except FileExistsError:
                if self._is_stale():
                    try:
                        shutil.rmtree(self.path)
                    except OSError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    owner = self._owner()
                    raise TimeoutError(f"timed out waiting for lock {self.path}; owner={owner}")
                time.sleep(0.25)

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            shutil.rmtree(self.path)
        except FileNotFoundError:
            pass
        self.acquired = False

    def __enter__(self) -> "DirectoryLock":
        return self.acquire()

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.release()
