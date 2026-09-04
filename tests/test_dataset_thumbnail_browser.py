"""Offscreen tests for the dataset label thumbnail browser."""

import json
import time

import pytest

QtCore = pytest.importorskip("PyQt6.QtCore")
QtGui = pytest.importorskip("PyQt6.QtGui")
QtTest = pytest.importorskip("PyQt6.QtTest")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from anylabeling.views.labeling.dataset_index import (
    DatasetThumbnailPage,
    DatasetThumbnailLocation,
    DatasetThumbnailRef,
)
from anylabeling.views.labeling.widgets.dataset_thumbnail import (
    DatasetLabelThumbnailWindow,
    ThumbnailRenderer,
)
from anylabeling.views.labeling.widgets.object_relabel import (
    ObjectMutationResult,
    ObjectRelabelResult,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
)
from anylabeling.views.labeling.widgets.label_batch import FileOperationResult


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
    progress_changed = QtCore.pyqtSignal(int, int, str)
    busy_changed = QtCore.pyqtSignal(bool)

    def __init__(self, refs):
        """Initialize a ready controller with one label's references."""
        super().__init__()
        self.refs = tuple(refs)
        self.is_query_ready = True
        self.state_value = "ready"
        self.is_busy = False
        self.query_calls = 0
        self.refresh_calls = 0
        self.rebuild_calls = 0

    def query_label_counts(self):
        """Return deterministic fake label counts."""
        labels = sorted({ref.label for ref in self.refs})
        return [
            (label, sum(ref.label == label for ref in self.refs))
            for label in labels
        ]

    def query_thumbnail_objects(self, label, limit=100, offset=0):
        """Return a bounded page from the fake references."""
        self.query_calls += 1
        items = tuple(ref for ref in self.refs if ref.label == label)
        return DatasetThumbnailPage(
            label,
            len(items),
            min(limit, 100),
            offset,
            items[offset : offset + limit],
        )

    def query_thumbnail_location(self, image_path, shape_id):
        """Return a unique label-relative location for one fake object."""
        matches = [
            ref
            for ref in self.refs
            if ref.image_path == image_path and ref.shape_id == shape_id
        ]
        if len(matches) != 1:
            return None
        ref = matches[0]
        label_refs = [item for item in self.refs if item.label == ref.label]
        return DatasetThumbnailLocation(
            ref.image_path,
            ref.json_path,
            ref.sort_order,
            ref.shape_index,
            ref.shape_id,
            ref.label,
            label_refs.index(ref),
        )

    def refresh(self):
        """Record one incremental recovery request."""
        self.refresh_calls += 1
        return True

    def rebuild(self):
        """Record one full recovery request."""
        self.rebuild_calls += 1
        return True


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


def test_renderer_uses_bounded_pool_and_deduplicates_inflight(qapp, tmp_path):
    """Repeated visibility requests do not enqueue the same crop twice."""
    ref = _ref(tmp_path)
    renderer = ThumbnailRenderer(
        str(tmp_path / "cache"), max_concurrency=1, parent=qapp
    )
    generation = renderer.invalidate()

    renderer.request([ref], generation=generation)
    first_inflight = set(renderer._inflight)
    renderer.request([ref], generation=generation)

    assert renderer._pool.maxThreadCount() == 1
    assert first_inflight
    assert renderer._inflight == first_inflight
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


def test_browser_is_a_resizable_top_level_window_and_closes(qapp, tmp_path):
    """The browser owns normal window chrome and emits one close lifecycle."""
    controller = FakeController([_ref(tmp_path)])
    parent = QtWidgets.QWidget()
    window = DatasetLabelThumbnailWindow(
        controller, "project", str(tmp_path), parent=parent
    )
    closed = []
    window.closed.connect(lambda: closed.append(True))

    assert window.isWindow()
    assert window.testAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
    assert window.minimumSize() != window.maximumSize()
    window.close()
    qapp.processEvents()
    assert closed == [True]


def test_page_reloads_clamp_after_last_page_shrinks(qapp, tmp_path):
    """A stale last-page offset falls back to the final valid page."""
    image_path = str(tmp_path / "shared.png")
    refs = tuple(
        DatasetThumbnailRef(
            image_path,
            str(tmp_path / "shared.json"),
            index,
            index,
            f"{index:032x}",
            "person",
            (1.0, 1.0, 10.0, 10.0),
        )
        for index in range(101)
    )
    controller = FakeController(refs)
    window = DatasetLabelThumbnailWindow(controller, "project", str(tmp_path))
    window._page = 1
    controller.refs = refs[:4]
    window._load_page()

    assert window._page == 0
    assert window._model.rowCount() == 4
    assert "Page 1 / 1" in window.page_label.text()
    window.close()
    qapp.processEvents()


