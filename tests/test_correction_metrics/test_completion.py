"""Tasks 5.3/5.4 -- "processing complete" is bound to a successfully saved version.

Covers spec ``annotation-correction-reporting`` "本轮处理完成绑定成功保存版本" and
"完成数量去重且轮次阶段另列":

* saving alone never declares completion;
* completion needs a successfully saved revision (a dirty draft / pending
  checkpoint gives a visible, non-raising refusal);
* a repeated explicit completion of the same saved version is idempotent: one
  completion record, same id, still one completed image;
* any real annotation change (global relabel, non-rectangle content) invalidates
  the current completion but keeps the old completion record;
* ``resume`` revokes completion and a later ``finish`` creates a *new* id;
  ``discard`` never manufactures a completion;
* read-only queries and re-saving the same content do not invalidate it;
* the completion cost snapshot is frozen and survives re-opening the image;
* batch completion skips an unsaved draft with an explicit reason.

Qt is only imported through the controller fixture; no widget is created.
The completion ledger is read back from the real SQLite database so the
assertions are about persisted, user-visible records rather than private state.
"""

from __future__ import annotations

import atexit
import itertools
import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from tests.test_correction_metrics.test_controller import rect, started

# ---------------------------------------------------------------------------
# scratch directory (this file lives outside the tests package while staging)
# ---------------------------------------------------------------------------
_SCRATCH_ROOT = Path(__file__).resolve().parent / "_scratch_completion"
_WORK_DIRS = []
_COUNTER = itertools.count()


def _workdir():
    _SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    while True:
        path = _SCRATCH_ROOT / ("case-%06d" % next(_COUNTER))
        try:
            path.mkdir()
        except FileExistsError:
            continue
        _WORK_DIRS.append(path)
        return path


@atexit.register
def _cleanup():
    for path in _WORK_DIRS:
        shutil.rmtree(path, ignore_errors=True)
    _WORK_DIRS.clear()


@pytest.fixture
def tmp_path(tmp_path_factory):
    """Writable per-test directory (falls back to the staging scratch tree)."""
    try:
        return tmp_path_factory.mktemp("completion")
    except OSError:
        return _workdir()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def polygon(shape_id="g1", label="person"):
    """Minimal polygon shape dict (statistics scope outside rectangles)."""
    return {
        "xanylabeling_shape_id": shape_id,
        "label": label,
        "shape_type": "polygon",
        "points": [[10, 10], [40, 10], [20, 40]],
    }


def save(controller, shapes):
    """Save the given shapes through the controller, asserting success."""
    token = controller.prepare_save("scene.json", shapes)
    assert token is not None
    assert controller.save_result(token, True) is True
    return token


def completion_ledger(controller, scratch):
    """Read every persisted completion record, as ``(id, round_id, revision, data)``."""
    controller.rows()  # public read forces a store flush of queued checkpoints
    database = next((scratch / "metrics").glob("*.sqlite3"))
    with sqlite3.connect(database) as connection:
        return connection.execute(
            "SELECT id, round_id, revision, data FROM completions ORDER BY rowid"
        ).fetchall()


def identities(paths):
    """The path-identity form the store stores for image paths."""
    return {os.path.normcase(os.path.abspath(path)) for path in paths}


# ---------------------------------------------------------------------------
# 1. completion needs an explicit action and a successfully saved version
# ---------------------------------------------------------------------------
def test_saving_alone_never_declares_completion(tmp_path):
    """验证 REP「保存成功但未声明完成」：保存本身不自动完成，轮次仍显示未完成。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    host.canvas.shapes = [rect("r1", box=(20, 20, 60, 80))]
    assert controller.edit("geometry", changed=host.canvas.shapes,
                           transaction_id="tx-move") is True

    save(controller, host.canvas.shapes)

    row = controller.current_row()
    assert row["completed"] is False
    assert row["revision"] != ""
    assert row["quality"] == "not-assessed"
    assert completion_ledger(controller, tmp_path) == []


def test_finish_requires_a_saved_version_and_reports_the_dirty_draft(tmp_path):
    """验证 REP「保存成功但未声明完成」：有未保存草稿时 finish=False，原因可见且不抛异常。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    host.canvas.shapes = [rect("r1", box=(20, 20, 60, 80))]
    assert controller.edit("geometry", changed=host.canvas.shapes,
                           transaction_id="tx-move") is True

    assert controller.finish_round() is False

    row = controller.current_row(draft=True)
    assert row["completed"] is False
    assert row["is_draft"] is True          # visible reason: draft != saved
    assert not controller.degraded_reason  # refused, not a crash
    assert completion_ledger(controller, tmp_path) == []


