from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_X_THREAD = REPO_ROOT / "tests" / "manual" / "smoke_x_thread.py"


def test_smoke_x_thread_refuses_without_arm_flag() -> None:
    result = subprocess.run(
        [sys.executable, str(SMOKE_X_THREAD)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 2, (
        f"expected exit 2, got {result.returncode}; stderr={result.stderr!r}"
    )
    assert "REFUSING: pass --arm-live-post" in result.stderr


def test_smoke_x_thread_armed_without_env_fails_fast() -> None:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYDANTIC_SETTINGS_DISABLE_ENV_FILE": "1",
        "SMOKE_X_THREAD_DISABLE_DOCKER_REEXEC": "1",
    }
    result = subprocess.run(
        [sys.executable, str(SMOKE_X_THREAD), "--arm-live-post"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )
    assert result.returncode != 0, (
        f"expected non-zero exit, got 0; stdout={result.stdout!r}"
    )
    assert result.returncode != 2, (
        "argparse gate should have passed with --arm-live-post; "
        f"got exit 2 with stderr={result.stderr!r}"
    )
    assert "Configuration error" in result.stderr, (
        f"expected 'Configuration error' in stderr; got={result.stderr!r}"
    )
