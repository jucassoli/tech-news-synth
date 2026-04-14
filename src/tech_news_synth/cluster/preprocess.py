"""Text preprocessor for TF-IDF vectorizer (D-08 + research P-1).

Pipeline: unidecode → lowercase → tokenize on ``\\b\\w+\\b`` → drop PT+EN
stopwords → rejoin with spaces. Fed to ``TfidfVectorizer(preprocessor=...)``.
"""

from __future__ import annotations

import re

from unidecode import unidecode

from tech_news_synth.cluster.stopwords_pt import PT_EN_STOPWORDS

_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)


def preprocess(text: str) -> str:
    """Lowercase + unidecode + strip stopword tokens + rejoin with spaces.

    Result is fed to ``TfidfVectorizer(preprocessor=preprocess,
    analyzer='char_wb', ...)``. Stopword tokens produce zero char n-grams
    because they never hit the analyzer.
    """
    if not text:
        return ""
    folded = unidecode(text).lower()
    tokens = _WORD_RE.findall(folded)
    kept = [t for t in tokens if t not in PT_EN_STOPWORDS]
    return " ".join(kept)


__all__ = ["preprocess"]
