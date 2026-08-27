"""Tests for read-only hourly manifest diagnostics."""

import json

from anylabeling.services.behavior_analytics.manifest import (
    diagnose_event_shards,
    rebuild_event_shard_manifest,
)


def _write_shard(path):
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "schema_version": 3,
                    "occurred_at_utc": "2026-08-21T01:00:00.000Z",
                }
            )
            for _ in range(2)
        )
        + "\n",
        encoding="utf-8",
    )


def test_manifest_diagnostics_detect_missing_and_rebuild_without_rewriting_source(
    tmp_path,
):
    """Missing manifests are diagnosable and rebuild is atomic/read-only to JSONL."""
    shard = tmp_path / "events-2026-08-21-01.jsonl"
    _write_shard(shard)
    original = shard.read_bytes()
    diagnostic = diagnose_event_shards(tmp_path)[0]
    assert diagnostic.status == "missing_manifest"
    rebuild_event_shard_manifest(shard)
    assert shard.read_bytes() == original
    assert diagnose_event_shards(tmp_path)[0].status == "ok"


def test_manifest_diagnostics_detect_stale_hash(tmp_path):
    """A changed JSONL source is flagged without modifying either input."""
    shard = tmp_path / "events-2026-08-21-02.jsonl"
    _write_shard(shard)
    rebuild_event_shard_manifest(shard)
    shard.write_bytes(shard.read_bytes() + b"broken\n")
    diagnostic = diagnose_event_shards(tmp_path)[0]
    assert diagnostic.status == "inconsistent"
    assert "stale_sha256" in diagnostic.issues

def test_manifest_diagnostics_flag_active_shard(tmp_path):
    """An incomplete sidecar is retained as an explicit crash/active fact."""
    shard = tmp_path / "events-2026-08-21-03.jsonl"
    _write_shard(shard)
    manifest = shard.with_name(f"{shard.stem}.manifest.json")
    manifest.write_text(
        json.dumps({"manifest_complete": False}), encoding="utf-8"
    )
    diagnostic = diagnose_event_shards(tmp_path)[0]
    assert diagnostic.status == "inconsistent"
    assert "active_shard" in diagnostic.issues