def test_partial_failure_keeps_selection_and_error(qapp, tmp_path):
    """Failed objects remain selected and visibly retryable after a batch."""
    refs = [_ref(tmp_path, index) for index in range(2)]
    controller = FakeController(refs)
    window = DatasetLabelThumbnailWindow(controller, "project", str(tmp_path))
    selection = window.view.selectionModel()
    for row in range(2):
        selection.select(
            window._model.index(row, 0),
            QtCore.QItemSelectionModel.SelectionFlag.Select,
        )
    result = ObjectRelabelResult(
        transaction_id="tx",
        phase="committed",
        cancelled=False,
        objects=(
            ObjectMutationResult(
                ("project", refs[0].image_path, refs[0].shape_id),
                STATUS_SUCCEEDED,
            ),
            ObjectMutationResult(
                ("project", refs[1].image_path, refs[1].shape_id),
                STATUS_FAILED,
                "identity changed",
            ),
        ),
    )

    window.apply_relabel_result(result)

    assert window._selected_refs() == (refs[1],)
    assert (
        window._model.index(1, 0).data(window._model.MutationErrorRole)
        == "identity changed"
    )
    assert window._model.is_selectable(1)
    window.close()
    qapp.processEvents()


def test_refresh_notifications_are_coalesced(qapp, tmp_path):
    """Many per-file completions trigger only one bounded page reload."""
    controller = FakeController([_ref(tmp_path)])
    window = DatasetLabelThumbnailWindow(controller, "project", str(tmp_path))
    baseline = controller.query_calls
    for index in range(5):
        controller.file_refresh_finished.emit(str(index), True, "")
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert controller.query_calls == baseline + 1
    window.close()
    qapp.processEvents()


def test_stale_state_exposes_recovery_and_ready_empty_is_truthful(
    qapp, tmp_path
):
    """Unavailable indexes offer recovery while a ready empty index does not."""
    controller = FakeController([])
    controller.is_query_ready = True
    controller.state_value = "stale"
    window = DatasetLabelThumbnailWindow(controller, "project", str(tmp_path))

    assert "stale" in window.summary_label.text()
    assert not window.scan_button.isHidden()
    window.scan_button.click()
    assert controller.refresh_calls == 1
    assert controller.rebuild_calls == 0

    controller.is_query_ready = True
    controller.state_value = "ready"
    window._on_controller_state_changed("stale", "ready")
    assert "No labeled objects" in window.summary_label.text()
    assert not window.scan_button.isHidden()
    window.close()
    qapp.processEvents()


def test_open_does_not_scan_and_manual_scan_shows_progress(qapp, tmp_path):
    """Opening is passive; explicit scanning gates relabel and shows progress."""
    ref = _ref(tmp_path)
    controller = FakeController([ref])
    window = DatasetLabelThumbnailWindow(controller, "project", str(tmp_path))

    assert controller.refresh_calls == 0
    assert controller.rebuild_calls == 0
    window.view.selectionModel().select(
        window._model.index(0, 0),
        QtCore.QItemSelectionModel.SelectionFlag.Select,
    )
    assert window.relabel_button.isEnabled()

    window.scan_button.click()
    assert controller.refresh_calls == 1

    controller.is_busy = True
    controller.busy_changed.emit(True)
    controller.progress_changed.emit(2, 5, str(tmp_path / "image-2.png"))

    assert not window.scan_button.isEnabled()
    assert not window.relabel_button.isEnabled()
    assert not window.scan_progress_bar.isHidden()
    assert window.scan_progress_bar.maximum() == 5
    assert window.scan_progress_bar.value() == 2
    assert "image-2.png" in window.scan_progress_label.text()

    controller.is_busy = False
    controller.busy_changed.emit(False)
    assert window.scan_progress_bar.isHidden()
    assert window._model.rowCount() == 1
    window.close()
    qapp.processEvents()


