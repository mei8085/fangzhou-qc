"""Per-model venv lifecycle for fullstack verify.

Each model gets its own venv under tasks/<TASK_ID>/venv_<CODE>/; we cache the
sha1 of the model's requirements.txt in `.installed.sha1` so re-runs skip pip
install when nothing changed.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path


def ensure(venv_dir: Path, requirements: Path) -> Path:
    """Ensure venv exists with requirements installed. Returns path to python.exe."""
    python_bin = _python_bin(venv_dir)
    if not python_bin.exists():
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True, capture_output=True, text=True,
        )

    stamp = venv_dir / ".installed.sha1"
    req_hash = _sha1(requirements)
    if stamp.exists() and stamp.read_text().strip() == req_hash:
        return python_bin

    # install
    subprocess.run(
        [str(python_bin), "-m", "pip", "install", "--quiet",
         "--disable-pip-version-check", "--prefer-binary",
         "-r", str(requirements)],
        check=True, capture_output=False, text=True,
    )
    stamp.write_text(req_hash, encoding="utf-8")
    return python_bin


def _python_bin(venv_dir: Path) -> Path:
    if (venv_dir / "Scripts" / "python.exe").exists() or venv_dir.name.startswith("venv_"):
        # Windows layout (also the default target when creating on Windows)
        candidate = venv_dir / "Scripts" / "python.exe"
        if candidate.exists() or (venv_dir / "Scripts").exists():
            return candidate
    return venv_dir / "bin" / "python"


def _sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()
