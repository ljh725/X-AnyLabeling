"""Completion, quality and navigation edge cases added in batch 2D.

* quality stays ``not-assessed`` until an explicit, sourced conclusion;
* a real content change invalidates completion *and* any quality conclusion;
* a cancelled image switch is observable and never moves the round.
"""

from __future__ import annotations

from tests.test_correction_metrics import synthetic
from tests.test_correction_metrics.test_controller import rect, started


def _save(controller, host):
    token = controller.prepare_save("scene.json", host.canvas.shapes)
    assert controller.save_result(token, True) is True
    return token


def test_quality_is_not_assessed_until_an_explicit_source(tmp_path):
    """5.6：默认 not-assessed；没有来源的结论不得写入。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    _save(controller, host)

    assert controller.current_row()["quality"] == "not-assessed"
    assert controller.set_quality("accepted") is False
    assert controller.set_quality("accepted", source="") is False
    assert controller.current_row()["quality"] == "not-assessed"

    assert controller.set_quality(
        "accepted", source={"kind": "manual-qc", "scope": "round"}
    ) is True
    row = controller.current_row()
    assert row["quality"] == "accepted"
    assert row["quality_source"] == {"kind": "manual-qc", "scope": "round"}
    # An explicit quality conclusion is independent of completion.
    assert row["completed"] is False


def test_content_change_invalidates_completion_and_quality(tmp_path):
    """5.4/5.6：内容变化使完成与质量结论同时失效。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    _save(controller, host)
    controller.set_quality("accepted", source="manual-qc")
    assert controller.finish_round() is True
    assert controller.current_row()["completed"] is True

    host.canvas.shapes = [rect("r1", box=(30, 30, 70, 90))]
    assert controller.edit("geometry", changed=host.canvas.shapes) is True

    row = controller.current_row()
    assert row["completed"] is False
    assert row["quality"] == "not-assessed"
    assert row["quality_source"] is None


def test_cancelled_navigation_keeps_the_round_and_is_observable(tmp_path):
    """5.2：取消切图不改轮次、不分配时间，且动作可见。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    round_id = controller.current_row()["round_id"]
    before = controller.current_row()["time"]

    assert controller.navigation_cancelled() is True
    assert controller.current_row()["round_id"] == round_id
    assert controller.current_row()["time"] == before


def test_complete_scope_completes_clean_rounds_and_skips_dirty_ones(tmp_path):
    """5.3：批量完成只完成干净已保存轮次，脏草稿带原因列出。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    _save(controller, host)

    # A second image with its own clean, saved round (batch entry).
    other = tmp_path / "images" / "other.jpg"
    other.write_bytes(b"other-image")
    assert controller.prediction_saved(
        str(other),
        str(tmp_path / "labels" / "other.json"),
        {"run_id": "batch-1", "mode": "replacement"},
        [rect("a1")],
    ) is True

    # The first image now has an unsaved draft: it must not be completed.
    host.canvas.shapes = [rect("r1"), rect("r2")]
    controller.edit("create", changed=[rect("r2")])

    report = controller.complete_scope()

    assert len(report["completed"]) == 1
    assert report["completed"][0].endswith("other.jpg")
    assert [(item["reason"]) for item in report["skipped"]] == ["unsaved-draft"]


def test_start_review_opens_a_separate_phase_round(tmp_path):
    """5.5：开始复核建立独立 review 阶段轮次，旧阶段成本保留。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    _save(controller, host)
    controller.finish_round()
    correction_id = controller.current_row()["round_id"]

    assert controller.start_review() is True
    row = controller.current_row()
    assert row["round_id"] != correction_id
    assert row["phase"] == "review"
    rows = controller.rows()
    assert {item["round_id"] for item in rows} >= {correction_id, row["round_id"]}


# ---------------------------------------------------------------------------
# Task 5.5 -- finishing closes the time segment; resume keeps the cost
# ---------------------------------------------------------------------------
class _Clock:
    """Deterministic monotonic clock for the controller-level timing cases."""

    def __init__(self, start=500.0):
        self.value = float(start)

    def __call__(self):
        return self.value

    def advance(self, seconds=1.0):
        self.value += float(seconds)


def _timed_controller(scratch, shapes):
    """Controller with an injectable work clock, already entered on one image."""
    from anylabeling.services.correction_metrics.timing import WorkClock
    from anylabeling.views.labeling.correction_metrics.controller import (
        CorrectionMetricsController,
    )
    from tests.test_correction_metrics.test_controller import make_host

    host = make_host(scratch, shapes)
    clock = _Clock()
    controller = CorrectionMetricsController(
        host,
        language="zh_CN",
        storage_root=str(scratch / "metrics"),
        clock=WorkClock(clock=clock),
    )
    assert controller.start_scope(
        str(scratch / "images"), str(scratch / "labels")
    )
    assert controller.enter_image() is True
    return controller, host, clock


def _run(controller, clock, seconds):
    for _ in range(int(seconds)):
        clock.advance(1)
        controller.tick()


def test_finishing_freezes_the_timer_and_resume_starts_a_new_session(tmp_path):
    """5.5：完成后计时关闭（浏览不再累加），继续修正从实际编辑起另计新片段。"""
    controller, host, clock = _timed_controller(tmp_path, [rect("r1")])
    _run(controller, clock, 20)
    assert controller.current_row()["time"]["working"] == 20.0

    token = controller.prepare_save("scene.json", host.canvas.shapes)
    assert controller.save_result(token, True) is True
    assert controller.finish_round() is True
    frozen = controller.current_row()["time"]["working"]
    assert frozen == 20.0
    assert controller.state()["state"] == "closed"

    # Browsing a completed round must not add processing time.
    _run(controller, clock, 30)
    assert controller.current_row()["time"]["working"] == frozen

    assert controller.resume_round() is True
    assert controller.state()["state"] == "working"
    _run(controller, clock, 5)

    row = controller.current_row()
    assert len(row["session_ids"]) == 2
    assert row["time"]["working"] == 25.0


def test_model_runtime_and_processing_time_are_reported_separately():
    """6.5：20 秒后台推理 + 20 秒审图并列记录，不相加为 40 秒人工处理。"""
    round_obj = synthetic.make_round(
        synthetic.dense_30(),
        provenance={"inference_seconds": 20.0, "model": "yolo"},
    )
    round_obj.set_time(
        "session-1", {"working": 20.0, "blocking_wait": 4.0}
    )

    row = round_obj.row()
    assert row["inference_seconds"] == 20.0
    assert row["time"]["working"] == 20.0
    assert row["time"]["blocking_wait"] == 4.0
    # There is no derived "elapsed" that could be mistaken for 40 s of work.
    assert "elapsed_total" not in row
    assert row["time"]["working"] != row["inference_seconds"] + 20.0
