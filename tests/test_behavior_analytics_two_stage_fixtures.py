"""Regression coverage for the two-stage behavior analytics fixtures."""

import json
from pathlib import Path


FIXTURES = Path("tests/fixtures/behavior_analytics/two_stage")


def _rows(path: Path) -> list[dict]:
    """Read non-empty JSONL rows from one fixture file."""
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_two_stage_fixture_inventory_is_complete():
    """All storage and replay edge cases have a stable input file."""
    expected = {
        "monthly/events-2026-08.jsonl",
        "hourly/events-2026-08-21-01.jsonl",
        "mixed/monthly/events-2026-08.jsonl",
        "mixed/hourly/events-2026-08-21-02.jsonl",
        "sequence_gap/events-2026-08-21-02.jsonl",
        "manifest_missing/events-2026-08-21-03.jsonl",
        "overlapping_actions/events-2026-08-21-04.jsonl",
        "dual_range/events-2026-08-21-05.jsonl",
    }
    actual = {
        path.relative_to(FIXTURES).as_posix()
        for path in FIXTURES.rglob("*.jsonl")
    }
    assert actual == expected


def test_hourly_fixture_is_v3_and_manifest_is_complete():
    """The representative hourly source has contiguous sequence facts."""
    rows = _rows(FIXTURES / "hourly/events-2026-08-21-01.jsonl")
    assert {row["schema_version"] for row in rows} == {3}
    assert [row["sequence_no"] for row in rows] == [1, 2, 3]
    manifest = json.loads(
        (FIXTURES / "hourly/events-2026-08-21-01.manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["manifest_complete"] is True
    assert manifest["event_count"] == len(rows)


def test_edge_fixtures_preserve_gap_missing_manifest_overlap_and_ranges():
    """Edge fixtures expose facts without relying on implementation behavior."""
    gap = _rows(FIXTURES / "sequence_gap/events-2026-08-21-02.jsonl")
    assert [row["sequence_no"] for row in gap] == [1, 3]
    missing = FIXTURES / "manifest_missing/events-2026-08-21-03.manifest.json"
    assert not missing.exists()
    overlap = _rows(FIXTURES / "overlapping_actions/events-2026-08-21-04.jsonl")
    spans = [
        (row["started_monotonic_ms"], row["ended_monotonic_ms"])
        for row in overlap
    ]
    assert spans == [(1000, 1800), (1500, 2200)]
    dual = _rows(FIXTURES / "dual_range/events-2026-08-21-05.jsonl")
    assert [row["event_id"] for row in dual] == [
        "baseline-1",
        "comparison-1",
    ]


def test_mixed_fixture_contains_v2_v3_and_duplicate_source_id():
    """The mixed directory models read-only compatibility and source overlap."""
    old = _rows(FIXTURES / "mixed/monthly/events-2026-08.jsonl")
    new = _rows(FIXTURES / "mixed/hourly/events-2026-08-21-02.jsonl")
    assert {row["schema_version"] for row in old + new} == {2, 3}
    assert old[0]["event_id"] == new[0]["event_id"]
