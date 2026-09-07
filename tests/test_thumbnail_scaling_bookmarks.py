"""Real Qt edge gestures and independent persisted review positions."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

from anylabeling.views.labeling.dataset_index import DatasetFilterIndex
from anylabeling.views.labeling.widgets.dataset_thumbnail import (
    DatasetLabelThumbnailWindow,
)
from anylabeling.views.labeling.widgets.dataset_thumbnail.review_state import (
    ReviewPosition,
    ThumbnailReviewState,
)


class Controller(QtCore.QObject):
    """Keep real index queries in the UI thread and count page reloads."""

    is_query_ready = True
    state_value = "ready"
    is_busy = False

    def __init__(self, index: DatasetFilterIndex) -> None:
        """Adapt the shared read-only index interface."""
        super().__init__()
        self.index = index
        self.queries = 0

    def __getattr__(self, name: str) -> Any:
        """Forward index queries not instrumented by this test."""
        return getattr(self.index, name)

    def query_thumbnail_objects(self, *args: Any) -> Any:
        """Count queries so resizing cannot silently reload a page."""
        self.queries += 1
        return self.index.query_thumbnail_objects(*args)


@pytest.fixture
def browser(tmp_path: Path, qapp: QtWidgets.QApplication) -> Any:
    """Create three real pages with different source images and stable IDs."""
    paths = []
    for file_index in range(12):
        path = tmp_path / f"s{file_index:04}.png"
        image = QtGui.QImage(800, 700, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("#759ab3"))
        assert image.save(str(path))
        shapes = [
            dict(
                label="person",
                shape_type="rectangle",
                points=[[50, 20], [750, 670]],
                xanylabeling_shape_id=f"{file_index * 20 + i + 1:032x}",
            )
            for i in range(20)
        ]
        path.with_suffix(".json").write_text(
            json.dumps(dict(shapes=shapes)), encoding="utf-8"
        )
        paths.append(str(path))
    index = DatasetFilterIndex(str(tmp_path / "index.sqlite"))
    index.rebuild(paths, dataset_root=str(tmp_path))
    settings = QtCore.QSettings(
        str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat
    )
    window = DatasetLabelThumbnailWindow(
        Controller(index),
        "p",
        str(tmp_path),
        settings=settings,
    )
    window._renderer.disk.root = str(tmp_path / "cache")
    window.show()
    QtTest.QTest.qWait(120)
    yield window
    if not window._closed:
        window.close()
    qapp.processEvents()
    index.close()


def click_card(
    window: Any,
    row: int,
    modifiers: Any = QtCore.Qt.KeyboardModifier.NoModifier,
) -> None:
    """Click a card interior, keeping resize hit targets out of the test."""
    index = window._model.index(row, 0)
    window.view.scrollTo(index)
    window.view.doItemsLayout()
    QtTest.QTest.mouseClick(
        window.view.viewport(),
        QtCore.Qt.MouseButton.LeftButton,
        modifiers,
        window.view.visualRect(index).center(),
    )


def drag_edge(window: Any, dx: int, dy: int = 0, edge: str = "right") -> None:
    """Send a real press/move/release gesture into the view's viewport."""
    index = window._model.index(0, 0)
    window.view.scrollTo(index)
    rect = window.view.visualRect(index).adjusted(4, 4, -4, -4)
    if edge == "bottom":
        start = QtCore.QPoint(rect.center().x(), rect.bottom())
    elif edge == "corner":
        start = rect.bottomRight()
    else:
        start = QtCore.QPoint(rect.right(), rect.center().y())
    viewport = window.view.viewport()
    QtTest.QTest.mousePress(
        viewport, QtCore.Qt.MouseButton.LeftButton, pos=start
    )
    assert window.view.is_resizing
    QtTest.QTest.mouseMove(viewport, start + QtCore.QPoint(dx, dy))
    QtTest.QTest.qWait(30)
    QtTest.QTest.mouseRelease(
        viewport,
        QtCore.Qt.MouseButton.LeftButton,
        pos=start + QtCore.QPoint(dx, dy),
    )


