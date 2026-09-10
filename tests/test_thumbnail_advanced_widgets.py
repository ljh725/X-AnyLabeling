"""Exercise advanced review through real Qt controls and image workers."""

from pathlib import Path
from typing import Any, Callable

import pytest
from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

import anylabeling.resources.resources  # noqa: F401
from tests import test_thumbnail_scaling_bookmarks as fixture_tools
from tests.test_thumbnail_scaling_bookmarks import click_card
from anylabeling.views.labeling.dataset_index.thumbnail_query import (
    ThumbnailQuery,
)
from anylabeling.views.labeling.widgets.dataset_thumbnail import (
    DatasetLabelThumbnailWindow,
)
from anylabeling.views.labeling.widgets.dataset_thumbnail.advanced_controls import (
    ThumbnailFiltersDialog,
)
from anylabeling.views.labeling.widgets.dataset_thumbnail.pipeline import (
    ThumbnailRenderer,
    thumbnail_crop_rect,
)
from anylabeling.views.labeling.widgets.dataset_thumbnail.render_options import (
    RenderOptions,
)


@pytest.fixture
def browser(tmp_path: Path, qapp: QtWidgets.QApplication) -> Any:
    """Reuse the real multi-page fixture with its cleanup guarantees."""
    yield from fixture_tools.browser.__wrapped__(tmp_path, qapp)


def wait_until(predicate: Callable[[], bool]) -> None:
    """Pump Qt events until an asynchronous result arrives or time expires."""
    for _ in range(300):
        if predicate():
            return
        QtTest.QTest.qWait(10)
    assert predicate(), "Qt result did not arrive within three seconds"


def test_manual_review_and_unreviewed_filter(browser: Any) -> None:
    """Only explicit marking removes objects from the unreviewed results."""
    window = browser
    controls = window.advanced
    controls.review_filter.setCurrentIndex(1)
    click_card(window, 0)
    click_card(window, 1, QtCore.Qt.KeyboardModifier.ControlModifier)
    assert window._current_total == 240
    assert controls.mark_button.isEnabled()
    refs = window._selected_refs()
    documents = {r.json_path: Path(r.json_path).read_bytes() for r in refs}
    controls.mark_button.click()
    assert window._current_total == 238
    assert not window._selected_refs()
    controls.review_filter.setCurrentIndex(2)
    assert window._current_total == 2
    assert all(
        window._model.ref_at(i).review_status == "confirmed" for i in range(2)
    )
    assert all(Path(p).read_bytes() == data for p, data in documents.items())
    controls.clear_query()
    assert (
        window._current_total == 240
        and controls.sort.currentData() == "original"
    )


def test_reopen_restores_filters_page_without_selection(browser: Any) -> None:
    """Restoring a thumbnail anchor neither selects it nor emits navigation."""
    window = browser
    window.advanced.sort.setCurrentIndex(1)
    window._next_page()
    click_card(window, 45)
    old_click = window._review_state.last_click
    window.close()
    saved = window._review_state.view_state
    assert saved["page"] == 1 and saved["anchor"]
    reopened = DatasetLabelThumbnailWindow(
        window._controller,
        "p",
        window._dataset_root,
        settings=window._review_state.settings,
    )
    navigation = []
    reopened.navigate_requested.connect(navigation.append)
    try:
        reopened.show()
        QtTest.QTest.qWait(100)
        assert reopened._page == 1
        assert reopened._query_options.sort == "small_pixels"
        assert not reopened._selected_refs() and not navigation
        assert reopened._review_state.last_click == old_click
        visible = [
            reopened._model.ref_at(i)
            for i in range(reopened._model.rowCount())
            if reopened.view.visualRect(
                reopened._model.index(i, 0)
            ).intersects(reopened.view.viewport().rect())
        ]
        assert saved["anchor"] in [
            list(reopened._model.identity_key(r)) for r in visible
        ]
    finally:
        reopened.close()


def test_slider_and_context_keep_page_selection(browser: Any) -> None:
    """Display changes preserve all 100 cards and their current selection."""
    window = browser
    click_card(window, 4)
    selected = window._selected_refs()
    window.advanced.size_slider.setValue(340)
    window.advanced.padding.setValue(50)
    window.advanced.box.setChecked(True)
    assert window.view.card_width == 340
    assert window._model.rowCount() == 100
    assert window._selected_refs() == selected
    assert window.advanced.render_options() == RenderOptions(0.5, True)
    window.advanced.context_mode.setCurrentIndex(1)
    assert window.advanced.render_options().padding == 0
    assert not window.advanced.padding.isEnabled()