def test_delegate_distinguishes_selection_and_navigation_focus(qapp, tmp_path):
    """Selected blue and reverse-focus white borders remain simultaneously."""
    refs = [_ref(tmp_path, index) for index in range(2)]
    window = DatasetLabelThumbnailWindow(
        FakeController(refs), "project", str(tmp_path)
    )
    selection = window.view.selectionModel()
    for row in range(2):
        selection.select(
            window._model.index(row, 0),
            QtCore.QItemSelectionModel.SelectionFlag.Select,
        )
    window._model.set_focus_identity((refs[0].image_path, refs[0].shape_id))

    canvas = QtGui.QImage(230, 200, QtGui.QImage.Format.Format_RGB32)
    canvas.fill(QtGui.QColor("#000000"))
    painter = QtGui.QPainter(canvas)
    option = QtWidgets.QStyleOptionViewItem()
    option.rect = QtCore.QRect(0, 0, 230, 200)
    option.state = (
        QtWidgets.QStyle.StateFlag.State_Enabled
        | QtWidgets.QStyle.StateFlag.State_Selected
    )
    window.view.itemDelegate().paint(
        painter, option, window._model.index(0, 0)
    )
    painter.end()

    assert canvas.pixelColor(4, 100).name() == "#35a2ff"
    assert canvas.pixelColor(10, 100).name() == "#ffffff"
    assert len(selection.selectedIndexes()) == 2
    window.close()
    qapp.processEvents()


def test_manual_scan_rebuilds_when_no_readable_cache(qapp, tmp_path):
    """The single scan action rebuilds only when no index can be queried."""
    controller = FakeController([])
    controller.is_query_ready = False
    controller.state_value = "missing"
    window = DatasetLabelThumbnailWindow(controller, "project", str(tmp_path))

    window.scan_button.click()

    assert controller.refresh_calls == 0
    assert controller.rebuild_calls == 1
    window.close()
    qapp.processEvents()


def test_explicit_activation_requests_navigation_but_selection_does_not(
    qapp, tmp_path
):
    """Selection remains local until a card is double-clicked or activated."""
    ref = _ref(tmp_path)
    window = DatasetLabelThumbnailWindow(
        FakeController([ref]), "project", str(tmp_path)
    )
    requested = []
    window.navigate_requested.connect(requested.append)
    index = window._model.index(0, 0)

    window.view.selectionModel().select(
        index,
        QtCore.QItemSelectionModel.SelectionFlag.Select,
    )
    assert requested == []

    window.view.setCurrentIndex(index)
    QtTest.QTest.keyClick(window.view, QtCore.Qt.Key.Key_Return)
    assert requested == [ref]

    requested.clear()
    window._activate_index(index)
    assert requested == [ref]
    window.close()
    qapp.processEvents()


def test_focus_object_switches_to_owning_page_and_selects_card(qapp, tmp_path):
    """Main-canvas selection reveals the matching thumbnail across pages."""
    refs = [_ref(tmp_path, index) for index in range(150)]
    controller = FakeController(refs)
    window = DatasetLabelThumbnailWindow(controller, "project", str(tmp_path))

    assert window.focus_object(refs[123].image_path, refs[123].shape_id)
    assert window._page == 1
    assert window._selected_refs() == (refs[123],)
    focused = window._model.index(23, 0)
    assert focused.data(window._model.FocusRole) is True

    controller.is_busy = True
    controller.state_value = "syncing"
    controller.busy_changed.emit(True)
    controller.is_busy = False
    controller.state_value = "ready"
    controller.busy_changed.emit(False)
    focused = window._model.index(23, 0)
    assert focused.data(window._model.FocusRole) is True

    assert not window.focus_object(refs[0].image_path, "missing")
    assert focused.data(window._model.FocusRole) is False

    assert window.focus_object(refs[123].image_path, refs[123].shape_id)
    window.view.selectionModel().select(
        window._model.index(24, 0),
        QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect,
    )
    assert focused.data(window._model.FocusRole) is False
    window.close()
    qapp.processEvents()


def test_digit_shortcut_uses_existing_mapping_and_ignores_text_focus(
    qapp, tmp_path
):
    """Window-local digits invoke relabel only outside text-entry controls."""
    ref = _ref(tmp_path)
    window = DatasetLabelThumbnailWindow(
        FakeController([ref]),
        "project",
        str(tmp_path),
        digit_label_resolver=lambda digit: "vehicle" if digit == 3 else None,
    )
    requested = []
    window.relabel_requested.connect(
        lambda refs, target: requested.append((refs, target))
    )
    window.show()
    window.view.setFocus()
    qapp.processEvents()
    window.view.selectionModel().select(
        window._model.index(0, 0),
        QtCore.QItemSelectionModel.SelectionFlag.Select,
    )

    QtTest.QTest.keyClick(window.view, QtCore.Qt.Key.Key_3)
    qapp.processEvents()
    assert requested == [((ref,), "vehicle")]
    assert not window._apply_digit_shortcut(4)

    window.label_combo.setFocus()
    qapp.processEvents()
    QtTest.QTest.keyClick(window.label_combo, QtCore.Qt.Key.Key_3)
    qapp.processEvents()
    assert len(requested) == 1
    window.close()
    qapp.processEvents()


