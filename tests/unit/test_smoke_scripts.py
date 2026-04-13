"""Unit tests for Phase 3 smoke-script safety gates.

Scope (per 03-VALIDATION.md "Cross-cutting — `--arm-live-post` gate test"):

- Verify ``scripts/smoke_x_post.py`` refuses to run without ``--arm-live-post``
  (T-03-02 / D-03). This proves the safety gate fires BEFORE any Settings load
  or network activity.
- Verify ``scripts/smoke_x_post.py`` with the flag, but without required
  secrets in env, fails fast at ``load_settings()`` with
  ``Configuration error`` on stderr — proving no network call is attempted
  when configuration is invalid.

Both tests use ``subprocess.run(...)`` to invoke the script as a CLI. We do
NOT import the script as a module (the ``scripts/`` dir intentionally has no
``__init__.py`` per CONTEXT D-01). No SDKs are mocked — neither test reaches
past the argparse gate / Settings load.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_X_POST = REPO_ROOT / "scripts" / "smoke_x_post.py"


def test_smoke_x_post_refuses_without_arm_flag() -> None:
    """Running the script with no flags must exit 2 with REFUSING banner.

    No env scrubbing is needed — the gate fires before any env access.
    """
    result = subprocess.run(
        [sys.executable, str(SMOKE_X_POST)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 2, (
        f"expected exit 2, got {result.returncode}; stderr={result.stderr!r}"
    )
    assert "REFUSING: pass --arm-live-post" in result.stderr


def test_smoke_x_post_armed_without_env_fails_fast() -> None:
    """Armed run without required secrets must fail fast at load_settings().

    Constructs a minimal env that deliberately omits the Anthropic/X/Postgres
    secrets AND disables ``.env`` loading so pydantic-settings can't rescue
    them from disk. Expect non-zero exit code (not 2 — argparse gate passed)
    and 'Configuration error' in stderr.
    """
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYDANTIC_SETTINGS_DISABLE_ENV_FILE": "1",
        # Deliberately NOT setting ANTHROPIC_API_KEY, X_*, POSTGRES_PASSWORD.
    }
    result = subprocess.run(
        [sys.executable, str(SMOKE_X_POST), "--arm-live-post"],
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