def test_finish_after_a_successful_save_completes_the_round(tmp_path):
    """验证 REP「本轮处理完成绑定成功保存版本」：保存成功后 finish=True 并冻结成本版本。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    host.canvas.shapes = [rect("r1", box=(20, 20, 60, 80))]
    assert controller.edit("geometry", changed=host.canvas.shapes,
                           transaction_id="tx-move") is True
    save(controller, host.canvas.shapes)
    revision = controller.current_row()["revision"]

    assert controller.finish_round() is True

    row = controller.current_row()
    assert row["completed"] is True
    ledger = completion_ledger(controller, tmp_path)
    assert len(ledger) == 1
    completion_id, round_id, frozen_revision, payload = ledger[0]
    assert completion_id != ""
    assert round_id == row["round_id"]
    assert frozen_revision == revision
    cost = json.loads(payload)
    assert cost["id"] == completion_id
    assert cost["revision"] == revision
    assert cost["cost"]["completed"] is True
    assert cost["cost"]["modified_original"] == 1
    assert cost["cost"]["geometry_changed"] == 1


def test_resume_before_any_completion_is_refused(tmp_path):
    """验证 REP「完成数量去重」：未完成时 resume_round=False，不产生虚假完成事件。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()

    assert controller.resume_round() is False
    assert controller.current_row()["completed"] is False
    assert completion_ledger(controller, tmp_path) == []


# ---------------------------------------------------------------------------
# 2. idempotence and the completion ledger
# ---------------------------------------------------------------------------
def test_repeated_finish_is_idempotent_with_one_completion_record(tmp_path):
    """验证 REP「同图重复完成」：重复 finish=True 幂等，completion id 与记录数不变。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    host.canvas.shapes = [rect("r1", box=(20, 20, 60, 80))]
    assert controller.edit("geometry", changed=host.canvas.shapes,
                           transaction_id="tx-move") is True
    save(controller, host.canvas.shapes)
    assert controller.finish_round() is True
    first = completion_ledger(controller, tmp_path)

    assert controller.finish_round() is True
    second = completion_ledger(controller, tmp_path)

    assert len(first) == len(second) == 1
    assert first[0][0] == second[0][0]          # completion id unchanged
    assert controller.current_row()["completed"] is True
    assert controller.count() == 1              # one image, not two completions


def test_read_only_queries_and_resaving_do_not_invalidate_completion(tmp_path):
    """验证 REP「完成后再浏览/缩放不失效」：只读查询与同内容重存都不撤销完成。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    host.canvas.shapes = [rect("r1", box=(20, 20, 60, 80))]
    assert controller.edit("geometry", changed=host.canvas.shapes,
                           transaction_id="tx-move") is True
    save(controller, host.canvas.shapes)
    assert controller.finish_round() is True
    completion_id = completion_ledger(controller, tmp_path)[0][0]

    # Browsing/queries: no annotation content changes.
    assert controller.current_row()["completed"] is True
    assert controller.current_row(draft=True)["completed"] is True
    assert len(controller.rows()) == 1
    assert controller.count() == 1
    # Re-saving the identical content is still not a content change.
    save(controller, host.canvas.shapes)

    assert controller.current_row()["completed"] is True
    ledger = completion_ledger(controller, tmp_path)
    assert len(ledger) == 1
    assert ledger[0][0] == completion_id


# ---------------------------------------------------------------------------
# 3. invalidation: real content changes only
# ---------------------------------------------------------------------------
def test_a_new_edit_invalidates_completion_and_needs_a_new_save_and_finish(tmp_path):
    """验证 REP「完成后再次修改」：任何实际内容变化立即使完成失效，旧记录保留，新版本需重存+重完成。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    host.canvas.shapes = [rect("r1", box=(20, 20, 60, 80))]
    assert controller.edit("geometry", changed=host.canvas.shapes,
                           transaction_id="tx-move") is True
    save(controller, host.canvas.shapes)
    assert controller.finish_round() is True
    first_completion = completion_ledger(controller, tmp_path)[0][0]

    host.canvas.shapes = [rect("r1", label="cat", box=(20, 20, 60, 80))]
    assert controller.edit("relabel", changed=host.canvas.shapes,
                           transaction_id="tx-relabel") is True

    row = controller.current_row(draft=True)
    assert row["completed"] is False
    assert row["is_draft"] is True
    # The old completion record is kept for traceability.
    assert [entry[0] for entry in completion_ledger(controller, tmp_path)] == [first_completion]
    # A new explicit completion now requires a new successful save.
    assert controller.finish_round() is False

    save(controller, host.canvas.shapes)
    assert controller.finish_round() is True
    ledger = completion_ledger(controller, tmp_path)
    assert len(ledger) == 2
    assert ledger[1][0] != first_completion
    assert ledger[1][2] == controller.current_row()["revision"]
    assert ledger[1][2] != ledger[0][2]


def test_global_relabel_and_non_rectangle_edits_invalidate_completion(tmp_path):
    """验证 REP「完成后再次修改」：全局改类与非矩形等统计范围外内容变化同样使完成失效。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    assert controller.finish_round() is True
    assert controller.current_row()["completed"] is True

    # A global class rename is real annotation content.
    host.canvas.shapes = [rect("r1", label="vehicle")]
    assert controller.edit("taxonomy", changed=host.canvas.shapes,
                           transaction_id="tx-rename") is True
    assert controller.current_row()["completed"] is False

    save(controller, host.canvas.shapes)
    assert controller.finish_round() is True
    assert controller.current_row()["completed"] is True

    # A non-rectangle object is outside the counting scope but still content.
    host.canvas.shapes = [rect("r1", label="vehicle"), polygon()]
    assert controller.edit("create", changed=host.canvas.shapes,
                           transaction_id="tx-polygon") is True
    assert controller.current_row()["completed"] is False