def test_space_preview_modes_and_escape(browser: Any) -> None:
    """Space opens from the card view; original mode shows the complete image."""
    window = browser
    window.advanced.filename.setFocus()
    QtTest.QTest.keyClick(window.advanced.filename, QtCore.Qt.Key.Key_Space)
    assert window._preview is None
    window.advanced.filename.clear()
    window.advanced.apply_query()
    click_card(window, 0)
    QtTest.QTest.keyClick(window.view, QtCore.Qt.Key.Key_Space)
    preview = window._preview
    assert preview is not None
    wait_until(lambda: preview._image is not None)
    preview.mode.setCurrentIndex(1)
    wait_until(lambda: preview._image is not None)
    assert (
        abs(preview._image.width() / preview._image.height() - 800 / 700)
        < 0.01
    )
    QtTest.QTest.keyClick(preview, QtCore.Qt.Key.Key_Escape)
    assert window._preview is None
    assert window._selected_refs()


def test_range_dialog_rejects_invalid_input(browser: Any) -> None:
    """Invalid bounds stay in the dialog instead of querying partial input."""
    dialog = ThumbnailFiltersDialog(ThumbnailQuery(), browser)
    dialog.fields["ratio_min"].setText("2")
    dialog.fields["ratio_max"].setText("1")
    dialog.accept()
    assert dialog.result() != QtWidgets.QDialog.DialogCode.Accepted
    assert dialog.error.text()
    dialog.clear_fields()
    dialog.fields["score_min"].setText("0.5")
    dialog.accept()
    assert dialog.result() == QtWidgets.QDialog.DialogCode.Accepted
    assert dialog.query.ratio_min is None and dialog.query.score_min == 0.5


def test_render_policy_cache_and_boundary(
    browser: Any, tmp_path: Path
) -> None:
    """Different context policies cannot share cached pixels or hide outlines."""
    renderer = ThumbnailRenderer(str(tmp_path / "policy-cache"))
    results = []
    renderer.result_ready.connect(results.append)
    ref = browser._model.ref_at(0)
    try:
        for policy in (
            RenderOptions(0),
            RenderOptions(0.5),
            RenderOptions(0, True),
            RenderOptions(mode="full", show_box=True),
        ):
            count = len(results)
            renderer.request([ref], size=(400, 350), options=policy)
            wait_until(lambda: len(results) > count)
        assert all(not r.error for r in results)
        assert len({r.key.token for r in results}) == 4
        plain, _, outlined, full = [r.image for r in results]
        yellow = QtGui.QColor("#ffcb30")
        assert plain.pixelColor(1, 1) != yellow
        assert outlined.pixelColor(1, 1) == yellow
        assert (full.width(), full.height()) == (400, 350)
        assert thumbnail_crop_rect((2, 10, 42, 30), (100, 80), 1) == (
            0,
            0,
            82,
            50,
        )
    finally:
        renderer.close()


def test_chinese_advanced_layout(
    browser: Any, qapp: Any, tmp_path: Path
) -> None:
    """Render translated controls and preview for visual inspection."""
    translator = QtCore.QTranslator()
    assert translator.load(":/languages/translations/zh_CN.qm")
    old_font = qapp.font()
    font_id = QtGui.QFontDatabase.addApplicationFont(
        "C:/Windows/Fonts/msyh.ttc"
    )
    families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
    if families:
        qapp.setFont(QtGui.QFont(families[0], 9))
    qapp.installTranslator(translator)
    window = None
    try:
        window = DatasetLabelThumbnailWindow(
            browser._controller,
            "p",
            browser._dataset_root,
            settings=browser._review_state.settings,
        )
        window._renderer.disk.root = browser._renderer.disk.root
        window.resize(980, 760)
        window.show()
        qapp.processEvents()
        assert window.width() == 980
        assert window.view.y() < 130
        assert window.first_button.text() == "首页"
        assert window.last_button.text() == "末尾页"
        assert window.advanced.locate_button.text() == "定位所选卡片"
        window.advanced.box.setChecked(True)
        click_card(window, 0)
        window.advanced.mark_button.click()
        wait_until(lambda: bool(window._model._images))
        output = tmp_path
        assert window.grab().save(str(output / "preview-browser.png"))
        dialog = ThumbnailFiltersDialog(ThumbnailQuery(), window)
        dialog.show()
        qapp.processEvents()
        assert dialog.grab().save(str(output / "preview-filters.png"))
        dialog.close()
        click_card(window, 1)
        window._open_preview()
        preview = window._preview
        preview.mode.setCurrentIndex(1)
        wait_until(lambda: preview._image is not None)
        assert preview.grab().save(str(output / "preview-full.png"))
    finally:
        if window is not None:
            window.close()
        qapp.removeTranslator(translator)
        qapp.setFont(old_font)


