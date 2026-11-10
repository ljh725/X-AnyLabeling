"""Task 6.1-6.3 -- the ``WorkClock`` interval state machine.

Covers the mutually exclusive work states (working / paused / inactive /
not_ready / blocking_wait / closed), the wall-clock conservation and segment
ledger of ``audit``, the explicit-pause semantics, idle accumulation and its
one-shot confirmation, clock-gap handling, monotonic-clock rollback and the
JSON-serialisable audit trail.  A fake monotonic clock is injected, so every
assertion is an exact number of seconds, never a threshold.

Three controller-level cases at the end pin ``time_checkpoint`` to an
**absolute** snapshot per session (a repeated heartbeat never doubles time) and
to the current round only.

No production code is modified by these tests.
"""

from __future__ import annotations

import json
import types

import pytest

from anylabeling.services.correction_metrics.core import SHAPE_ID
from anylabeling.services.correction_metrics.timing import WorkClock

STATES = ("working", "paused", "inactive", "not_ready", "blocking_wait")


class FakeClock:
    """Injectable monotonic clock that only moves when a test moves it."""

    def __init__(self, start=1000.0):
        self.value = float(start)

    def __call__(self):
        return self.value

    def advance(self, seconds=1.0):
        self.value += float(seconds)
        return self.value

    def set(self, value):
        self.value = float(value)
        return self.value


def attached(**kwargs):
    """Return ``(clock, work)`` with a round already attached at t=1000."""
    clock = FakeClock()
    work = WorkClock(clock=clock)
    work.attach("round-1", **kwargs)
    return clock, work


def run(clock, work, seconds, step=1.0):
    """Advance the fake clock by ``seconds`` in ``step`` ticks, calling tick()."""
    for _ in range(int(round(seconds / step))):
        clock.advance(step)
        work.tick()


def segment_list(work):
    """``audit["segments"]`` as ``(state, start, end)`` tuples."""
    return [tuple(segment) for segment in work.audit["segments"]]


def state_seconds(work):
    """Sum of the five real states (pending/excluded are derived, not states)."""
    totals = work.totals
    return sum(totals[state] for state in STATES)


# ---------------------------------------------------------------------------
# 1. state exclusivity and priority
# ---------------------------------------------------------------------------
def test_attach_is_working_and_detach_is_closed():
    """验证 TIM-1：未 attach 时 closed；attach 后只有一个状态 working；attach(None) 回到 closed。"""
    clock = FakeClock()
    work = WorkClock(clock=clock)

    assert work.state == "closed"
    work.attach("round-1")
    assert work.state == "working"
    assert work.session_id is not None

    work.attach(None)
    assert work.state == "closed"
    assert work.session_id is None


def test_explicit_pause_beats_foreground_and_blocking():
    """验证 TIM-2：paused 优先级最高——foreground/suspended/blocked/ready 同时变化仍是 paused。"""
    clock, work = attached()

    work.change(paused=True)
    assert work.state == "paused"

    work.change(foreground=False, suspended=True, blocked=True, ready=False)
    assert work.state == "paused"

    work.change(paused=False)
    assert work.state == "inactive"  # foreground still False


def test_inactive_beats_blocking_and_not_ready():
    """验证 TIM-2：窗口失焦或系统挂起一律 inactive，优先于 blocked/not_ready。"""
    clock, work = attached()

    work.change(foreground=False, blocked=True, ready=False)
    assert work.state == "inactive"

    work.change(foreground=True)
    assert work.state == "blocking_wait"

    work.change(blocked=False, ready=False, suspended=True)
    assert work.state == "inactive"

    work.change(suspended=False)
    assert work.state == "not_ready"


def test_blocked_beats_not_ready_and_ready_controls_working():
    """验证 TIM-2/TIM-7：blocked 优先于 not_ready；ready=False 只表示 not_ready。"""
    clock, work = attached()

    work.change(blocked=True, ready=False)
    assert work.state == "blocking_wait"

    work.change(blocked=False)
    assert work.state == "not_ready"

    work.change(ready=True)
    assert work.state == "working"


def test_completed_clock_is_closed_whatever_the_flags_say():
    """验证 TIM-3：completed=True 后状态是 closed，即使 paused/blocked 等标志仍为真。"""
    clock, work = attached()

    work.change(paused=True, blocked=True)
    work.completed = True

    assert work.state == "closed"
    run(clock, work, 3)
    assert work.totals["working"] == 0.0
    assert work.totals["paused"] == 0.0


