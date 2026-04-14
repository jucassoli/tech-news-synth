"""Hashtag allowlist + selector (D-11, SYNTH-05).

Storage:
  ``config/hashtags.yaml`` is a topic→tags map + default fallback. Loaded
  at boot via :func:`load_hashtag_allowlist` which validates through pydantic
  (fail-fast on malformed input — T-06-08).

Selection:
  :func:`select_hashtags` takes the cluster's ``centroid_terms`` (Phase 5's
  top-K TF-IDF terms) and substring-matches their slugs against allowlist
  topic keys. The LLM NEVER picks a hashtag (D-11, T-06-05).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, field_validator
from slugify import slugify


class HashtagAllowlist(BaseModel):
    """Validated hashtag allowlist (T-06-08).

    ``topics``: mapping of topic slug → list of hashtags (must include ``#``).
    ``default``: fallback tags when no topic matches. MUST be non-empty.
    """

    model_config = ConfigDict(frozen=True)

    topics: dict[str, list[str]]
    default: list[str]

    @field_validator("default")
    @classmethod
    def _default_must_be_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("HashtagAllowlist.default must be non-empty")
        return v


def load_hashtag_allowlist(path: Path) -> HashtagAllowlist:
    """Parse + validate ``path`` as a HashtagAllowlist.

    Uses ``yaml.safe_load`` (never ``yaml.load``) for arbitrary-code safety.
    """
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(
            f"Hashtag allowlist must be a YAML mapping, got {type(raw).__name__}"
        )
    return HashtagAllowlist.model_validate(raw)


def select_hashtags(
    centroid_terms: dict[str, float],
    allowlist: HashtagAllowlist,
    top_k: int = 10,
    max_tags: int = 2,
) -> list[str]:
    """Return up to ``max_tags`` hashtags from the allowlist (D-11, T-06-05).

    Algorithm:
      1. Sort terms by weight DESC; keep top ``top_k``.
      2. For each term, compute ``slug = slugify(term)``.
      3. Substring-match ``slug`` against each allowlist topic key
         (``slug in key or key in slug``); collect that topic's tags.
      4. Deduplicate preserving first-seen order.
      5. Slice to ``max_tags``.
      6. If empty → return ``allowlist.default[:max_tags]``.

    Never returns a tag outside ``allowlist.topics.values()`` ∪
    ``allowlist.default`` (T-06-05).
    """
    if not centroid_terms:
        return list(allowlist.default[:max_tags])

    sorted_terms = sorted(centroid_terms.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]

    collected: list[str] = []
    seen: set[str] = set()
    for term, _weight in sorted_terms:
        term_slug = slugify(term)
        if not term_slug:
            continue
        for topic_key, tags in allowlist.topics.items():
            if term_slug in topic_key or topic_key in term_slug:
                for tag in tags:
                    if tag not in seen:
                        collected.append(tag)
                        seen.add(tag)

    if not collected:
        return list(allowlist.default[:max_tags])

    return collected[:max_tags]


__all__ = ["HashtagAllowlist", "load_hashtag_allowlist", "select_hashtags"]
