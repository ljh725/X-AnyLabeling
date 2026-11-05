"""Cancellation responsiveness and dense-candidate behaviour.

These are deliberately small so they run in CI, but they record the actual
machine, input size and elapsed time instead of asserting a vague "fast".
"""

from __future__ import annotations

import platform
import threading
import time

from anylabeling.services.inspection.manifest import build_manifest
from anylabeling.services.inspection.models import RunScope, RunState
from anylabeling.services.inspection.profiles import default_profiles
from anylabeling.services.inspection.runner import InspectionRunner

CANCEL_TARGET_S = 1.0


def _write_dense_dataset(tmp_path, count=120, files=1):
    import json

    shapes = []
    for index in range(count):
        left = index % 10
        top = index // 10
        shapes.append(
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[left, top], [left + 8, top + 8]],
                "xanylabeling_shape_id": f"id{index}",
            }
        )
    for file_index in range(files):
        name = "dense" if file_index == 0 else f"dense{file_index}"
        (tmp_path / f"{name}.jpg").write_bytes(b"dense-image")
        (tmp_path / f"{name}.json").write_text(
            json.dumps(
                {
                    "version": "4.2.1",
                    "imageWidth": 200,
                    "imageHeight": 200,
                    "shapes": shapes,
                }
            ),
            encoding="utf-8",
        )
    return build_manifest(str(tmp_path))


def test_dense_candidates_complete_with_recorded_scale(tmp_path):
    manifest = _write_dense_dataset(tmp_path, count=120)
    profile = default_profiles()[0]
    started = time.perf_counter()
    report = InspectionRunner().run(manifest, profile, RunScope.DATASET)
    elapsed = time.perf_counter() - started
    duplicate = [
        issue
        for issue in report.issues
        if "duplicate_boxes" in issue.rule_ids
    ]
    # 120 boxes on a 10x10 grid overlap heavily: the candidate count is
    # quadratic, and the report must carry the real number of pairs rather
    # than a silently reduced set.
    assert duplicate
    assert report.truncated is False
    coverage = next(
        entry
        for entry in report.coverage
        if entry.rule_id == "duplicate_boxes"
    )
    assert coverage.state.value == "completed"
    assert coverage.issue_count == len(duplicate)
    print(
        "dense-scale",
        {
            "machine": platform.processor() or platform.machine(),
            "python": platform.python_version(),
            "rectangles": 120,
            "pairs": coverage.issue_count,
            "elapsed_s": round(elapsed, 4),
        },
    )
    assert elapsed < 10.0


def test_cancellation_is_observed_quickly_on_dense_input(tmp_path):
    manifest = _write_dense_dataset(tmp_path, count=160, files=3)
    profile = default_profiles()[0]
    cancel = threading.Event()
    observed = {"at": None}

    def progress(index, total, path):
        # Cancel once the first file starts producing results.
        if observed["at"] is None:
            observed["at"] = time.perf_counter()
            cancel.set()

    started = time.perf_counter()
    report = InspectionRunner().run(
        manifest,
        profile,
        RunScope.DATASET,
        cancel_event=cancel,
        progress=progress,
    )
    finished = time.perf_counter()
    latency = (
        finished - observed["at"] if observed["at"] is not None else None
    )
    assert report.state is RunState.CANCELLED
    assert report.issues or any(
        entry.state.value == "cancelled" for entry in report.coverage
    )
    # Cancellation must be observed by the compute side, and the run must
    # stop without discarding the partial evidence it already produced.
    assert latency is not None
    assert latency < CANCEL_TARGET_S, latency
    print(
        "cancel-latency",
        {
            "machine": platform.processor() or platform.machine(),
            "python": platform.python_version(),
            "rectangles": 160,
            "cancel_observed_s": round(latency, 4),
            "elapsed_s": round(finished - started, 4),
            "state": report.state.value,
        },
    )


def test_max_pairs_limit_marks_partial_and_truncated(tmp_path):
    manifest = _write_dense_dataset(tmp_path, count=60)
    profile = default_profiles()[0]
    from dataclasses import replace as dataclass_replace

    rules = []
    for rule in profile.rules:
        if rule.rule_id == "duplicate_boxes":
            rules.append(
                dataclass_replace(
                    rule,
                    parameters={**dict(rule.parameters), "max_pairs": 5},
                )
            )
        else:
            rules.append(rule)
    limited = dataclass_replace(profile, rules=tuple(rules))
    report = InspectionRunner().run(manifest, limited, RunScope.DATASET)
    duplicate = [
        issue
        for issue in report.issues
        if "duplicate_boxes" in issue.rule_ids
    ]
    assert len(duplicate) == 5
    assert report.truncated is True
    assert report.state is RunState.PARTIAL
    entry = next(
        item
        for item in report.coverage
        if item.rule_id == "duplicate_boxes"
    )
    assert entry.truncated is True
    assert "截断" in entry.reason