def test_attach_resets_every_counter_and_starts_a_new_session():
    """验证 TIM-1：重新 attach 归零全部时长并换新 session_id（同一次访问、新的轮次）。"""
    clock, work = attached()
    run(clock, work, 10)
    first_session = work.session_id
    assert work.totals["working"] == 10.0

    work.attach("round-2")

    assert work.session_id != first_session
    assert work.round_id == "round-2"
    assert work.state == "working"
    assert work.totals["working"] == 0.0
    assert state_seconds(work) == 0.0


def test_attach_with_completed_flag_is_closed_from_the_start():
    """验证 TIM-3：attach(completed=True) 直接进入 closed，不再累计任何时长。"""
    clock = FakeClock()
    work = WorkClock(clock=clock)
    work.attach("round-1", completed=True)

    assert work.state == "closed"
    clock.advance(5)
    work.tick()
    assert state_seconds(work) == 0.0
    assert work.totals["timing_gap_seconds"] == 0.0


# ---------------------------------------------------------------------------
# 2. wall-clock conservation and the segment ledger
# ---------------------------------------------------------------------------
def test_total_seconds_equal_elapsed_wall_clock_for_mixed_states():
    """验证 TIM-4：五种状态时长之和等于经过的墙钟时间（31s，逐状态精确）。"""
    clock, work = attached()

    run(clock, work, 10)                              # working 10
    work.change(foreground=False)                     # -> inactive
    run(clock, work, 5)                               # inactive 5
    work.change(foreground=True)                      # -> working
    run(clock, work, 2)                               # working 12
    work.change(blocked=True)                         # -> blocking_wait
    run(clock, work, 3)                               # blocking 3
    work.change(blocked=False, ready=False)           # -> not_ready
    run(clock, work, 7)                               # not_ready 7
    work.change(ready=True, paused=True)              # -> paused
    run(clock, work, 4)                               # paused 4

    totals = work.totals
    assert totals["working"] == 12.0
    assert totals["inactive"] == 5.0
    assert totals["blocking_wait"] == 3.0
    assert totals["not_ready"] == 7.0
    assert totals["paused"] == 4.0
    assert state_seconds(work) == 31.0
    assert totals["timing_gap_seconds"] == 0.0


def test_audit_segments_are_contiguous_monotonic_and_non_overlapping():
    """验证 TIM-4：audit.segments 首尾相接、不重叠、单调递增，且覆盖全部经过时间。"""
    clock, work = attached()

    run(clock, work, 10)
    work.change(foreground=False)
    run(clock, work, 5)
    work.change(foreground=True)
    run(clock, work, 2)
    work.change(blocked=True)
    run(clock, work, 3)
    work.change(blocked=False, ready=False)
    run(clock, work, 7)
    work.change(ready=True, paused=True)
    run(clock, work, 4)

    segments = segment_list(work)
    assert segments == [
        ("working", 0.0, 10.0),
        ("inactive", 10.0, 15.0),
        ("working", 15.0, 17.0),
        ("blocking_wait", 17.0, 20.0),
        ("not_ready", 20.0, 27.0),
        ("paused", 27.0, 31.0),
    ]
    for previous, following in zip(segments, segments[1:]):
        assert previous[2] == following[1]          # contiguous (首尾相接)
        assert previous[1] < previous[2]            # positive width
        assert following[1] >= previous[1]          # monotonic
    assert sum(end - start for _, start, end in segments) == 31.0


def test_same_state_ticks_coalesce_into_one_segment():
    """验证 TIM-4：同状态连续 tick 合并为一段（不因每秒 tick 产生碎片）。"""
    clock, work = attached()
    run(clock, work, 7)

    assert segment_list(work) == [("working", 0.0, 7.0)]


def test_clock_rewind_never_produces_negative_durations():
    """验证 TIM-5：系统时间回退时 tick 不累加、不产生负时长，恢复后继续从上次位置计时。"""
    clock, work = attached()
    run(clock, work, 10)
    assert work.totals["working"] == 10.0

    clock.set(1005.0)          # clock jumps 5s backwards
    work.tick()                # ignored
    work.tick()

    totals = work.totals
    assert totals["working"] == 10.0
    assert all(totals[state] >= 0.0 for state in STATES)
    assert totals["pending_idle"] == 0.0
    assert totals["timing_gap_seconds"] == 0.0
    assert state_seconds(work) == 10.0

    clock.set(1011.0)          # back above the previous mark: +1s
    work.tick()
    assert work.totals["working"] == 11.0


