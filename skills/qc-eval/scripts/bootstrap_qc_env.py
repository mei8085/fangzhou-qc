#!/usr/bin/env python3
"""Create and update the repository-level qc-eval virtual environment."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parent.parent
VENV_DIR = REPO_ROOT / ".venv"
REQUIREMENTS = SKILL_DIR / "requirements.txt"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run(args: list[str]) -> None:
    print("$", " ".join(str(arg) for arg in args), flush=True)
    subprocess.check_call(args, cwd=REPO_ROOT)


def venv_is_usable(python: Path) -> bool:
    if not python.exists():
        return False
    result = subprocess.run(
        [str(python), "-c", "import sys; print(sys.version_info[0])"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "3"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="upgrade packages listed in requirements.txt instead of only installing missing packages",
    )
    args = parser.parse_args()

    if not REQUIREMENTS.exists():
        raise SystemExit(f"requirements file not found: {REQUIREMENTS}")

    python = venv_python()
    if not venv_is_usable(python):
        print(f"==> creating virtual environment: {VENV_DIR}")
        run([sys.executable, "-m", "venv", "--clear", str(VENV_DIR)])

    pip_args = [str(python), "-m", "pip", "install", "--disable-pip-version-check"]
    if args.upgrade:
        pip_args.append("--upgrade")
    run(pip_args + ["-r", str(REQUIREMENTS)])

    run(
        [
            str(python),
            "-c",
            "import PIL, cryptography, openpyxl, zstandard; "
            "print('qc-eval Python dependencies: OK')",
        ]
    )
    print(f"==> QC_PYTHON={python}")
    print(f"==> use {python} for all qc-eval Python scripts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
