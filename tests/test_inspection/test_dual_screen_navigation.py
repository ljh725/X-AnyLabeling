"""Independent-window navigation and explicit save/recheck regression tests."""
from dataclasses import replace
from unittest.mock import patch

import pytest
from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

from anylabeling.services.inspection.models import Decision, VerificationState
from anylabeling.views.labeling.inspector.dialog import InspectorDialog
from tests.test_inspection.test_inspector_dialog import (
    window, _prepare_image, _wait_until,
)


def prepare(window, tmp_path):
    host = window.labeling_widget.view
    assert host.load_file(_prepare_image(tmp_path))
    host.open_inspector()
    dialog = host.inspector_dialog
    dialog.profile_combo.setCurrentIndex(dialog.profile_combo.findData('generic'))
    dialog._start_run()
    assert _wait_until(QtWidgets.QApplication.instance(), lambda: dialog.report is not None)
    return host, dialog


def test_click_navigation_single_object_and_programmatic_refresh(window, tmp_path):
    host, dialog = prepare(window, tmp_path)
    with patch.object(host, 'inspection_navigate_to', wraps=host.inspection_navigate_to) as navigate:
        dialog._populate_table()
        assert not navigate.called
        item = dialog.issue_table.item(0, 0)
        pos = dialog.issue_table.visualItemRect(item).center()
        QtTest.QTest.mouseClick(dialog.issue_table.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=pos)
        assert navigate.call_count == 1
        dialog._locate_selected()
        assert navigate.call_count == 1
        assert len(host.canvas.selected_shapes) == 1
        dialog.object_combo.setCurrentIndex(1)
        dialog.object_combo.activated.emit(1)
        assert [s.xanylabeling_shape_id for s in host.canvas.selected_shapes] == ['id2']


def test_full_queue_cross_page_and_anchor(window, tmp_path):
    host, dialog = prepare(window, tmp_path)
    original = dialog.report.issues[0]
    issues = tuple(replace(original, family_key=f'key{i}', issue_id=f'issue{i}') for i in range(205))
    dialog.report = replace(dialog.report, issues=issues)
    dialog._populate_table()
    assert dialog._navigate_issue(issues[199])
    dialog._select_issue(1)
    assert dialog._active_issue_key == 'key200'
    assert dialog._issue_page == 1
    dialog.report = replace(dialog.report, issues=tuple(i for i in issues if i.family_key != 'key200'))
    dialog._populate_table()
    dialog._select_issue(1)
    assert dialog._active_issue_key == 'key201'
    dialog._navigate_issue(issues[-1])
    dialog._select_issue(1)
    assert dialog._active_issue_key == 'key204'
    dialog.report = replace(dialog.report, issues=())
    dialog._populate_table()
    assert not dialog.next_issue_button.isEnabled()


def test_failure_keeps_cursor_and_busy_guard(window, tmp_path):
    host, dialog = prepare(window, tmp_path)
    issue = dialog.report.issues[0]
    assert dialog._navigate_issue(issue)
    other = replace(issue, family_key='other', issue_id='other')
    dialog.report = replace(dialog.report, issues=(issue, other))
    with patch.object(host, 'inspection_navigate_to', return_value=False):
        assert not dialog._navigate_issue(other)
    assert dialog._active_issue_key == issue.family_key
    assert dialog._selected_issue().family_key == issue.family_key
    with patch.object(host.canvas, 'interaction_in_progress', return_value=True), patch.object(host, 'inspection_navigate_to') as navigate:
        dialog._select_issue(1)
        assert not navigate.called


@pytest.mark.parametrize('verification,decision,expected', [
    (VerificationState.CURRENT, Decision.CONFIRMED_ERROR, 'pending'),
    (VerificationState.CURRENT, Decision.ACCEPTABLE, 'ignored'),
    (VerificationState.CURRENT, Decision.FALSE_POSITIVE, 'ignored'),
    (VerificationState.NOT_DETECTED, Decision.CONFIRMED_ERROR, 'resolved'),
    (VerificationState.STALE, Decision.ACCEPTABLE, 'pending'),
    (VerificationState.PENDING_RECHECK, Decision.FALSE_POSITIVE, 'pending'),
    (VerificationState.UNVERIFIABLE, Decision.ACCEPTABLE, 'pending'),
])
def test_state_projection(window, tmp_path, verification, decision, expected):
    _, dialog = prepare(window, tmp_path)
    issue = replace(dialog.report.issues[0], verification=verification, decision=decision)
    assert dialog._review_state(issue) == expected


