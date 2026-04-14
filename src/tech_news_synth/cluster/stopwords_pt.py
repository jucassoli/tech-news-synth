"""PT+EN stopwords for TF-IDF preprocessor (D-08, research P-1).

CRITICAL: sklearn's TfidfVectorizer(stop_words=...) is silently IGNORED
when analyzer='char_wb'. We strip stopwords at preprocess time BEFORE text
reaches the vectorizer. This module exports the union set the preprocessor
filters against.

All words are pre-unidecoded and lowercased so lookup after
``unidecode(text).lower()`` matches without a second pass.
"""

from __future__ import annotations

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

# ~90 PT-BR high-frequency words from CONTEXT <specifics> seed list.
# Pre-unidecoded (e.g. "não" -> "nao", "é" -> "e", "à" -> "a", "às" -> "as").
# Duplicates after unidecoding (e.g. "a"/"à" both become "a") are deduped by frozenset.
_PT_SEED: tuple[str, ...] = (
    "de", "a", "o", "que", "e", "do", "da", "em", "um", "para",
    "com", "nao", "uma", "os", "no", "se", "na", "por", "mais",
    "as", "dos", "como", "mas", "foi", "ao", "ele", "das", "tem",
    "seu", "sua", "ou", "ser", "quando", "muito", "ha", "nos", "ja",
    "esta", "eu", "tambem", "so", "pelo", "pela", "ate",
    "isso", "ela", "entre", "era", "depois", "sem", "mesmo", "aos",
    "ter", "seus", "quem", "nas", "me", "esse", "eles", "estao",
    "voce", "tinha", "foram", "essa", "num", "nem", "suas", "meu",
    "minha", "numa", "pelos", "elas", "havia", "seja", "qual", "sera",
    "tenho", "lhe", "deles", "essas", "esses", "pelas", "este", "fosse",
)  # fmt: skip

PT_STOPWORDS: frozenset[str] = frozenset(_PT_SEED)
PT_EN_STOPWORDS: frozenset[str] = PT_STOPWORDS | frozenset(ENGLISH_STOP_WORDS)

__all__ = ["PT_EN_STOPWORDS", "PT_STOPWORDS"]
