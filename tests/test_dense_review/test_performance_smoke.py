"""Smoke test for the dense-review benchmark harness.

This only proves that the offscreen harness builds a real window, opens
the workspace and returns a complete report.  It intentionally does not
assert the provisional latency thresholds: those are measured manually
with ``scripts/benchmark_dense_review.py`` on a quiet machine.

Runtime target: well below 15 seconds (5 objects, 5 samples, 1 repeat).
"""

import importlib.util
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "benchmark_dense_review.py"
)
CONDITIONS = {
    "object_switch_cold",
    "object_switch_warm",
    "batch_switch_cold",
    "batch_switch_warm",
    "heartbeat_idle",
    "heartbeat_cards",
    "drag_baseline",
    "drag_open_all",
    "drag_open_focus",
    "drag_open_background",
    "text_refresh",
}


def _load_benchmark():
    spec = importlib.util.spec_from_file_location(
        "dense_review_benchmark_under_test", SCRIPT
    )
    if spec is None or spec.loader is None:
        raise AssertionError("benchmark script could not be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_benchmark_harness_smoke():
    started = time.perf_counter()
    module = _load_benchmark()
    report = module.run_benchmark(
        object_count=5,
        samples=5,
        repeats=1,
        lifecycle_switches=4,
    )
    elapsed = time.perf_counter() - started

    for key in (
        "environment",
        "conditions",
        "cache",
        "source_pixels",
        "thresholds",
        "passed",
        "summary",
    ):
        assert key in report

    conditions = report["conditions"]
    assert CONDITIONS <= set(conditions)
    for name in CONDITIONS:
        assert conditions[name]["summary"]["count"] == 5

    environment = report["environment"]
    assert environment["offscreen"] is True
    assert environment["pyqt"]
    assert environment["qt"]
    assert environment["image"]["objects"] == 5

    cache = report["cache"]
    assert cache["limit_entries"] >= 4
    assert cache["bounded"] is True
    probe = cache["probe"]
    assert probe["peak_entries"] <= cache["limit_entries"]
    assert probe["after"]["entries"] <= cache["limit_entries"]
    assert cache["reset_cleared_entries"] is True

    assert report["harness"]["errors"] == []
    lifecycle = report["image_lifecycle"]
    assert lifecycle["bounded_graphical_resources"] is True
    assert len(lifecycle["trace"]) == 4
    assert lifecycle["peak_rss_bytes"] > 0
    assert len({row["image"] for row in lifecycle["trace"]}) == 2
    assert len({row["output_dir"] for row in lifecycle["trace"]}) == 2
    assert report["source_pixels"]["fingerprint_calls_during_drag"] == 0

    # Threshold values are reported, not enforced by this smoke test.
    assert report["thresholds"]
    for check in report["thresholds"]:
        assert "passed" in check
        assert "measured" in check

    assert elapsed < 15.0, "benchmark smoke took %.1fs" % elapsed
