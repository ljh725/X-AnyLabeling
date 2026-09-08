"""Exercise advanced review through real Qt controls and image workers."""

from pathlib import Path
from typing import Any, Callable

import pytest
from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

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


def test_chinese_advanced_layout(browser: Any, qapp: Any) -> None:
    """Render translated controls and preview for visual inspection."""
    translator = QtCore.QTranslator()
    assert translator.load(
        str(Path("anylabeling/resources/translations/zh_CN.qm").resolve())
    )
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
        window.resize(1180, 850)
        window.show()
        window.advanced.box.setChecked(True)
        click_card(window, 0)
        window.advanced.mark_button.click()
        QtTest.QTest.qWait(250)
        output = Path("openspec/changes/add-advanced-thumbnail-review")
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