def test_tick_without_time_passing_counts_nothing():
    """验证 TIM-4：同一时刻重复 tick 不产生时长、不产生段。"""
    clock, work = attached()

    work.tick()
    work.tick()
    work.tick()

    assert work.totals["working"] == 0.0
    assert segment_list(work) == []


# ---------------------------------------------------------------------------
# 3. explicit pause
# ---------------------------------------------------------------------------
def test_explicit_pause_survives_foreground_activation():
    """验证 TIM-6：显式暂停不被重新获得焦点解除，只有 paused=False 才恢复工作。"""
    clock, work = attached()
    work.change(paused=True)
    run(clock, work, 5)
    assert work.totals["paused"] == 5.0

    work.change(foreground=True)
    assert work.state == "paused"
    run(clock, work, 3)
    assert work.totals["paused"] == 8.0
    assert work.totals["working"] == 0.0

    work.change(paused=False)
    assert work.state == "working"
    run(clock, work, 2)
    assert work.totals["working"] == 2.0
    assert state_seconds(work) == 10.0


def test_paused_time_never_becomes_pending_idle():
    """验证 TIM-6：暂停时长不参与空闲判定（200s paused 后 pending_idle 仍为 0）。"""
    clock, work = attached()
    work.change(paused=True)
    run(clock, work, 200)

    assert work.totals["paused"] == 200.0
    assert work.totals["pending_idle"] == 0.0
    assert work.audit["adjustments"] == []


# ---------------------------------------------------------------------------
# 4. idle accumulation and one-shot confirmation
# ---------------------------------------------------------------------------
def test_working_below_idle_threshold_has_no_pending_idle():
    """验证 TIM-8：连续工作 119s（<120s 阈值）不累计 pending_idle。"""
    clock, work = attached()
    run(clock, work, 119)

    assert work.totals["working"] == 119.0
    assert work.totals["pending_idle"] == 0.0
    assert work.totals["excluded_idle"] == 0.0
    assert work.totals["adjusted_working"] == 119.0


def test_reaching_idle_threshold_only_accumulates_pending_idle():
    """验证 TIM-8：连续工作达 120s 只累计 pending_idle，绝不自动扣除。"""
    clock, work = attached()
    run(clock, work, 120)
    run(clock, work, 10)

    totals = work.totals
    assert totals["working"] == 130.0
    assert totals["pending_idle"] == 130.0
    assert totals["excluded_idle"] == 0.0            # not deducted automatically
    assert totals["adjusted_working"] == 130.0
    assert work.audit["adjustments"] == []


def test_confirm_idle_true_deducts_once_and_writes_an_adjustment():
    """验证 TIM-9：confirm_idle(True) 扣一次并写 adjustment；再次确认不重复扣。"""
    clock, work = attached()
    run(clock, work, 130)

    assert work.confirm_idle(True) == 130.0
    totals = work.totals
    assert totals["pending_idle"] == 0.0
    assert totals["excluded_idle"] == 130.0
    assert totals["adjusted_working"] == 0.0
    assert work.audit["adjustments"] == [
        {"at": 130.0, "decision": "exclude", "seconds": 130.0}
    ]

    # A repeated confirmation must not deduct anything twice.
    assert work.confirm_idle(True) == 0.0
    assert work.totals["excluded_idle"] == 130.0
    assert len(work.audit["adjustments"]) == 1


def test_confirm_idle_false_records_reviewed_without_deduction():
    """验证 TIM-9：confirm_idle(False) 只记 reviewed，不扣时长。"""
    clock, work = attached()
    run(clock, work, 130)

    assert work.confirm_idle(False) == 130.0
    totals = work.totals
    assert totals["pending_idle"] == 0.0
    assert totals["excluded_idle"] == 0.0
    assert totals["adjusted_working"] == 130.0
    assert work.audit["adjustments"] == [
        {"at": 130.0, "decision": "reviewed", "seconds": 130.0}
    ]


