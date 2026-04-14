"""Unit tests for tech_news_synth.ingest.sources_config (INGEST-01, T-04-01).

Covers:
    1. Happy path — 5 v1 sources validate with correct discriminator types
    2. Missing url → ValidationError
    3. Unknown type → ValidationError (discriminator failure)
    4. Duplicate name → ValueError
    5. Python object yaml → yaml.YAMLError (safe_load rejects)
    6. Default timeout_sec per type (RSS=20.0, HN/Reddit=15.0)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from tech_news_synth.ingest.sources_config import (
    HnFirebaseSource,
    RedditJsonSource,
    RssSource,
    load_sources_config,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sources"


# ---------------------------------------------------------------------------
# Test 1 — happy path
# ---------------------------------------------------------------------------
def test_valid_config_loads_five_sources():
    cfg = load_sources_config(FIXTURES / "valid.yaml")
    assert cfg.max_articles_per_fetch == 30
    assert cfg.max_article_age_hours == 24
    assert len(cfg.sources) == 5

    by_name = {s.name: s for s in cfg.sources}
    assert isinstance(by_name["techcrunch"], RssSource)
    assert isinstance(by_name["verge"], RssSource)
    assert isinstance(by_name["ars_technica"], RssSource)
    assert isinstance(by_name["hacker_news"], HnFirebaseSource)
    assert isinstance(by_name["reddit_technology"], RedditJsonSource)


# ---------------------------------------------------------------------------
# Test 2 — missing url
# ---------------------------------------------------------------------------
def test_missing_url_raises_validation_error():
    with pytest.raises(ValidationError) as excinfo:
        load_sources_config(FIXTURES / "missing_url.yaml")
    msg = str(excinfo.value).lower()
    assert "url" in msg


# ---------------------------------------------------------------------------
# Test 3 — unknown type (discriminator failure)
# ---------------------------------------------------------------------------
def test_unknown_type_raises_validation_error():
    with pytest.raises(ValidationError) as excinfo:
        load_sources_config(FIXTURES / "unknown_type.yaml")
    msg = str(excinfo.value).lower()
    assert "type" in msg


def test_bad_type_fixture_also_rejected():
    with pytest.raises(ValidationError):
        load_sources_config(FIXTURES / "bad_type.yaml")


# ---------------------------------------------------------------------------
# Test 4 — duplicate source name
# ---------------------------------------------------------------------------
def test_duplicate_name_raises_value_error():
    # ValueError from our @model_validator is wrapped by pydantic into
    # ValidationError when raised from within model_validator(mode="after").
    with pytest.raises((ValueError, ValidationError)) as excinfo:
        load_sources_config(FIXTURES / "duplicate_name.yaml")
    assert "techcrunch" in str(excinfo.value).lower()
    assert "duplicate" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Test 5 — safe_load rejects python object tags
# ---------------------------------------------------------------------------
def test_rejects_python_object_tags():
    """T-04-01: !!python/object/apply:os.system must be rejected by safe_load
    BEFORE any Python object is instantiated."""
    with pytest.raises(yaml.YAMLError):
        load_sources_config(FIXTURES / "python_object.yaml")


# ---------------------------------------------------------------------------
# Test 6 — default timeout per type
# ---------------------------------------------------------------------------
def test_default_timeouts_per_type(tmp_path: Path):
    content = """
max_articles_per_fetch: 30
max_article_age_hours: 24
sources:
  - {name: rss_src, type: rss, url: https://example.com/feed}
  - {name: hn_src, type: hn_firebase, url: https://hacker-news.firebaseio.com/v0}
  - {name: reddit_src, type: reddit_json, url: https://www.reddit.com/r/tech/.json}
"""
    p = tmp_path / "defaults.yaml"
    p.write_text(content)
    cfg = load_sources_config(p)
    by_name = {s.name: s for s in cfg.sources}
    assert by_name["rss_src"].timeout_sec == 20.0
    assert by_name["hn_src"].timeout_sec == 15.0
    assert by_name["reddit_src"].timeout_sec == 15.0


# ---------------------------------------------------------------------------
# Phase 5 — per-source `weight` field (D-04/D-05)
# ---------------------------------------------------------------------------
def test_weight_default_preserves_backward_compat():
    """Existing yaml without `weight` must load; all sources default to 1.0."""
    cfg = load_sources_config(FIXTURES / "valid.yaml")
    for s in cfg.sources:
        assert s.weight == 1.0


def test_weight_custom_value_loads(tmp_path: Path):
    content = """
max_articles_per_fetch: 30
max_article_age_hours: 24
sources:
  - {name: rss_src, type: rss, url: https://example.com/feed, weight: 2.5}
  - {name: hn_src, type: hn_firebase, url: https://hacker-news.firebaseio.com/v0}
"""
    p = tmp_path / "weights.yaml"
    p.write_text(content)
    cfg = load_sources_config(p)
    by_name = {s.name: s for s in cfg.sources}
    assert by_name["rss_src"].weight == 2.5
    assert by_name["hn_src"].weight == 1.0


@pytest.mark.parametrize("bad_weight", [-0.5, 11.0, 100.0])
def test_weight_out_of_bounds_rejected(tmp_path: Path, bad_weight):
    content = f"""
max_articles_per_fetch: 30
max_article_age_hours: 24
sources:
  - {{name: rss_src, type: rss, url: https://example.com/feed, weight: {bad_weight}}}
"""
    p = tmp_path / "bad_weight.yaml"
    p.write_text(content)
    with pytest.raises(ValidationError):
        load_sources_config(p)
