"""Shared SQLAlchemy 2.0 DeclarativeBase for all ORM models.

Every model in :mod:`tech_news_synth.db.models` inherits from :class:`Base`;
the Alembic ``env.py`` (Plan 02-02) passes ``Base.metadata`` as
``target_metadata`` for autogenerate.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared metadata for every ORM model. ``target_metadata`` for alembic."""