@pytest.mark.parametrize("edge", ["right", "bottom", "corner"])
def test_edge_resize_keeps_page_selection_and_click(
    browser: Any, edge: str
) -> None:
    """All sizes change together, without extra navigation or page queries."""
    window = browser
    click_card(window, 1)
    click_card(window, 2, QtCore.Qt.KeyboardModifier.ControlModifier)
    selected = window._selected_refs()
    bookmark = window._review_state.last_click
    queries = window._controller.queries
    navigation = []
    window.navigate_requested.connect(navigation.append)
    drag_edge(window, 100, 86, edge)
    assert window.view.card_width > 300
    assert window._model.rowCount() == 100 and window._page == 0
    assert window._selected_refs() == selected
    assert window._review_state.last_click == bookmark
    assert window._controller.queries == queries and not navigation
    assert not window.view.is_resizing
    sizes = [
        window.view.sizeHintForIndex(window._model.index(i, 0))
        for i in range(100)
    ]
    assert all(size == window.view.card_size() for size in sizes)
    assert window.view.visualRect(window._model.index(0, 0)).intersects(
        window.view.viewport().rect()
    )
    window._next_page()
    assert window._model.rowCount() == 100 and window._page == 1
    assert window.view.card_width > 300


def test_scaling_defers_rendering_and_replaces_resolution(
    browser: Any, monkeypatch: Any
) -> None:
    """Dragging uses previews; release requests the new bounded image size."""
    window = browser
    requested = []
    original_request = window._renderer.request

    def request(*args: Any, **kwargs: Any) -> Any:
        """Capture renderer inputs while retaining real background work."""
        requested.append(kwargs)
        return original_request(*args, **kwargs)

    monkeypatch.setattr(window._renderer, "request", request)
    rect = window.view.visualRect(window._model.index(0, 0))
    start = QtCore.QPoint(rect.right() - 4, rect.center().y())
    QtTest.QTest.mousePress(
        window.view.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=start
    )
    QtTest.QTest.mouseMove(
        window.view.viewport(), start + QtCore.QPoint(180, 0)
    )
    QtTest.QTest.qWait(60)
    window._request_visible()
    assert not requested
    images_before = dict(window._model._images)
    old_generation = window._render_generation
    QtTest.QTest.mouseRelease(
        window.view.viewport(),
        QtCore.Qt.MouseButton.LeftButton,
        pos=start + QtCore.QPoint(180, 0),
    )
    assert window._model._images == images_before
    assert window._render_generation > old_generation
    QtTest.QTest.qWait(150)
    assert requested and requested[-1]["size"][0] > 350
    for _ in range(100):
        if any(
            image.width() > 300 for image in window._model._images.values()
        ):
            break
        QtTest.QTest.qWait(10)
    assert any(image.width() > 300 for image in window._model._images.values())


def test_no_movement_edge_click_resumes_rendering(browser: Any) -> None:
    """Pressing a border without changing size cannot strand placeholders."""
    window = browser
    generation = window._render_generation
    drag_edge(window, 0)
    assert window._render_generation == generation
    assert window._visible_timer.isActive()


