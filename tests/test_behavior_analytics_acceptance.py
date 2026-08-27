"""Cross-cutting acceptance checks for the two-stage analytics change."""

import json
from pathlib import Path

from anylabeling.services.behavior_analytics import (
    benchmark_stream,
    generate_events,
    read_events,
    export_analysis_bundle,
    write_fixture,
)


def test_scale_fixture_writer_is_reproducible(tmp_path):
    """The documented fixture generator writes deterministic event lines."""
    first = write_fixture(tmp_path / "one.jsonl", 1000, sessions=4)
    second = write_fixture(tmp_path / "two.jsonl", 1000, sessions=4)
    assert first.read_bytes() == second.read_bytes()
    assert len(first.read_text(encoding="utf-8").splitlines()) == 1000


def test_stream_benchmark_reports_bounded_progress_and_memory():
    """Streaming benchmark exposes cancellation and peak-memory facts."""
    result = benchmark_stream(
        generate_events(10_000, sessions=4),
        batch_size=128,
        cancellation_after=512,
    )
    assert 512 <= result["processed_events"] <= 640
    assert result["cancelled"] is True
    assert result["peak_memory_bytes"] >= 0


def test_v3_bundle_is_deterministic_except_manifest_timestamp(tmp_path):
    """Repeated exports keep rows, traces, and file hashes stable."""
    events, _ = read_events(
        [Path("tests/fixtures/behavior_analytics/behavior_analytics_v2.jsonl")]
    )
    first = export_analysis_bundle(tmp_path / "first", events)
    second = export_analysis_bundle(tmp_path / "second", events)
    names = sorted(
        path.name for path in first.iterdir() if path.name != "manifest.json"
    )
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes()
    manifest_one = json.loads(
        (first / "manifest.json").read_text(encoding="utf-8")
    )
    manifest_two = json.loads(
        (second / "manifest.json").read_text(encoding="utf-8")
    )
    manifest_one.pop("generated_at_utc")
    manifest_two.pop("generated_at_utc")
    assert manifest_one == manifest_two


def test_high_cardinality_tables_emit_an_other_row(tmp_path):
    """Entity tables preserve an explicit aggregate after deterministic bounds."""
    target = export_analysis_bundle(
        tmp_path / "bounded",
        list(generate_events(64, sessions=4)),
        compact_table_row_limit=1,
    )
    rows = (target / "object_metrics.csv").read_text(encoding="utf-8")
    assert "other" in rows
    manifest = json.loads(
        (target / "manifest.json").read_text(encoding="utf-8")
    )
    assert (
        manifest["table_limits"]["tables"]["object_metrics.csv"][
            "omitted_rows"
        ]
        >= 1
    )


def test_worker_boundary_has_no_ui_thread_export_path():
    """The Qt adapter delegates work to QThread and the pure job."""
    source = Path(
        "anylabeling/views/labeling/widgets/behavior_analytics_worker.py"
    ).read_text(encoding="utf-8")
    assert "class BehaviorAnalyticsExportWorker(QtCore.QThread)" in source
    assert "run_export_job(" in source
    assert "export_analysis_bundle(" not in source