def test_reopened_dataset_uses_an_isolated_cache_root(qapp, tmp_path):
    """A new dataset window never reuses the previous dataset cache root."""
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first = DatasetLabelThumbnailWindow(
        FakeController([]), "first", str(first_root)
    )
    first_cache = first._renderer.disk.root
    first.close()
    qapp.processEvents()

    second = DatasetLabelThumbnailWindow(
        FakeController([]), "second", str(second_root)
    )
    second_cache = second._renderer.disk.root

    assert first_cache != second_cache
    second.close()
    qapp.processEvents()


@pytest.mark.parametrize(
    ("statuses", "cancelled", "stage", "heading", "color"),
    [
        (("succeeded",), False, "", "Completed", "#dff2e4"),
        (("unchanged", "deleted"), False, "", "No write needed", "#e8edf3"),
        (("succeeded", "failed"), False, "", "Partially completed", "#fff2cc"),
        (("conflict", "failed"), False, "", "Not completed", "#f9dddd"),
        ((), False, "", "Not run", "#e8edf3"),
        (("cancelled",), True, "preflight", "Preflight stopped", "#e8edf3"),
        (
            ("cancelled",),
            True,
            "confirmation",
            "Commit was not confirmed",
            "#e8edf3",
        ),
        (("cancelled",), True, "staging", "Staging stopped", "#e8edf3"),
    ],
)
def test_result_bar_matrix_and_severity(
    qapp, tmp_path, statuses, cancelled, stage, heading, color
):
    """Every specified terminal class has deterministic text and severity."""
    ref = _ref(tmp_path)
    window = DatasetLabelThumbnailWindow(
        FakeController([ref]), "project", str(tmp_path)
    )
    objects = tuple(
        ObjectMutationResult(
            ("project", ref.image_path, f"shape-{index}"), status
        )
        for index, status in enumerate(statuses)
    )
    result = ObjectRelabelResult(
        transaction_id="tx",
        phase="cancelled" if cancelled else "committed",
        cancelled=cancelled,
        objects=objects,
        target_label="vehicle",
        cancellation_stage=stage,
    )

    window.apply_relabel_result(result)

    assert heading in window.result_summary_label.text()
    assert color in window.result_frame.styleSheet()
    assert not window.result_frame.isHidden()
    window._load_page()
    assert not window.result_frame.isHidden()
    assert heading in window.result_summary_label.text()
    window.close()
    qapp.processEvents()


def test_result_bar_exposes_exact_manifest_only_for_committed_files(
    qapp, tmp_path
):
    """Recovery is offered only when this result committed a real file."""
    ref = _ref(tmp_path)
    window = DatasetLabelThumbnailWindow(
        FakeController([ref]), "project", str(tmp_path)
    )
    manifest = str(tmp_path / "transactions" / "tx" / "manifest.json")
    (tmp_path / "transactions" / "tx").mkdir(parents=True)
    (tmp_path / "transactions" / "tx" / "manifest.json").write_text(
        "{}", encoding="utf-8"
    )
    result = ObjectRelabelResult(
        transaction_id="tx",
        phase="committed",
        cancelled=False,
        manifest_path=manifest,
        objects=(
            ObjectMutationResult(
                ("project", ref.image_path, ref.shape_id), "succeeded"
            ),
        ),
        files=(FileOperationResult(ref.json_path, "succeeded"),),
        target_label="vehicle",
    )
    requested = []
    window.restore_requested.connect(requested.append)

    window.apply_relabel_result(result)
    window.result_restore_button.click()

    assert not window.result_restore_button.isHidden()
    assert requested == [manifest]
    window.apply_relabel_result(
        ObjectRelabelResult("noop", "committed", False, manifest_path=manifest)
    )
    assert window.result_restore_button.isHidden()
    window.close()
    qapp.processEvents()