def test_save_failure_and_deleted_object_recheck(window, tmp_path):
    host, dialog = prepare(window, tmp_path)
    assert dialog._navigate_issue(dialog.report.issues[0])
    with patch.object(host, '_save_file', return_value=False), patch.object(dialog.controller, 'start') as start:
        dialog._save_and_recheck()
        assert not start.called
    # Deletion must not require locating the now missing object again.
    host.canvas.select_shapes([host.canvas.shapes[0]])
    host.delete_selected_shape()
    dialog.auto_advance.setChecked(False)
    dialog._save_and_recheck()
    assert _wait_until(QtWidgets.QApplication.instance(), lambda: dialog._recheck_issue is None)
    assert any(i.verification is VerificationState.NOT_DETECTED for i in dialog.report.issues), dialog.status_label.text()


def test_window_keys_runtime_update_close_and_reopen(window, tmp_path):
    host, dialog = prepare(window, tmp_path)
    app = QtWidgets.QApplication.instance()
    for owner in (dialog, window):
        owner.activateWindow()
        app.processEvents()
        dialog._active_issue_key = ''
        dialog._navigation_order = []
        with patch.object(dialog, '_select_issue') as navigate:
            QtTest.QTest.keyClick(owner, QtCore.Qt.Key.Key_F2)
            app.processEvents()
            assert navigate.call_count == 1
            assert app.activeWindow() is owner
    host._config['shortcuts']['inspector_next_issue'] = 'F8'
    dialog._refresh_shortcuts()
    assert 'F8' in dialog.next_issue_button.text()
    host._config['shortcuts']['open'] = 'F8'
    dialog._refresh_shortcuts()
    assert all(not shortcut.isEnabled() for key, _, shortcut, _ in dialog._issue_shortcuts if key == 'inspector_next_issue')
    host._config['shortcuts']['open'] = 'Ctrl+O'
    host._config['shortcuts']['inspector_next_issue'] = 'F2'
    dialog._refresh_shortcuts()
    dialog.showMinimized()
    window.activateWindow()
    app.processEvents()
    with patch.object(dialog, '_select_issue') as navigate:
        QtTest.QTest.keyClick(window, QtCore.Qt.Key.Key_F2)
        app.processEvents()
        assert navigate.call_count == 1
        assert dialog.isMinimized()
    host.open_inspector()
    tool = QtWidgets.QDialog(window)
    tool.show()
    tool.activateWindow()
    app.processEvents()
    with patch.object(dialog, '_select_issue') as navigate:
        QtTest.QTest.keyClick(tool, QtCore.Qt.Key.Key_F2)
        assert not navigate.called
    tool.close()
    modal = QtWidgets.QDialog(window)
    modal.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
    modal.show()
    app.processEvents()
    with patch.object(host, 'inspection_navigate_to') as navigate:
        dialog._select_issue(1)
        assert not navigate.called
    modal.close()
    host._config['shortcuts']['inspector_next_issue'] = ''
    dialog._refresh_shortcuts()
    assert all(not shortcut.isEnabled() for key, _, shortcut, _ in dialog._issue_shortcuts if key == 'inspector_next_issue')
    dialog.close()
    assert not dialog._session_open
    host.open_inspector()
    assert host.inspector_dialog is dialog
    assert dialog._session_open


def test_geometry_restores_disconnected_screen():
    available = QtCore.QRect(0, 0, 1280, 720)
    restored = InspectorDialog._visible_geometry(QtCore.QRect(2200, 50, 1600, 1000), [available])
    assert available.contains(restored)
    assert restored.width() == 1280
    assert restored.height() == 720