def test_page_jump_and_navigation_boundaries(browser: Any) -> None:
    """Explicit page input and endpoint buttons navigate bounded real pages."""
    window = browser
    assert window.page_input.maximum() == 3
    assert not window.first_button.isEnabled()
    click_card(window, 0)
    window.page_input.setFocus()
    window.page_input.lineEdit().selectAll()
    QtTest.QTest.keyClicks(window.page_input, "2")
    assert window._page == 0
    QtTest.QTest.keyClick(window.page_input, QtCore.Qt.Key.Key_Return)
    assert window._page == 1 and not window._selected_refs()
    window.last_button.click()
    assert window._page == 2 and window._model.rowCount() == 40
    assert not window.last_button.isEnabled()
    assert not window.next_button.isEnabled()
    window.first_button.click()
    assert window._page == 0 and window.page_input.value() == 1
    window.page_input.setValue(2)
    window.jump_button.click()
    assert window._page == 1
    window.page_input.setValue(999)
    window.jump_button.click()
    assert window._page == 2
    window.page_input.setValue(0)
    window.jump_button.click()
    assert window._page == 0


@pytest.mark.parametrize("sort_index", [0, 1, 3])
def test_search_locates_exact_card_in_unsearched_page(
    browser: Any, sort_index: int
) -> None:
    """Filename confirmation keeps sorting and review filters and the exact ID."""
    window = browser
    controls = window.advanced
    controls.sort.setCurrentIndex(sort_index)
    controls.review_filter.setCurrentIndex(1)
    controls.filename.setText("s0010")
    controls.apply_query()
    assert window._current_total == 20
    assert not controls.locate_button.isEnabled()
    click_card(window, 13)
    ref = window._selected_refs()[0]
    bookmark = window._review_state.last_click
    original = Path(ref.json_path).read_bytes()
    navigation = []
    window.navigate_requested.connect(navigation.append)
    controls.locate_button.click()
    assert window._page == 2 and window.page_input.value() == 3
    assert window._current_total == 240
    assert not controls.filename.text() and not window._query_options.filename
    assert window._query_options.sort == controls.sort.currentData()
    assert window._query_options.review == "unreviewed"
    assert window._selected_refs()[0].shape_id == ref.shape_id
    assert window.view.currentIndex().row() == 13
    assert window.view.visualRect(window.view.currentIndex()).intersects(
        window.view.viewport().rect()
    )
    assert window._review_state.last_click == bookmark
    assert not navigation and Path(ref.json_path).read_bytes() == original
    QtTest.QTest.qWait(300)
    assert (
        window._page == 2
        and window._selected_refs()[0].shape_id == ref.shape_id
    )


def test_search_location_requires_one_card_and_cancels_pending_typing(
    browser: Any,
) -> None:
    """Multiple cards cannot locate; pending search typing cannot undo a jump."""
    controls = browser.advanced
    controls.filename.setText("s0006")
    controls.apply_query()
    click_card(browser, 0)
    click_card(browser, 1, QtCore.Qt.KeyboardModifier.ControlModifier)
    assert not controls.locate_button.isEnabled()
    click_card(browser, 7)
    controls.filename.setText("s0007")
    controls.locate_button.click()
    QtTest.QTest.qWait(300)
    assert browser._page == 1
    assert browser._selected_refs()[0].shape_index == 7
    assert Path(browser._selected_refs()[0].image_path).stem == "s0006"


def test_empty_and_unavailable_results_disable_page_controls(
    browser: Any,
) -> None:
    """A stale or empty result cannot navigate using an old page range."""
    browser.last_button.click()
    browser.advanced.filename.setText("no-matching-file")
    browser.advanced.apply_query()
    assert browser._page == 0 and browser._current_total == 0
    controls = (
        browser.first_button,
        browser.previous_button,
        browser.next_button,
        browser.last_button,
        browser.page_input,
        browser.jump_button,
        browser.advanced.locate_button,
    )
    assert all(not control.isEnabled() for control in controls)
    browser.advanced.clear_query()
    browser.last_button.click()
    browser._controller.is_query_ready = False
    browser._set_unavailable_state()
    assert browser._page == 0
    assert all(not control.isEnabled() for control in controls)


def test_history_collapses_without_losing_records(browser: Any) -> None:
    """Long historical identities take no grid space until expanded."""
    browser.resize(980, 760)
    QtTest.QTest.qWait(20)
    top = browser.view.y()
    assert top < 130
    assert browser.width() == 980
    assert not browser.history_frame.isVisible()
    browser.history_button.click()
    QtTest.QTest.qWait(20)
    assert browser.history_frame.isVisible() and browser.view.y() > top
    browser.history_button.click()
    QtTest.QTest.qWait(20)
    assert browser.view.y() == top


def test_disappeared_search_result_keeps_search_and_selection(
    browser: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing identity reports the problem without clearing search context."""
    controls = browser.advanced
    controls.filename.setText("s0010")
    controls.apply_query()
    click_card(browser, 3)
    refs = browser._selected_refs()
    monkeypatch.setattr(
        browser._controller, "query_thumbnail_location", lambda *_args: None
    )
    controls.locate_button.click()
    assert browser._selected_refs() == refs
    assert controls.filename.text() == "s0010"
    assert controls.feedback.isVisible() and controls.feedback.text()