def test_activity_resets_the_continuous_working_streak():
    """验证 TIM-8：activity() 打断连续工作段——两段 100s 不会触发 120s 空闲判定。"""
    clock, work = attached()
    run(clock, work, 100)
    work.activity()
    run(clock, work, 100)

    assert work.totals["working"] == 200.0
    assert work.totals["pending_idle"] == 0.0
    assert work.totals["excluded_idle"] == 0.0


def test_idle_streak_restarts_after_a_confirmation():
    """验证 TIM-9：确认后连续工作段从 0 重新计算，需再满 120s 才产生新的 pending_idle。"""
    clock, work = attached()
    run(clock, work, 120)
    assert work.confirm_idle(True) == 120.0

    run(clock, work, 60)
    assert work.totals["pending_idle"] == 0.0
    run(clock, work, 60)
    assert work.totals["pending_idle"] == 120.0
    assert work.totals["working"] == 240.0
    assert work.totals["excluded_idle"] == 120.0
    assert work.totals["adjusted_working"] == 120.0


def test_activity_outside_working_is_a_no_op():
    """验证 TIM-8：非 working 状态调用 activity() 既不累计也不改变状态。"""
    clock, work = attached()
    work.change(paused=True)
    run(clock, work, 5)

    work.activity()

    assert work.state == "paused"
    assert work.totals["paused"] == 5.0
    assert work.totals["working"] == 0.0


# ---------------------------------------------------------------------------
# 5. long tick intervals (clock gaps)
# ---------------------------------------------------------------------------
def test_long_interval_records_a_timing_gap_instead_of_working_time():
    """验证 TIM-10：两次 tick 间隔 > max_gap 时记 timing gap，且不把整段算成 working。"""
    clock, work = attached()
    run(clock, work, 10)
    assert work.totals["working"] == 10.0

    clock.advance(30)          # > max_gap(5)
    work.tick()

    totals = work.totals
    assert totals["working"] == 10.0
    assert totals["timing_gap_seconds"] == 30.0
    assert work.audit["gaps"] == [(10.0, 40.0)]
    assert segment_list(work) == [("working", 0.0, 10.0)]

    clock.advance(1)
    work.tick()
    assert work.totals["working"] == 11.0


def test_interval_equal_to_max_gap_is_still_working_time():
    """验证 TIM-10：间隔恰好等于 max_gap(5s) 不是缺口，仍计入 working（边界不误判）。"""
    clock, work = attached()
    run(clock, work, 10)

    clock.advance(5)
    work.tick()

    assert work.totals["working"] == 15.0
    assert work.totals["timing_gap_seconds"] == 0.0
    assert work.audit["gaps"] == []


def test_gap_resets_the_idle_streak():
    """验证 TIM-10：长间隔同时打断连续工作段，缺口前后 100s 不会触发空闲判定。"""
    clock, work = attached()
    run(clock, work, 100)
    clock.advance(30)
    work.tick()
    run(clock, work, 100)

    totals = work.totals
    assert totals["working"] == 200.0
    assert totals["timing_gap_seconds"] == 30.0
    assert totals["pending_idle"] == 0.0
    assert work.audit["gaps"] == [(100.0, 130.0)]


# ---------------------------------------------------------------------------
# 6. derived totals and JSON audit
# ---------------------------------------------------------------------------
def test_adjusted_working_is_working_minus_excluded_idle():
    """验证 TIM-9：adjusted_working 恒等于 working - excluded_idle（扣前扣后都对）。"""
    clock, work = attached()
    run(clock, work, 200)

    assert work.totals["adjusted_working"] == 200.0 - 0.0
    work.confirm_idle(True)
    assert work.totals["working"] == 200.0
    assert work.totals["excluded_idle"] == 200.0
    assert work.totals["adjusted_working"] == 0.0


def test_totals_expose_exactly_the_documented_fields():
    """验证 TIM-11：totals 暴露五个状态 + pending/excluded/adjusted/gap 九个字段，且非负。"""
    clock, work = attached()
    run(clock, work, 3)

    assert set(work.totals) == {
        "working", "paused", "inactive", "not_ready", "blocking_wait",
        "pending_idle", "excluded_idle", "adjusted_working",
        "timing_gap_seconds",
    }
    assert all(value >= 0.0 for value in work.totals.values())


