"""PT+EN stopwords for TF-IDF preprocessor (D-08, research P-1).

Plan 05-01 Task 1 scaffold — Task 2 populates ``PT_STOPWORDS`` with the
real seed list from CONTEXT <specifics>.
"""

from __future__ import annotations

PT_STOPWORDS: frozenset[str] = frozenset()
PT_EN_STOPWORDS: frozenset[str] = frozenset()

__all__ = ["PT_EN_STOPWORDS", "PT_STOPWORDS"]
