"""Exercise real Qt confirmation, worker commit, inverse and index refresh."""

import json
from dataclasses import replace
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

from anylabeling.views.labeling.dataset_index import DatasetFilterIndex
from anylabeling.views.labeling.widgets.dataset_thumbnail import (
    DatasetLabelThumbnailWindow,
)
from anylabeling.views.labeling.widgets.object_relabel import (
    MarkedObjectRef,
    build_object_relabel_plan,
)
from anylabeling.views.labeling.widgets.object_relabel_dialog import (
    run_object_relabel_flow,
)


class Controller(QtCore.QObject):
    """Use a real SQLite index behind the browser contract."""

    is_query_ready = True
    state_value = "ready"
    is_busy = False

    def __init__(self, index) -> None:
        """Keep the index alive during worker execution."""
        super().__init__()
        self.index = index

    def __getattr__(self, name: str):
        """Forward read-only queries."""
        return getattr(self.index, name)


def test_confirm_commit_undo_and_preserve_other_fields(qapp, tmp_path) -> None:
    """UI confirmations and both writes use the same real transaction path."""
    translator = QtCore.QTranslator()
    old_font = qapp.font()
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    if font_path.exists():
        font_id = QtGui.QFontDatabase.addApplicationFont(str(font_path))
        families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
        if families:
            qapp.setFont(QtGui.QFont(families[0], 9))
    qm = Path("anylabeling/resources/translations/zh_CN.qm")
    assert translator.load(str(qm.resolve()))
    qapp.installTranslator(translator)
    image_path = tmp_path / "sample.png"
    image = QtGui.QImage(320, 240, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor("#688aaa"))
    assert image.save(str(image_path))
    json_path = image_path.with_suffix(".json")
    original = dict(
        imagePath="sample.png",
        shapes=[
            dict(
                label="person",
                shape_type="rectangle",
                points=[[20, 20], [100, 180]],
                xanylabeling_shape_id="1" * 32,
                description="keep",
                group_id=7,
            ),
            dict(
                label="person",
                shape_type="rectangle",
                points=[[150, 20], [220, 180]],
                xanylabeling_shape_id="2" * 32,
                description="other",
                group_id=8,
            ),
        ],
    )
    json_path.write_text(json.dumps(original), encoding="utf-8")
    index = DatasetFilterIndex(str(tmp_path / "index.sqlite"))
    index.rebuild([str(image_path)], dataset_root=str(tmp_path))
    window = DatasetLabelThumbnailWindow(Controller(index), "p", str(tmp_path))
    window._renderer.disk.root = str(tmp_path / "cache")
    window.show()
    finished, failures, confirmations = [], [], []
    parent = QtWidgets.QWidget()
    timer = QtCore.QTimer()

    def confirm() -> None:
        """Approve only the test's actual relabel confirmation dialog."""
        for widget in qapp.topLevelWidgets():
            if (
                isinstance(widget, QtWidgets.QMessageBox)
                and widget.isVisible()
            ):
                confirmations.append(widget.text())
                assert "sample.png" in widget.detailedText()
                widget.done(QtWidgets.QMessageBox.StandardButton.Yes)

    def applied(result) -> None:
        """Refresh from disk as the main window's relabel callback does."""
        index.rebuild([str(image_path)], dataset_root=str(tmp_path))
        window.apply_relabel_result(result)
        window.refresh_from_index()
        finished.append(result)

    timer.timeout.connect(confirm)
    timer.start(10)
    ref = MarkedObjectRef("p", str(image_path), "1" * 32, "person")
    plan = build_object_relabel_plan(
        [ref], "p", "head", str(tmp_path), lambda _image: str(json_path)
    )
    try:
        assert run_object_relabel_flow(
            parent,
            plan,
            str(tmp_path),
            str(tmp_path),
            applied,
            failures.append,
            show_result_dialog=False,
        )
        for _ in range(300):
            if finished or failures:
                break
            QtTest.QTest.qWait(10)
        assert not failures and len(finished) == 1
        assert window.undo_button.isEnabled()
        after = json.loads(json_path.read_text(encoding="utf-8"))
        assert after["shapes"][0]["label"] == "head"
        assert after["shapes"][1] == original["shapes"][1]
        assert "单个对象" in confirmations[0]
        QtTest.QTest.qWait(100)
        preview = Path(
            "openspec/changes/improve-thumbnail-review-safety-and-performance/validation-preview.png"
        )
        assert window.grab().save(str(preview))
        record = window._single_undo
        inverse = replace(
            plan, target_label=record.old_label, undo_record=record
        )
        requested = []
        window.undo_requested.connect(requested.append)
        QtTest.QTest.mouseClick(
            window.undo_button, QtCore.Qt.MouseButton.LeftButton
        )
        assert requested == [record]
        assert run_object_relabel_flow(
            parent,
            inverse,
            str(tmp_path),
            str(tmp_path),
            applied,
            failures.append,
            show_result_dialog=False,
        )
        for _ in range(300):
            if len(finished) == 2 or failures:
                break
            QtTest.QTest.qWait(10)
        assert not failures and len(finished) == 2
        assert json.loads(json_path.read_text(encoding="utf-8")) == original
        assert not window.undo_button.isEnabled()
        assert index.query_label_counts() == [("person", 2)]
    finally:
        timer.stop()
        qapp.removeTranslator(translator)
        qapp.setFont(old_font)
        window.close()
        parent.close()
        index.close()