def test_audit_is_json_serializable():
    """验证 TIM-11：audit 只含 JSON 原生类型，可直接序列化并回读。"""
    clock, work = attached()
    run(clock, work, 130)
    work.change(foreground=False)
    run(clock, work, 4)
    clock.advance(30)
    work.tick()
    work.confirm_idle(True)

    payload = json.dumps(work.audit)
    restored = json.loads(payload)

    assert restored["segments"][0] == ["working", 0.0, 130.0]
    assert restored["segments"][-1] == ["inactive", 130.0, 134.0]
    assert restored["adjustments"] == [
        {"at": 164.0, "decision": "exclude", "seconds": 130.0}
    ]
    assert restored["gaps"] == [[134.0, 164.0]]
    assert all(isinstance(value, float) for value in work.totals.values())


# ---------------------------------------------------------------------------
# 7. controller.checkpoint: absolute per-session time, current round only
# ---------------------------------------------------------------------------
def rect(shape_id="r1"):
    """Minimal rectangle shape dict for the controller fixture."""
    return {
        SHAPE_ID: shape_id,
        "label": "person",
        "shape_type": "rectangle",
        "points": [[10, 10], [40, 60]],
    }


def started_controller(scratch):
    """Start a controller on one image and return it with its current round id."""
    from anylabeling.views.labeling.correction_metrics.controller import (
        CorrectionMetricsController,
    )

    image = scratch / "images" / "scene.jpg"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"fake-image-bytes")
    labels = scratch / "labels"
    labels.mkdir(exist_ok=True)
    host = types.SimpleNamespace(
        filename=str(image),
        output_dir=str(labels),
        canvas=types.SimpleNamespace(shapes=[rect()]),
    )
    controller = CorrectionMetricsController(
        host, language="zh_CN", storage_root=str(scratch / "metrics")
    )
    assert controller.start_scope(str(scratch / "images"), str(scratch / "labels"))
    controller.enter_image()
    return controller, controller.current_row()["round_id"]


def test_time_checkpoint_writes_absolute_totals_and_never_doubles(tmp_path):
    """验证 TIM-12：time_checkpoint 写入绝对值——同一 totals 重复上报不翻倍，改写则替换。"""
    controller, round_id = started_controller(tmp_path)

    controller.time_checkpoint(round_id, "session-A", {"working": 10.0, "paused": 2.0}, False)
    first = controller.current_row()["time"]
    assert first["working"] == 10.0
    assert first["paused"] == 2.0

    # The same heartbeat again must not double the session time.
    controller.time_checkpoint(round_id, "session-A", {"working": 10.0, "paused": 2.0}, False)
    repeated = controller.current_row()["time"]
    assert repeated["working"] == 10.0
    assert repeated["paused"] == 2.0

    # A later, larger absolute snapshot replaces the previous one (not a delta).
    controller.time_checkpoint(round_id, "session-A", {"working": 15.0, "paused": 2.0}, False)
    later = controller.current_row()["time"]
    assert later["working"] == 15.0
    assert later["paused"] == 2.0


def test_time_checkpoint_ignores_a_foreign_round_id(tmp_path):
    """验证 TIM-12：非当前 round_id 的 checkpoint 被忽略并返回 False，不污染本轮的时长。"""
    controller, round_id = started_controller(tmp_path)
    controller.time_checkpoint(round_id, "session-A", {"working": 7.0}, False)

    assert controller.time_checkpoint("not-this-round", "session-A",
                                      {"working": 900.0}, False) is False
    assert controller.current_row()["time"]["working"] == 7.0


def test_time_checkpoint_without_an_open_round_is_refused(tmp_path):
    """验证 TIM-12：未进入任何图片时 checkpoint 返回 False（没有可归属的轮次）。"""
    from anylabeling.views.labeling.correction_metrics.controller import (
        CorrectionMetricsController,
    )

    host = types.SimpleNamespace(
        filename=str(tmp_path / "images" / "scene.jpg"),
        output_dir=str(tmp_path / "labels"),
        canvas=types.SimpleNamespace(shapes=[rect()]),
    )
    controller = CorrectionMetricsController(
        host, language="zh_CN", storage_root=str(tmp_path / "metrics")
    )
    assert controller.start_scope(str(tmp_path / "images"), str(tmp_path / "labels"))

    assert controller.time_checkpoint("round-x", "session-A", {"working": 1.0}, False) is False
