"""Task 10.4 -- rolling the statistics back must not damage the annotations.

Qt-free service-level proof:

* switching the feature off creates no database and no controller;
* every observer call is inert (``None``) when no session is attached;
* a stopped session exposes safe defaults and its database stays readable;
* the annotation JSON is byte-identical through a full record/save/stop cycle;
* the training payload never gains a statistics key;
* the database can be copied as a backup, and deleting it loses only history.

The GUI layer (menu enablement, panel, dialogs) is out of scope here and is
listed as uncovered in ``.local/stage/team/rollback.md``.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from types import SimpleNamespace

import pytest

from anylabeling.services.correction_metrics import export, reporting
from anylabeling.services.correction_metrics.storage import MetricsStore
from anylabeling.views.labeling.correction_metrics.controller import (
    CorrectionMetricsController,
)
from anylabeling.views.labeling.correction_metrics.hooks import (
    metrics_pending_message,
    notify_metrics,
)

from . import synthetic

LABEL_PAYLOAD_KEYS = {
    "version", "flags", "shapes", "imagePath", "imageData",
    "imageHeight", "imageWidth",
}


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def _host(work, shapes=(), language="zh_CN", output_dir=None):
    images = work / "images"
    images.mkdir(parents=True, exist_ok=True)
    labels = work / "labels" if output_dir is None else output_dir
    labels.mkdir(parents=True, exist_ok=True)
    image = images / "scene.jpg"
    if not image.exists():
        image.write_bytes(b"synthetic-image")
    statuses = []
    return SimpleNamespace(
        filename=str(image),
        output_dir=str(labels),
        canvas=SimpleNamespace(shapes=list(shapes)),
        unique_label_list=SimpleNamespace(lock_states={}),
        _config={"language": language, "correction_metrics_enabled": False},
        correction_metrics=None,
        status=lambda text, timeout=0: statuses.append(text),
        open_settings_dialog=lambda **kwargs: None,
        tr=lambda text: text,
        _statuses=statuses,
    )


def _controller(work, host, **kwargs):
    controller = CorrectionMetricsController(
        host, language="zh_CN", storage_root=work / "db", **kwargs
    )
    assert controller.start_scope(str(work / "images"),
                                  str(work / "labels")) is True
    host.correction_metrics = controller
    return controller


def _scene(work, shapes, label_name="scene.json"):
    labels = work / "labels"
    labels.mkdir(parents=True, exist_ok=True)
    label = labels / label_name
    payload = {
        "version": "2.4.0",
        "flags": {},
        "shapes": shapes,
        "imagePath": "scene.jpg",
        "imageData": None,
        "imageHeight": 480,
        "imageWidth": 640,
    }
    label.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return label


# ---------------------------------------------------------------------------
# 1) the feature switched off costs nothing
# ---------------------------------------------------------------------------
def test_disabled_setting_creates_no_database_and_no_controller(tmp_path,
                                                                monkeypatch):
    """设置关闭 → 入口不建 controller、不建 sqlite。"""
    metrics_dir = tmp_path / "metrics"
    monkeypatch.setenv("XANYLABELING_METRICS_DIR", str(metrics_dir))

    from anylabeling.views.labeling.label_widget import LabelingWidget

    host = _host(tmp_path)
    host._config["correction_metrics_enabled"] = False

    assert LabelingWidget.open_correction_metrics(host) is None

    assert host.correction_metrics is None
    assert not metrics_dir.exists() or not list(metrics_dir.iterdir())
    assert getattr(host, "_metrics_timer", None) is None


def test_notify_metrics_is_inert_without_a_session():
    """host 没有/为空 controller 时，所有 hook 返回 None 且不抛。"""
    for host in (SimpleNamespace(),
                 SimpleNamespace(correction_metrics=None)):
        for operation in ("edit", "prepare_save", "save_result", "discard",
                          "prediction_applied", "time_checkpoint"):
            assert notify_metrics(host, operation) is None, operation


def test_notify_metrics_swallows_observer_errors():
    """观察者抛异常时不冒泡到保存路径。"""
    calls = []

    class Boom:
        def edit(self, *args, **kwargs):
            raise RuntimeError("observer down")

        def degrade(self, operation, error=None):
            calls.append(operation)

    host = SimpleNamespace(correction_metrics=Boom())

    assert notify_metrics(host, "edit") is None
    assert calls == ["edit"]


# ---------------------------------------------------------------------------
# 2) stopping a running session
# ---------------------------------------------------------------------------
def test_stopped_session_returns_safe_defaults(tmp_path):
    """stop() 后 enabled False，后续操作返回安全默认值且不抛。"""
    shapes = [synthetic.rect("c-001", "cat", (0, 0, 10, 10))]
    work = synthetic.workdir()
    host = _host(work, shapes)
    controller = _controller(work, host)
    controller.enter_image()
    assert controller.enabled is True

    controller.stop()

    assert controller.enabled is False
    assert controller.current_row() is None
    assert controller.rows() == []
    assert controller.count() == 0
    assert controller.edit("create", changed=shapes) is False
    assert controller.prepare_save() is None
    assert controller.save_result(None, True) is False
    assert controller.discard() is False
    assert controller.prediction_applied(SimpleNamespace(provenance={})) is False
    state = controller.state()
    assert set(state) >= {"state", "seconds", "paused", "idle_waiting", "degraded"}
    assert state["seconds"] == 0.0
    controller.stop()          # idempotent


def test_stopped_database_is_still_readable_and_exportable(tmp_path):
    """停用后统计库仍在，且可被新实例读出并导出 CSV。"""
    shapes = [synthetic.rect("c-001", "cat", (0, 0, 10, 10)),
              synthetic.rect("c-002", "dog", (20, 20, 30, 30))]
    work = synthetic.workdir()
    host = _host(work, shapes)
    label = _scene(work, shapes)
    controller = _controller(work, host)
    controller.enter_image()
    # The baseline already contains these shapes, so a real content change is
    # needed before anything can be counted.
    assert controller.edit("geometry",
                           changed=[synthetic.moved(shapes[0], 5, 5)],
                           transaction_id="t1") is True
    token = controller.prepare_save(str(label), shapes)
    assert controller.save_result(token, True) is True
    database = controller._store.path
    controller.stop()
    assert database.exists()

    reopened = MetricsStore(database, dataset_id="ds")
    try:
        rows = [reporting.saved_row(row) for row in reopened.rows()]
    finally:
        reopened.close()

    assert len(rows) == 1
    assert rows[0]["revision"]
    out = tmp_path / "after-rollback.csv"
    export.export_csv(out, rows, kind="images")
    assert out.exists() and out.stat().st_size > 0


# ---------------------------------------------------------------------------
# 3) the annotation content is untouched
# ---------------------------------------------------------------------------
def test_annotation_json_is_byte_identical_through_the_whole_cycle(tmp_path):
    """启用→记录→保存检查点→关闭：标注 JSON 字节不变、键集不变。"""
    shapes = [synthetic.rect("c-001", "cat", (0, 0, 10, 10))]
    work = synthetic.workdir()
    host = _host(work, shapes)
    label = _scene(work, shapes)
    before = label.read_bytes()
    before_keys = set(json.loads(before))

    controller = _controller(work, host)
    controller.enter_image()
    try:
        controller.edit("geometry", changed=[synthetic.moved(shapes[0], 3, 4)],
                        transaction_id="t1")
        token = controller.prepare_save(str(label), shapes)
        controller.save_result(token, True)
        notify_metrics(host, "edit", "create", changed=shapes)
    finally:
        controller.stop()

    assert label.read_bytes() == before
    assert set(json.loads(label.read_text(encoding="utf-8"))) == before_keys
    assert before_keys == LABEL_PAYLOAD_KEYS


def test_training_payload_never_gains_a_statistics_key():
    """训练导出 payload 的键集合不因统计而改变。"""
    payload = {
        "version": "2.4.0", "flags": {}, "shapes": [],
        "imagePath": "a.jpg", "imageData": None,
        "imageHeight": 100, "imageWidth": 100,
    }
    host = SimpleNamespace(correction_metrics=None)
    notify_metrics(host, "prepare_save")
    notify_metrics(host, "save_result", None, True)

    assert set(payload) == LABEL_PAYLOAD_KEYS
    for word in ("metrics", "correction", "transaction", "elapsed"):
        assert word not in "".join(payload).casefold()


# ---------------------------------------------------------------------------
# 4) rollback = the statistics module is gone
# ---------------------------------------------------------------------------
def test_missing_workspace_makes_the_observer_inert(monkeypatch):
    """metrics_available()=False：hook 空转、有提示文案、保存流程仍成功。"""
    from anylabeling.views.labeling.correction_metrics import hooks

    monkeypatch.setattr(hooks, "metrics_available", lambda: False)

    assert hooks.metrics_available() is False
    assert metrics_pending_message("zh_CN")
    assert metrics_pending_message("en_US")

    def save():
        return True

    host = SimpleNamespace(correction_metrics=None)
    assert notify_metrics(host, "prepare_save") is None
    assert save() is True
    assert host.correction_metrics is None


# ---------------------------------------------------------------------------
# 5) backup / delete the database
# ---------------------------------------------------------------------------
def test_database_can_be_copied_as_a_backup(tmp_path):
    """先 close 再复制（WAL）：副本可读回同样 rows，原库不受影响。"""
    shapes = [synthetic.rect("c-001", "cat", (0, 0, 10, 10))]
    work = synthetic.workdir()
    db = work / "rollback.sqlite3"
    store = MetricsStore(db, dataset_id="ds")
    try:
        store.open_round(str(work / "a.jpg"), str(work / "a.json"),
                         "digest-a", shapes, origin="unknown-existing",
                         saved=True)
        assert store.flush() is True
    finally:
        store.close()
    assert not list(work.glob("rollback.sqlite3-wal"))

    backup = tmp_path / "backup.sqlite3"
    shutil.copy2(db, backup)

    for path in (db, backup):
        reopened = MetricsStore(path, dataset_id="ds")
        try:
            assert len(reopened.rows()) == 1, path
        finally:
            reopened.close()


def test_deleting_the_database_loses_only_history(tmp_path):
    """删除统计库：旧标注仍完好，重启后只是新建空库。"""
    shapes = [synthetic.rect("c-001", "cat", (0, 0, 10, 10))]
    work = synthetic.workdir()
    host = _host(work, shapes)
    label = _scene(work, shapes)
    before = label.read_bytes()

    controller = _controller(work, host)
    controller.enter_image()
    old_round = controller.current_row()["round_id"]
    database = controller._store.path
    controller.stop()
    assert database.exists()

    for path in [database] + list(database.parent.glob(database.name + "-*")):
        path.unlink()

    # The annotation is untouched and still a valid document.
    assert label.read_bytes() == before
    assert set(json.loads(label.read_text(encoding="utf-8"))) == LABEL_PAYLOAD_KEYS

    # A fresh controller simply starts with an empty database again.
    fresh = _host(work, shapes)
    again = _controller(work, fresh)
    try:
        assert again.enter_image() is True
        assert again.enabled is True
        # Only the history is gone: a brand-new round was opened, the deleted
        # one is not resurrected.
        assert again.count() == 1
        assert again.current_row()["round_id"] != old_round
    finally:
        again.stop()


def test_unreadable_future_database_does_not_block_the_annotations(tmp_path):
    """版本过新的统计库：降级（不覆盖），标注文件不受影响。"""
    work = synthetic.workdir()
    host = _host(work, [])
    label = _scene(work, [])
    before = label.read_bytes()

    dbpath = work / "db" / "future.sqlite3"
    dbpath.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(dbpath)
    db.execute("PRAGMA user_version=99")
    db.execute("CREATE TABLE rounds(id TEXT PRIMARY KEY)")
    db.commit()
    db.close()

    broken = MetricsStore(dbpath, dataset_id="ds")
    assert broken.error and "version" in broken.error
    broken.close()

    controller = CorrectionMetricsController(host, language="zh_CN",
                                             storage_root=work / "db2")
    assert controller.start_scope(str(work / "images"), str(work / "labels")) is True
    controller.stop()
    assert label.read_bytes() == before


def test_fresh_controller_without_a_scope_is_safe():
    """未启用/未开范围的新 controller 只返回安全默认值。"""
    controller = CorrectionMetricsController(SimpleNamespace(), language="en_US")

    assert controller.enabled is False
    assert controller.current_row() is None
    assert controller.rows() == []
    assert controller.count() == 0
    assert controller.edit("create") is False
    assert controller.prepare_save() is None
    assert controller.degraded_reason is None
    controller.stop()
