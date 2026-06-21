"""Unit tests for the freshness + selector-cache invalidation chain."""

# Standard Library
import os

# First Party
from adaf.dbt import cache


def _touch(path, mtime_ns: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))


def test_missing_manifest_is_not_fresh(tmp_path) -> None:
    assert cache.manifest_is_fresh(tmp_path / "target" / "manifest.json", tmp_path) is False


def test_fresh_when_manifest_newer_than_sources(tmp_path) -> None:
    _touch(tmp_path / "models" / "a.sql", mtime_ns=1_000_000_000)
    _touch(tmp_path / "dbt_project.yml", mtime_ns=1_000_000_000)
    manifest = tmp_path / "target" / "manifest.json"
    _touch(manifest, mtime_ns=2_000_000_000)  # newer than every source
    assert cache.manifest_is_fresh(manifest, tmp_path) is True


def test_stale_when_a_source_is_newer(tmp_path) -> None:
    manifest = tmp_path / "target" / "manifest.json"
    _touch(manifest, mtime_ns=1_000_000_000)
    _touch(tmp_path / "models" / "a.sql", mtime_ns=2_000_000_000)  # edited after the parse
    assert cache.manifest_is_fresh(manifest, tmp_path) is False


def test_selector_cache_round_trip(tmp_path) -> None:
    manifest = tmp_path / "target" / "manifest.json"
    selectors = tmp_path / "selectors.yml"
    _touch(manifest, mtime_ns=1_000)
    _touch(selectors, mtime_ns=1_000)
    entry = cache.SelectorCacheEntry(
        members={"model.x", "model.y"},
        boundaries={"model.x": "outbound", "model.y": "internal"},
    )

    cache.save_selector(tmp_path, manifest, selectors, "demand", entry)
    loaded = cache.load_selector(tmp_path, manifest, selectors, "demand")
    assert loaded is not None
    assert loaded.members == entry.members
    assert loaded.boundaries == entry.boundaries


def test_selector_cache_is_one_file_per_selector(tmp_path) -> None:
    manifest = tmp_path / "target" / "manifest.json"
    selectors = tmp_path / "selectors.yml"
    _touch(manifest, mtime_ns=1_000)
    _touch(selectors, mtime_ns=1_000)
    cache.save_selector(
        tmp_path, manifest, selectors, "demand", cache.SelectorCacheEntry({"model.x"}, {"model.x": "outbound"})
    )
    cache.save_selector(
        tmp_path, manifest, selectors, "supply", cache.SelectorCacheEntry({"model.z"}, {"model.z": "inbound"})
    )
    # Each selector resolves to its own inspectable file; one missing doesn't affect the other.
    assert cache.selector_cache_path(tmp_path, "demand").exists()
    assert cache.selector_cache_path(tmp_path, "supply").exists()
    assert cache.load_selector(tmp_path, manifest, selectors, "absent") is None


def test_selector_cache_invalidates_when_manifest_changes(tmp_path) -> None:
    manifest = tmp_path / "target" / "manifest.json"
    selectors = tmp_path / "selectors.yml"
    _touch(manifest, mtime_ns=1_000)
    _touch(selectors, mtime_ns=1_000)
    cache.save_selector(
        tmp_path, manifest, selectors, "demand", cache.SelectorCacheEntry({"model.x"}, {"model.x": "internal"})
    )

    os.utime(manifest, ns=(5_000, 5_000))  # a reparse bumps the manifest mtime
    # Fingerprint no longer matches → a miss (None), never a stale read.
    assert cache.load_selector(tmp_path, manifest, selectors, "demand") is None


def test_corrupt_cache_is_a_miss(tmp_path) -> None:
    manifest = tmp_path / "target" / "manifest.json"
    selectors = tmp_path / "selectors.yml"
    _touch(manifest, mtime_ns=1_000)
    _touch(selectors, mtime_ns=1_000)
    cache_file = cache.selector_cache_path(tmp_path, "demand")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("{not json", encoding="utf-8")
    assert cache.load_selector(tmp_path, manifest, selectors, "demand") is None