def test_refresh_barrier_blocks_button_and_digit_until_model_replaced(
    qapp, tmp_path
):
    """Neither mutation entry can reuse the pre-refresh thumbnail model."""
    ref = _ref(tmp_path)
    controller = FakeController([ref])
    window = DatasetLabelThumbnailWindow(
        controller,
        "project",
        str(tmp_path),
        digit_label_resolver=lambda digit: "vehicle" if digit == 3 else None,
    )
    requested = []
    window.relabel_requested.connect(
        lambda refs, target: requested.append((refs, target))
    )
    window.view.selectionModel().select(
        window._model.index(0, 0),
        QtCore.QItemSelectionModel.SelectionFlag.Select,
    )
    result = ObjectRelabelResult(
        "tx",
        "committed",
        False,
        manifest_path=str(tmp_path / "manifest.json"),
        objects=(
            ObjectMutationResult(
                ("project", ref.image_path, ref.shape_id), "failed"
            ),
        ),
        files=(FileOperationResult(ref.json_path, "succeeded"),),
    )

    window.apply_relabel_result(result)
    window._reload_timer.stop()

    assert window._relabel_refresh_pending
    assert not window.relabel_button.isEnabled()
    assert not window._apply_digit_shortcut(3)
    assert requested == []
    window._load_page()
    assert not window._relabel_refresh_pending
    assert window.relabel_button.isEnabled()
    assert window._apply_digit_shortcut(3)
    assert requested == [((ref,), "vehicle")]
    assert window.result_frame.isHidden()
    window.close()
    qapp.processEvents()


def test_result_summary_lists_every_nonzero_object_count(qapp, tmp_path):
    """Mixed informational counts are preserved without zero-count noise."""
    ref = _ref(tmp_path)
    window = DatasetLabelThumbnailWindow(
        FakeController([ref]), "project", str(tmp_path)
    )
    result = ObjectRelabelResult(
        "tx",
        "committed",
        False,
        objects=(
            ObjectMutationResult(
                ("project", ref.image_path, "a"), "succeeded"
            ),
            ObjectMutationResult(
                ("project", ref.image_path, "b"), "unchanged"
            ),
            ObjectMutationResult(("project", ref.image_path, "c"), "deleted"),
        ),
        target_label="vehicle",
    )

    window.apply_relabel_result(result)

    summary = window.result_summary_label.text()
    assert '1 changed to "vehicle"' in summary
    assert "1 unchanged" in summary
    assert "1 deleted" in summary
    assert "conflict" not in summary
    assert "failed" not in summary
    window.close()
    qapp.processEvents()


def test_failed_index_refresh_keeps_mutation_barrier(qapp, tmp_path):
    """A stale index never clears pending merely because a timer fired."""
    ref = _ref(tmp_path)
    controller = FakeController([ref])
    window = DatasetLabelThumbnailWindow(controller, "project", str(tmp_path))
    window._relabel_refresh_pending = True

    controller.state_value = "stale"
    window._on_file_refresh_finished(ref.image_path, False, "stale")

    assert window._relabel_refresh_pending
    assert not window.relabel_button.isEnabled()
    assert not window._apply_digit_shortcut(1)
    assert not window.scan_button.isHidden()
    window.close()
    qapp.processEvents()


def test_page_change_drops_ordinary_selection_but_restores_failed_item(
    qapp, tmp_path
):
    """Only retained failure identities survive a page round-trip."""
    refs = [_ref(tmp_path, index) for index in range(101)]
    window = DatasetLabelThumbnailWindow(
        FakeController(refs), "project", str(tmp_path)
    )
    window.view.selectionModel().select(
        window._model.index(0, 0),
        QtCore.QItemSelectionModel.SelectionFlag.Select,
    )
    window._next_page()
    assert window._selected_refs() == ()
    window._previous_page()
    assert window._selected_refs() == ()

    failed = ObjectRelabelResult(
        "tx",
        "committed",
        False,
        objects=(
            ObjectMutationResult(
                ("project", refs[0].image_path, refs[0].shape_id), "failed"
            ),
        ),
    )
    window.view.selectionModel().select(
        window._model.index(0, 0),
        QtCore.QItemSelectionModel.SelectionFlag.Select,
    )
    window.apply_relabel_result(failed)
    window._next_page()
    assert window._selected_refs() == ()
    window._previous_page()
    assert window._selected_refs() == (refs[0],)
    window.close()
    qapp.processEvents()