def test_resume_then_finish_produces_a_new_completion_id(tmp_path):
    """验证 REP「完成后继续修正」：resume 撤销完成，再次明确完成得到新的 completion id。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    host.canvas.shapes = [rect("r1", box=(20, 20, 60, 80))]
    assert controller.edit("geometry", changed=host.canvas.shapes,
                           transaction_id="tx-move") is True
    save(controller, host.canvas.shapes)
    assert controller.finish_round() is True
    first_completion = completion_ledger(controller, tmp_path)[0][0]

    assert controller.resume_round() is True
    assert controller.current_row()["completed"] is False

    assert controller.finish_round() is True
    ledger = completion_ledger(controller, tmp_path)
    assert len(ledger) == 2
    assert ledger[0][0] == first_completion
    assert ledger[1][0] != first_completion
    assert ledger[1][2] == ledger[0][2]  # same saved version, new completion event


def test_discard_does_not_manufacture_a_completion(tmp_path):
    """验证 REP「丢弃修改」/完成绑定：discard 后 completed=False，且不产生完成记录。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    host.canvas.shapes = [rect("r1", box=(20, 20, 60, 80))]
    assert controller.edit("geometry", changed=host.canvas.shapes,
                           transaction_id="tx-move") is True

    assert controller.discard() is True

    row = controller.current_row(draft=True)
    assert row["completed"] is False
    assert row["is_draft"] is False   # back to the saved version, not completed
    assert completion_ledger(controller, tmp_path) == []


def test_completed_state_and_frozen_cost_survive_reopening(tmp_path):
    """验证 REP「完成后浏览不追加」：完成状态与冻结成本跨重开保留，仍只有一条完成记录。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    host.canvas.shapes = [rect("r1", box=(20, 20, 60, 80))]
    assert controller.edit("geometry", changed=host.canvas.shapes,
                           transaction_id="tx-move") is True
    save(controller, host.canvas.shapes)
    assert controller.finish_round() is True
    first_ledger = completion_ledger(controller, tmp_path)

    assert controller.leave_image() is True
    controller.enter_image()

    row = controller.current_row()
    assert row["completed"] is True
    assert row["round_id"] == first_ledger[0][1]
    second_ledger = completion_ledger(controller, tmp_path)
    assert len(second_ledger) == 1
    assert second_ledger[0] == first_ledger[0]


def test_discarding_a_post_completion_edit_keeps_the_old_record_only(tmp_path):
    """验证 REP「丢弃修改」+去重：完成后编辑又丢弃，旧完成记录保留且不产生新完成事件。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    host.canvas.shapes = [rect("r1", box=(20, 20, 60, 80))]
    assert controller.edit("geometry", changed=host.canvas.shapes,
                           transaction_id="tx-move") is True
    save(controller, host.canvas.shapes)
    assert controller.finish_round() is True
    first_completion = completion_ledger(controller, tmp_path)[0][0]

    host.canvas.shapes = [rect("r1", box=(30, 30, 70, 90))]
    assert controller.edit("geometry", changed=host.canvas.shapes,
                           transaction_id="tx-move-again") is True
    assert controller.current_row()["completed"] is False
    assert controller.discard() is True

    row = controller.current_row(draft=True)
    assert row["completed"] is False       # a discard is not a new completion
    assert row["is_draft"] is False
    ledger = completion_ledger(controller, tmp_path)
    assert [entry[0] for entry in ledger] == [first_completion]


# ---------------------------------------------------------------------------
# 4. batch completion discloses skipped images with a reason
# ---------------------------------------------------------------------------
def test_batch_completion_skips_a_dirty_draft_with_a_reason(tmp_path):
    """验证 REP「批量完成存在保存失败」：批量完成只完成有效保存版本，未保存者逐项披露原因。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    first_path = host.filename

    # A second image in the same scope, edited but never saved.
    second_image = tmp_path / "images" / "second.jpg"
    second_image.write_bytes(b"fake-image-bytes-second")
    host.filename = str(second_image)
    host.canvas.shapes = [rect("s1")]
    controller.enter_image()
    host.canvas.shapes = [rect("s1", box=(20, 20, 60, 80))]
    assert controller.edit("geometry", changed=host.canvas.shapes,
                           transaction_id="tx-second") is True

    report = controller.complete_scope()

    assert identities([first_path]) == set(report["completed"])
    assert len(report["skipped"]) == 1
    assert report["skipped"][0]["reason"] == "unsaved-draft"
    assert os.path.normcase(os.path.abspath(str(second_image))) == \
        report["skipped"][0]["path"]
