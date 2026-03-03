"""Development runner for VECTIQOR backend + frontend."""

from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path


def main() -> None:
    package_dir = Path(__file__).resolve().parents[2]
    frontend_dir = package_dir / "frontend"

    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "vectiqor.server:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
                "--reload",
                "--no-access-log",
            ],
            cwd=package_dir,
        ),
        subprocess.Popen(["pnpm", "dev"], cwd=frontend_dir),
    ]

    try:
        exit_code = 0
        while True:
            for process in processes:
                code = process.poll()
                if code is not None:
                    exit_code = code
                    raise KeyboardInterrupt
            signal.pause()
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    raise SystemExit(exit_code)
