"""Offscreen tests for the dataset label thumbnail browser."""

import json
import time

import pytest

QtCore = pytest.importorskip("PyQt6.QtCore")
QtGui = pytest.importorskip("PyQt6.QtGui")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from anylabeling.views.labeling.dataset_index import (
    DatasetThumbnailPage,
    DatasetThumbnailRef,
)
from anylabeling.views.labeling.widgets.dataset_thumbnail import (
    DatasetLabelThumbnailWindow,
    ThumbnailRenderer,
)


@pytest.fixture(scope="module")
def qapp():
    """Create one offscreen QApplication for browser tests."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app
    app.processEvents()


class FakeController(QtCore.QObject):
    """Small query controller matching the browser's read-only contract."""

    state_changed = QtCore.pyqtSignal(object, object)
    file_refresh_finished = QtCore.pyqtSignal(str, bool, str)

    def __init__(self, refs):
        """Initialize a ready controller with one label's references."""
        super().__init__()
        self.refs = tuple(refs)
        self.is_query_ready = True
        self.state_value = "ready"

    def query_label_counts(self):
        """Return the single fake label and its count."""
        return [("person", len(self.refs))]

    def query_thumbnail_objects(self, label, limit=100, offset=0):
        """Return a bounded page from the fake references."""
        items = tuple(ref for ref in self.refs if ref.label == label)
        return DatasetThumbnailPage(
            label,
            len(items),
            min(limit, 100),
            offset,
            items[offset : offset + limit],
        )


def _ref(tmp_path, index=0):
    """Create a reference and a tiny valid source image."""
    image_path = tmp_path / f"image-{index}.png"
    image = QtGui.QImage(32, 24, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor("#dd8844"))
    assert image.save(str(image_path), "PNG")
    return DatasetThumbnailRef(
        str(image_path),
        str(tmp_path / f"image-{index}.json"),
        index,
        0,
        f"{index:032x}",
        "person",
        (2.0, 3.0, 20.0, 18.0),
    )


def _wait_for_results(app, results, count):
    """Process queued Qt events until enough render results arrive."""
    deadline = time.monotonic() + 3
    while len(results) < count and time.monotonic() < deadline:
        app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.01)


def test_renderer_groups_and_renders_visible_source(qapp, tmp_path):
    """A valid crop is emitted as PNG bytes with the current generation."""
    ref = _ref(tmp_path)
    renderer = ThumbnailRenderer(str(tmp_path / "cache"), parent=qapp)
    results = []
    renderer.result_ready.connect(results.append)
    generation = renderer.request([ref], size=(64, 64))
    _wait_for_results(qapp, results, 1)

    assert len(results) == 1
    assert results[0].generation == generation
    assert results[0].error == ""
    assert results[0].image_bytes
    renderer.close()


def test_browser_pages_and_selection_are_bounded(qapp, tmp_path):
    """The browser exposes one page and emits only selected valid refs."""
    refs = [_ref(tmp_path, index) for index in range(3)]
    controller = FakeController(refs)
    window = DatasetLabelThumbnailWindow(
        controller,
        "project",
        str(tmp_path),
        lambda: ["person", "other"],
    )
    window.show()
    qapp.processEvents()

    assert window._model.rowCount() == 3
    assert window.next_button.isEnabled() is False
    window.view.selectionModel().select(
        window._model.index(0, 0),
        QtCore.QItemSelectionModel.SelectionFlag.Select,
    )
    assert window._selected_refs() == (refs[0],)
    window.close()
    qapp.processEvents()