@pytest.mark.parametrize('advance,persist,late', [(True, True, False), (False, True, False), (True, False, False), (True, True, True)])
def test_saved_recheck_successor_and_manual_anchor(window, tmp_path, monkeypatch, advance, persist, late):
    import json
    from PIL import Image
    host, dialog = prepare(window, tmp_path)
    # A second actual file is the stable successor, not another copy of a row.
    Image.new('RGB', (64, 64)).save(tmp_path / 'second.png')
    payload = json.loads((tmp_path / 'image.json').read_text(encoding='utf-8'))
    payload['imagePath'] = 'second.png'
    (tmp_path / 'second.json').write_text(json.dumps(payload), encoding='utf-8')
    host._full_image_dir = str(tmp_path)
    dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData('dataset'))
    old_run = dialog.report.run_id
    dialog._start_run()
    app = QtWidgets.QApplication.instance()
    assert _wait_until(app, lambda: dialog.report.run_id != old_run)
    first, second = dialog.report.issues
    assert dialog._navigate_issue(first)
    dialog.auto_advance.setChecked(advance)
    host.delete_selected_shape()
    if not persist:
        monkeypatch.setattr(dialog, '_save_run', lambda *args: False)
    dialog._save_and_recheck()
    if late:
        dialog._edit_serial += 1
    assert _wait_until(app, lambda: dialog._recheck_issue is None)
    if not persist or late:
        assert dialog._active_issue_key == first.family_key
        assert host.inspection_current_relative_path() == first.location.relative_path
        return
    if not advance:
        assert dialog._active_issue_key == first.family_key
        assert host.inspection_current_relative_path() == first.location.relative_path
        dialog._select_issue(1)
    assert dialog._active_issue_key == second.family_key
    assert host.inspection_current_relative_path() == second.location.relative_path


def test_cross_image_cancel_missing_identity_and_load_failure(window, tmp_path):
    import json
    from PIL import Image
    host, dialog = prepare(window, tmp_path)
    first = dialog.report.issues[0]
    assert dialog._navigate_issue(first)
    Image.new('RGB', (64, 64)).save(tmp_path / 'second.png')
    payload = json.loads((tmp_path / 'image.json').read_text(encoding='utf-8'))
    payload['imagePath'] = 'second.png'
    (tmp_path / 'second.json').write_text(json.dumps(payload), encoding='utf-8')
    other = replace(first, family_key='second', issue_id='second', location=replace(first.location, relative_path='second.png', image_path=str(tmp_path / 'second.png')))
    dialog.report = replace(dialog.report, issues=(first, other))
    host.dirty = True
    with patch.object(host, 'may_continue', return_value=False) as prompt:
        assert not dialog._navigate_issue(other)
        assert prompt.call_count == 1
    assert host.filename.endswith('image.png')
    assert host.dirty
    with patch.object(host, 'may_continue', return_value=True), patch.object(host, 'load_file', return_value=False):
        assert not dialog._navigate_issue(other)
    invalid = replace(other, location=replace(other.location, object_ids=('missing',)))
    assert not dialog._navigate_issue(invalid)
    assert dialog._active_issue_key == first.family_key
    assert host.filename.endswith('image.png')
    host.dirty = False
    dialog.activateWindow()
    QtWidgets.QApplication.instance().processEvents()
    assert dialog._navigate_issue(other)
    QtWidgets.QApplication.instance().processEvents()
    assert QtWidgets.QApplication.activeWindow() is dialog


def test_compact_layout_evidence(window, tmp_path):
    from pathlib import Path
    import json
    host, dialog = prepare(window, tmp_path)
    QtGui.QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    dialog.setFont(QtGui.QFont('Microsoft YaHei', 9))
    dialog._navigate_issue(dialog.report.issues[0])
    dialog.resize(880, 700)
    QtWidgets.QApplication.instance().processEvents()
    for button in (dialog.save_recheck_button, dialog.next_issue_button, dialog.start_button):
        assert button.isVisible()
        point = button.mapTo(dialog, QtCore.QPoint(0, 0))
        assert dialog.rect().contains(QtCore.QRect(point, button.size()))
    output = Path('.tmp/inspector-dual-screen-evidence')
    output.mkdir(parents=True, exist_ok=True)
    dialog.grab().save(str(output / 'inspector.png'))
    (output / 'screens.json').write_text(json.dumps([
        {'name': screen.name(), 'width': screen.availableGeometry().width(),
         'height': screen.availableGeometry().height(), 'scale': screen.devicePixelRatio()}
        for screen in QtWidgets.QApplication.screens()
    ], indent=2), encoding='utf-8')