def test_two_bookmarks_survive_fresh_process_and_no_click_pages(
    browser: Any, tmp_path: Path
) -> None:
    """A closed page tail and an older click retain different image identities."""
    window = browser
    click_card(window, 1)
    clicked = window._review_state.last_click
    window._next_page()
    window._next_page()
    assert window._model.rowCount() == 40
    last_ref = window._model.ref_at(39)
    assert last_ref.image_path != clicked.image_path
    window.close()
    # New process and QSettings object prove this is not merely cached state.
    code = (
        "import json,sys; from dataclasses import asdict; from PyQt6 import QtCore; "
        "from anylabeling.views.labeling.widgets.dataset_thumbnail.review_state import ThumbnailReviewState; "
        "s=ThumbnailReviewState(sys.argv[1],QtCore.QSettings(sys.argv[2],QtCore.QSettings.Format.IniFormat)); "
        "print(json.dumps({'page':asdict(s.page_end),'click':asdict(s.last_click)}))"
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(tmp_path),
            str(tmp_path / "settings.ini"),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    saved = json.loads(completed.stdout)
    assert saved["page"]["image_path"] == last_ref.image_path
    assert saved["page"]["label"] == "person"
    assert saved["click"]["shape_id"] == clicked.shape_id
    assert saved["click"]["image_path"] == clicked.image_path
    reopened = DatasetLabelThumbnailWindow(
        window._controller,
        "p",
        str(tmp_path),
        settings=window._review_state.settings,
    )
    assert (
        Path(last_ref.image_path).name in reopened.page_bookmark_label.text()
    )
    assert clicked.shape_id in reopened.click_bookmark_label.text()
    assert not reopened._selected_refs()
    reopened.close()


def test_only_single_selected_mouse_click_updates_record(browser: Any) -> None:
    """Keyboard, programmatic focus and deselection do not invent clicks."""
    window = browser
    click_card(window, 0)
    expected = window._review_state.last_click
    click_card(window, 0, QtCore.Qt.KeyboardModifier.ControlModifier)
    assert window._review_state.last_click == expected
    ref = window._model.ref_at(3)
    window.focus_object(ref.image_path, ref.shape_id)
    QtTest.QTest.keyClick(window.view, QtCore.Qt.Key.Key_Right)
    assert window._review_state.last_click == expected
    click_card(window, 4)
    assert (
        window._review_state.last_click.shape_id
        == window._model.ref_at(4).shape_id
    )


def test_state_isolation_empty_page_and_corrupt_settings(
    browser: Any, tmp_path: Path
) -> None:
    """Dataset identity and malformed records cannot leak a saved target."""
    window = browser
    state = window._review_state
    state.page_end = ReviewPosition.from_ref(window._model.ref_at(99))
    expected = state.page_end
    window._model.set_items(())
    window.close()
    loaded = ThumbnailReviewState(str(tmp_path), state.settings)
    assert loaded.page_end == expected
    other = ThumbnailReviewState(str(tmp_path / "other"), state.settings)
    assert other.page_end is None and other.last_click is None
    state.settings.setValue(
        state.key, '{"version": 1, "card_width": 100000, "page_end": []}'
    )
    loaded = ThumbnailReviewState(str(tmp_path), state.settings)
    assert loaded.card_width == 520 and loaded.page_end is None
    state.settings.setValue(state.key, "broken json")
    loaded = ThumbnailReviewState(str(tmp_path), state.settings)
    assert loaded.card_width == 220 and loaded.last_click is None


def test_size_clamps_and_persists_without_annotation_changes(
    browser: Any, tmp_path: Path
) -> None:
    """Scale limits and restart preferences only write application settings."""
    before = {path: path.read_bytes() for path in tmp_path.glob("s*.json")}
    window = browser
    window.view.set_card_width(10000)
    assert window.view.card_width == 520
    window.view.set_card_width(-10)
    assert window.view.card_width == 160
    window.view.set_card_width(340)
    settings = window._review_state.settings
    window.close()
    assert ThumbnailReviewState(str(tmp_path), settings).card_width == 340
    assert {path: path.read_bytes() for path in before} == before


def test_focus_loss_and_border_double_click_do_not_navigate(
    browser: Any,
) -> None:
    """A gesture ends safely if focus changes, and grips never navigate."""
    window = browser
    navigation = []
    window.navigate_requested.connect(navigation.append)
    rect = window.view.visualRect(window._model.index(0, 0))
    point = QtCore.QPoint(rect.right() - 4, rect.center().y())
    viewport = window.view.viewport()
    QtTest.QTest.mousePress(
        viewport, QtCore.Qt.MouseButton.LeftButton, pos=point
    )
    QtTest.QTest.mouseMove(viewport, point + QtCore.QPoint(30, 0))
    QtWidgets.QApplication.sendEvent(
        window.view, QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut)
    )
    assert not window.view.is_resizing
    rect = window.view.visualRect(window._model.index(0, 0))
    point = QtCore.QPoint(rect.right() - 4, rect.center().y())
    QtTest.QTest.mouseDClick(
        viewport, QtCore.Qt.MouseButton.LeftButton, pos=point
    )
    assert not navigation and window._review_state.last_click is None


