"""Behavior checks for stable incremental thumbnail updates."""

from dataclasses import replace

from PyQt6 import QtCore, QtGui, QtTest

import pytest
from PyQt6 import QtWidgets
from tests.test_dataset_thumbnail_browser import FakeController, _ref
from anylabeling.views.labeling.widgets.dataset_thumbnail.browser import (
    DatasetLabelThumbnailWindow,
)
from anylabeling.views.labeling.widgets.dataset_thumbnail.pipeline import (
    ThumbnailRenderResult,
)
from anylabeling.views.labeling.widgets.dataset_thumbnail.page_diff import (
    compare_pages,
    identity,
)


@pytest.fixture(scope="module")
def qapp():
    """Reuse one QApplication for incremental model tests."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app
    app.processEvents()


def test_unrelated_save_keeps_images_and_selection(qapp, tmp_path):
    """A save outside the query does not rebuild or request any card."""
    refs = tuple(_ref(tmp_path, i) for i in range(8))
    controller = FakeController(refs)
    window = DatasetLabelThumbnailWindow(controller, "p", str(tmp_path))
    resets = QtTest.QSignalSpy(window._model.modelReset)
    image = QtGui.QImage(12, 12, QtGui.QImage.Format.Format_RGB32)
    window._model._images[window._model.item_key(refs[0])] = image
    selection = window.view.selectionModel()
    selection.select(
        window._model.index(0, 0),
        QtCore.QItemSelectionModel.SelectionFlag.Select,
    )
    calls = []
    window._renderer.request = lambda *a, **k: calls.append(a)
    window._visible_timer.stop()
    window._sync_page()
    assert not resets and not calls
    assert (
        window._model._images[window._model.item_key(refs[0])].cacheKey()
        == image.cacheKey()
    )
    assert selection.isSelected(window._model.index(0, 0))
    window.close()


def test_remove_and_reorder_preserve_images_and_reject_old_crop(
    qapp, tmp_path
):
    """Survivors keep QImages and old geometry cannot overwrite a new crop."""
    refs = tuple(_ref(tmp_path, i) for i in range(4))
    controller = FakeController(refs)
    window = DatasetLabelThumbnailWindow(controller, "p", str(tmp_path))
    model = window._model
    image = QtGui.QImage(12, 12, QtGui.QImage.Format.Format_RGB32)
    model._images[model.item_key(refs[2])] = image
    changed = replace(refs[1], bbox=(0, 0, 5, 5))
    controller.refs = (refs[2], changed, refs[3])
    resets = QtTest.QSignalSpy(model.modelReset)
    window._sync_page()
    assert not resets
    assert (
        model._images[model.item_key(refs[2])].cacheKey() == image.cacheKey()
    )
    model.set_render_result(
        ThumbnailRenderResult(0, refs[1], None, b"png", image=image)
    )
    assert model.item_key(changed) not in model._images
    window.close()


def test_last_item_keeps_label_and_new_member_is_seen(qapp, tmp_path):
    """Zero results preserve the filter and a newly matching file appears."""
    first = _ref(tmp_path)
    controller = FakeController([first])
    window = DatasetLabelThumbnailWindow(controller, "p", str(tmp_path))
    controller.refs = (replace(first, label="other"),)
    window._sync_page()
    assert window._selected_label == "person" and window._model.rowCount() == 0
    new = _ref(tmp_path, 2)
    controller.refs += (new,)
    window._sync_page()
    assert window._model._items == (new,)
    window.close()


def test_page_diff_uses_identity_not_array_index(tmp_path):
    """Reordering metadata does not count as a different rendered object."""
    ref = _ref(tmp_path)
    changed = replace(ref, shape_index=7, label="new", signature="new")
    diff = compare_pages([ref], [changed])
    assert diff.changed == frozenset([identity(ref)])
    assert not diff.images and not diff.added and not diff.removed
