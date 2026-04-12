"""INFRA-04 — secret hygiene: .env never tracked, .env.example tracked,
.gitignore + .dockerignore + pre-commit hook all in place.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_env_example_is_tracked():
    assert (REPO / ".env.example").is_file()
    result = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", ".env.example"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == ".env.example"


def test_env_is_not_tracked():
    result = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", ".env"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "", f"expected .env untracked; saw: {result.stdout!r}"


def test_gitignore_excludes_env_exactly():
    content = (REPO / ".gitignore").read_text()
    assert re.search(r"(?m)^\.env$", content), ".gitignore must contain a `^.env$` line"


def test_dockerignore_excludes_env_exactly():
    content = (REPO / ".dockerignore").read_text()
    assert re.search(r"(?m)^\.env$", content), ".dockerignore must contain a `^.env$` line"


def test_pre_commit_config_references_gitleaks():
    path = REPO / ".pre-commit-config.yaml"
    assert path.is_file(), "pre-commit config must exist"
    assert "gitleaks" in path.read_text().lower()


def test_env_example_has_no_real_secrets():
    """Belt-and-suspenders: scan .env.example for anything that looks like a
    live API key even if an operator accidentally copies .env over it."""
    content = (REPO / ".env.example").read_text()
    # Anthropic-style real key
    assert not re.search(r"sk-ant-[a-zA-Z0-9_-]{20,}", content), (
        "Looks like a real Anthropic key leaked into .env.example"
    )
    # 32+ char base64-ish tokens (rough heuristic).
    # Ignore placeholder words like "replace-me" which contain hyphens.
    suspicious = re.findall(r"=([A-Za-z0-9+/]{32,})\b", content)
    assert suspicious == [], f"High-entropy values in .env.example: {suspicious!r}"