def test_settings_failure_is_reported(browser: Any, monkeypatch: Any) -> None:
    """An unsuccessful write must not be silently reported as persisted."""
    messages = []
    browser.state_save_failed.connect(messages.append)
    monkeypatch.setattr(browser._review_state, "save", lambda: False)
    browser.close()
    assert messages == [
        browser.tr("Could not save thumbnail review positions.")
    ]


def test_chinese_bookmarks_and_scaling_preview(
    browser: Any, qapp: Any
) -> None:
    """Render readable Chinese positions and both grid densities for review."""
    window = browser
    translator = QtCore.QTranslator()
    assert translator.load(
        str(Path("anylabeling/resources/translations/zh_CN.qm").resolve())
    )
    old_font = qapp.font()
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    if font_path.exists():
        font_id = QtGui.QFontDatabase.addApplicationFont(str(font_path))
        families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
        if families:
            qapp.setFont(QtGui.QFont(families[0], 9))
    qapp.installTranslator(translator)
    preview_window = None
    try:
        window._review_state.page_end = ReviewPosition.from_ref(
            window._model.ref_at(99)
        )
        click_card(window, 1)
        assert window._review_state.save()
        preview_window = DatasetLabelThumbnailWindow(
            window._controller,
            "p",
            window._dataset_root,
            settings=window._review_state.settings,
        )
        preview_window._renderer.disk.root = window._renderer.disk.root
        preview_window.show()
        window = preview_window
        assert "上次关闭时页面末项" in window.page_bookmark_label.text()
        assert "最后单击选中的对象" in window.click_bookmark_label.text()
        for width in (220, 340):
            window.view.set_card_width(width)
            window._on_card_resize_finished()
            window.view.scrollToTop()
            QtTest.QTest.qWait(200)
            preview = Path(
                f"openspec/changes/add-thumbnail-scaling-and-review-bookmarks/preview-{width}.png"
            )
            assert window.grab().save(str(preview))
    finally:
        if preview_window is not None:
            preview_window.close()
        qapp.removeTranslator(translator)
        qapp.setFont(old_font)


def test_deep_page_resize_keeps_dragged_object_visible(browser: Any) -> None:
    """Changing column counts near the page end cannot jump to the top."""
    window = browser
    click_card(window, 80)
    index = window._model.index(80, 0)
    before = window._selected_refs()
    rect = window.view.visualRect(index)
    start = QtCore.QPoint(rect.right() - 4, rect.center().y())
    viewport = window.view.viewport()
    QtTest.QTest.mousePress(
        viewport, QtCore.Qt.MouseButton.LeftButton, pos=start
    )
    QtTest.QTest.mouseMove(viewport, start + QtCore.QPoint(70, 0))
    QtTest.QTest.qWait(30)
    QtTest.QTest.mouseRelease(
        viewport,
        QtCore.Qt.MouseButton.LeftButton,
        pos=start + QtCore.QPoint(70, 0),
    )
    assert window.view.card_width == 290
    assert window.view.visualRect(index).intersects(viewport.rect())
    assert window._selected_refs() == before
    assert window.view.verticalScrollBar().value() > 0
