"""Task 4.6 -- a confirmed global class rename must reach the metrics store.

``LabelModifyDialog.modify_label`` rewrites the label JSON and then notifies
``metrics.taxonomy_saved``.  Its outer ``except Exception: logger.exception``
would swallow any wiring error, so these tests drive the *real* method with a
fake dialog and assert the recorded net result **and** that the failure path
was never entered.

Covered spec points: EVT-7 / EVT-7.1 (a one-to-one system rename is not a
personal relabel), EVT-7.2 (a personal relabel made before the rename keeps
its own class change), BASE-5 (merge -> not comparable), BASE-6 (only images
that already take part in the statistics are touched).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from anylabeling.views.labeling.correction_metrics.controller import (  # noqa: E402
    CorrectionMetricsController,
)
from anylabeling.views.labeling.widgets import (  # noqa: E402
    label_dialog as label_dialog_module,
)
from anylabeling.views.labeling.widgets.label_dialog import (  # noqa: E402
    LabelModifyDialog,
)

from . import synthetic  # noqa: E402


class _UniqueLabels:
    """Stand-in for ``unique_label_list`` (only ``lock_states`` is read)."""

    def __init__(self):
        self.lock_states = {}


class _LogSpy:
    """Records failures instead of printing them."""

    def __init__(self):
        self.exceptions = []
        self.errors = []

    def exception(self, *args, **kwargs):
        self.exceptions.append((args, kwargs))

    def error(self, *args, **kwargs):
        self.errors.append((args, kwargs))

    def warning(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


def _scene(work, shapes, image_name="scene.jpg"):
    """Write one image plus its label JSON below ``work``."""
    images = work / "images"
    labels = work / "labels"
    images.mkdir(parents=True, exist_ok=True)
    labels.mkdir(parents=True, exist_ok=True)
    image = images / image_name
    image.write_bytes(b"synthetic-image")
    label = labels / (image.stem + ".json")
    label.write_text(
        json.dumps({"shapes": shapes}, ensure_ascii=False), encoding="utf-8"
    )
    return image, label, labels


def _host(image, labels, shapes):
    """Minimal stand-in for ``LabelingWidget`` (what the dialog's parent needs)."""
    return SimpleNamespace(
        filename=str(image),
        output_dir=str(labels),
        canvas=SimpleNamespace(shapes=shapes),
        unique_label_list=_UniqueLabels(),
        _config={"language": "zh_CN"},
        correction_metrics=None,
    )


def _label_info(renames, extra=()):
    """``{"cat": "feline"}`` -> the dialog's per-class state mapping."""
    info = {old: {"value": "", "delete": False} for old in extra}
    info.update(
        {old: {"value": new, "delete": False} for old, new in renames.items()}
    )
    return info


def _run_modify(host, image_files, info, start=1, end=1):
    """Call the real ``modify_label`` with a fake ``self``."""
    dialog = SimpleNamespace(
        parent=host,
        image_file_list=list(image_files),
        start_index=start,
        end_index=end,
    )
    host.label_info = info
    return LabelModifyDialog.modify_label(dialog)


@pytest.fixture
def failure_log(monkeypatch):
    """Fail the test if the dialog swallows a metrics error."""
    spy = _LogSpy()
    monkeypatch.setattr(label_dialog_module, "logger", spy)
    return spy


def _assert_no_swallowed_error(spy):
    assert spy.exceptions == [], "metrics notification raised: %r" % (
        spy.exceptions,
    )
    assert spy.errors == [], "modify_label took its error path: %r" % (
        spy.errors,
    )


def _controller(work, host):
    controller = CorrectionMetricsController(
        host, language="zh_CN", storage_root=work / "db"
    )
    started = controller.start_scope(str(work / "images"), str(work / "labels"))
    assert started is True, controller.degraded_reason
    # The dialog reads the controller from ``parent.correction_metrics``;
    # ``start_metrics`` assigns it there, so the fake host must too.
    host.correction_metrics = controller
    return controller


def test_one_to_one_rename_is_not_a_personal_class_change(
    tmp_path, failure_log
):
    """一对一改名：class_changed 0、unchanged n、仍可比、无事务。"""
    shapes = [
        synthetic.rect("c-001", "cat", (10, 10, 60, 60)),
        synthetic.rect("c-002", "cat", (80, 10, 130, 60)),
        synthetic.rect("c-003", "dog", (150, 10, 200, 60)),
    ]
    image, label, labels = _scene(tmp_path, shapes)
    host = _host(image, labels, shapes)
    controller = _controller(tmp_path, host)
    try:
        assert controller.enter_image() is True
        assert controller.current_row(draft=True)["baseline_count"] == 3

        result = _run_modify(host, [image], _label_info({"cat": "feline"}, extra=("dog",)))

        assert result is True
        _assert_no_swallowed_error(failure_log)
        row = controller.current_row(draft=True)
        assert row["class_changed"] == 0
        assert row["geometry_changed"] == 0
        assert row["added"] == 0 and row["deleted"] == 0
        assert row["unchanged"] == 3
        assert row["modified_original"] == 0
        assert row["transactions"] == 0
        assert row["comparable"] is True
        assert "class-incomparable" not in row["issues"]
        saved = json.loads(label.read_text(encoding="utf-8"))
        assert [shape["label"] for shape in saved["shapes"]] == [
            "feline", "feline", "dog",
        ]
        assert row["touches"] == 0
        assert row["unique_objects"] == 0
        # A net result identical to the baseline proves nothing on its own:
        # assert the round's draft and alias map really moved.
        draft = controller._round._state["draft"]["objects"]
        assert draft["c-001"]["label"] == "feline"
        assert draft["c-002"]["label"] == "feline"
        assert draft["c-003"]["label"] == "dog"
        assert controller._round._state["alias"]["cat"] == "feline"
    finally:
        controller.stop()


def test_personal_relabel_before_the_rename_is_preserved(
    tmp_path, failure_log
):
    """先个人改类 dog->cat，再全局 cat->feline：保留 1 次真实改类。"""
    shapes = [
        synthetic.rect("c-001", "cat", (10, 10, 60, 60)),
        synthetic.rect("c-002", "cat", (80, 10, 130, 60)),
        synthetic.rect("c-003", "dog", (150, 10, 200, 60)),
    ]
    image, label, labels = _scene(tmp_path, shapes)
    host = _host(image, labels, shapes)
    controller = _controller(tmp_path, host)
    try:
        assert controller.enter_image() is True
        assert controller.edit(
            "relabel",
            changed=[{**shapes[2], "label": "cat"}],
            transaction_id="personal-relabel",
        ) is True
        relabelled = [dict(shape) for shape in shapes]
        relabelled[2] = {**shapes[2], "label": "cat"}
        label.write_text(
            json.dumps({"shapes": relabelled}, ensure_ascii=False),
            encoding="utf-8",
        )

        result = _run_modify(host, [image], _label_info({"cat": "feline"}, extra=("dog",)))

        assert result is True
        _assert_no_swallowed_error(failure_log)
        row = controller.current_row(draft=True)
        assert row["transactions"] == 1
        assert row["class_changed"] == 1
        assert row["modified_original"] == 1
        assert row["unchanged"] == 2
        assert row["geometry_changed"] == 0
        assert row["comparable"] is True
    finally:
        controller.stop()


def test_merge_makes_the_class_dimension_unavailable(tmp_path, failure_log):
    """两旧类合并为同一新类：comparable False，依赖 C 的字段全为 None。"""
    shapes = [
        synthetic.rect("c-001", "cat", (10, 10, 60, 60)),
        synthetic.rect("c-002", "dog", (80, 10, 130, 60)),
    ]
    image, label, labels = _scene(tmp_path, shapes)
    host = _host(image, labels, shapes)
    controller = _controller(tmp_path, host)
    try:
        assert controller.enter_image() is True

        result = _run_modify(
            host, [image], _label_info({"cat": "animal", "dog": "animal"})
        )

        assert result is True
        _assert_no_swallowed_error(failure_log)
        row = controller.current_row(draft=True)
        assert row["comparable"] is False
        assert "class-incomparable" in row["issues"]
        assert row["class_changed"] is None
        assert row["modified_original"] is None
        assert row["unchanged"] is None
        assert row["modified_rate"] is None
        assert row["unchanged_rate"] is None
        assert row["geometry_changed"] == 0
        assert row["added"] == 0 and row["deleted"] == 0
        assert row["baseline_count"] == 2
    finally:
        controller.stop()


def test_image_outside_the_scope_is_never_given_a_round(
    tmp_path, failure_log
):
    """未纳入统计的图片：调用不建轮次、计数不变。"""
    shapes = [synthetic.rect("c-001", "cat", (10, 10, 60, 60))]
    image, label, labels = _scene(tmp_path, shapes)
    host = _host(image, labels, shapes)
    controller = _controller(tmp_path, host)
    try:
        assert controller.count() == 0

        result = _run_modify(host, [image], _label_info({"cat": "feline"}, extra=("dog",)))

        assert result is True
        _assert_no_swallowed_error(failure_log)
        assert controller.count() == 0
        assert controller.current_row() is None
        saved = json.loads(label.read_text(encoding="utf-8"))
        assert saved["shapes"][0]["label"] == "feline"
    finally:
        controller.stop()


def test_existing_round_that_is_not_current_still_receives_the_rename(
    tmp_path, failure_log
):
    """非当前图片的已有轮次：通过 store.latest 命中并应用映射。"""
    first = [synthetic.rect("c-001", "cat", (10, 10, 60, 60))]
    second = [synthetic.rect("d-001", "dog", (10, 10, 60, 60))]
    image_a, label_a, labels = _scene(tmp_path, first, "a.jpg")
    image_b, label_b, _ = _scene(tmp_path, second, "b.jpg")
    host = _host(image_a, labels, first)
    controller = _controller(tmp_path, host)
    try:
        assert controller.enter_image() is True
        round_a = controller._round
        assert round_a is not None

        host.filename = str(image_b)
        host.canvas.shapes = second
        assert controller.enter_image() is True
        assert controller._round is not round_a

        result = _run_modify(host, [image_a], _label_info({"cat": "feline"}, extra=("dog",)))

        assert result is True
        _assert_no_swallowed_error(failure_log)
        stored = controller._store.latest(str(image_a), str(label_a))
        assert stored is not None and stored.round_id == round_a.round_id
        row = stored.row(draft=True)
        assert row["class_changed"] == 0
        assert row["unchanged"] == 1
        assert row["comparable"] is True
    finally:
        controller.stop()
