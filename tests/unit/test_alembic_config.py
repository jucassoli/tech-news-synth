"""T-02-01 / T-02-02 — alembic.ini secrets-hygiene assertions.

`alembic.ini` is checked into the repo. It MUST NOT contain a populated
`sqlalchemy.url` line: the DSN materializes at runtime in `env.py` from
`load_settings().database_url`. Alembic + sqlalchemy loggers must be set
to WARN so SA INFO output cannot echo connection-string fragments.
"""

from __future__ import annotations

import configparser
from pathlib import Path

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def test_alembic_ini_exists() -> None:
    assert ALEMBIC_INI.exists(), f"alembic.ini missing at {ALEMBIC_INI}"


def test_alembic_ini_has_no_sqlalchemy_url() -> None:
    """T-02-01: DSN must not land in the checked-in config."""
    cp = configparser.ConfigParser()
    cp.read(ALEMBIC_INI)
    url = cp["alembic"].get("sqlalchemy.url", "").strip()
    assert url == "", f"alembic.ini leaks sqlalchemy.url = {url!r}"


def test_alembic_ini_script_location_is_alembic() -> None:
    cp = configparser.ConfigParser()
    cp.read(ALEMBIC_INI)
    assert cp["alembic"].get("script_location", "").strip() == "alembic"


def test_alembic_loggers_are_warn_level() -> None:
    """T-02-02: prevents DSN echo in alembic CLI output."""
    cp = configparser.ConfigParser()
    cp.read(ALEMBIC_INI)
    assert cp.get("logger_alembic", "level", fallback="").upper() == "WARN"
    assert cp.get("logger_sqlalchemy", "level", fallback="").upper() == "WARN"
