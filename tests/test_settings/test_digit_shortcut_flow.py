"""Digit shortcut manager: confirm -> persist -> close, never the reverse.

Task 4.3 of ``fix-user-settings-persistence``: the dialog used to show "saved
successfully" before anything was written, so a failed or conflicting save
closed the window and threw the user's input away.  These tests pin the new
order and the explicit-baseline transaction.
"""

import copy
import os
import shutil
import uuid
from types import SimpleNamespace

import pytest
import yaml

from PyQt6 import QtWidgets

from anylabeling import user_config
from anylabeling.config import normalize_user_config
from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.labeling.widgets.label_dialog import DigitShortcutDialog

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

DIGIT_ONE = {"mode": "rectangle", "label": "car"}
DIGIT_TWO = {"mode": "polygon", "label": "road"}
DIGIT_THREE = {"mode": "circle", "label": "sun"}


def _workspace():
    path = os.path.join(
        REPO_ROOT, ".tmp", "digit-shortcut-flow", uuid.uuid4().hex
    )
    os.makedirs(path, exist_ok=True)
    return path


@pytest.fixture
def session():
    path = _workspace()
    config = copy.deepcopy(load_template_config())
    target = os.path.join(path, ".xanylabelingrc")
    user_config.begin_session(
        target_path=target,
        origin="file",
        template=copy.deepcopy(config),
        effective=config,
        disk_data=None,
        ensure_created=True,
        normalizer=normalize_user_config,
    )
    try:
        yield config, target, path
    finally:
        user_config.end_session()
        shutil.rmtree(path, ignore_errors=True)


class _StubParent(QtWidgets.QWidget):
    def __init__(self, mapping):
        super().__init__()
        self.drawing_digit_shortcuts = dict(mapping)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture
def suppress_warnings(monkeypatch):
    seen = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: seen.append(args),
    )
    return seen


def test_failed_commit_keeps_the_dialog_open_and_the_input(
    suppress_warnings,
):
    parent = _StubParent({1: DIGIT_ONE})
    dialog = DigitShortcutDialog(
        parent=parent,
        commit_handler=lambda _proposed, _baseline: (False, "disk is full"),
    )
    dialog._get_combo(2).setCurrentIndex(1)
    dialog._get_label_edit(2).setText("road")

    dialog.save_settings()

    assert dialog.result() != QtWidgets.QDialog.DialogCode.Accepted
    assert suppress_warnings, "the failure must be visible"
    assert parent.drawing_digit_shortcuts == {1: DIGIT_ONE}
    assert dialog._get_label_edit(2).text() == "road"


def test_successful_commit_closes_the_dialog_and_updates_the_parent():
    calls = []
    parent = _StubParent({1: DIGIT_ONE})
    dialog = DigitShortcutDialog(
        parent=parent,
        commit_handler=lambda proposed, baseline: calls.append(
            (proposed, baseline)
        )
        or True,
    )
    dialog._get_combo(2).setCurrentIndex(1)
    dialog._get_label_edit(2).setText("road")

    dialog.save_settings()

    assert dialog.result() == QtWidgets.QDialog.DialogCode.Accepted
    proposed, baseline = calls[0]
    assert proposed[2]["label"] == "road"
    # The baseline is the mapping captured when the dialog opened.
    assert baseline == {1: DIGIT_ONE}
    assert parent.drawing_digit_shortcuts == {1: DIGIT_ONE}


def test_commit_uses_the_dialog_baseline_not_the_live_mapping(session):
    config, _target, _path = session
    user_config.save_values({("digit_shortcuts", 1): DIGIT_ONE})
    parent = _StubParent({1: DIGIT_ONE})
    seen = []
    dialog = DigitShortcutDialog(
        parent=parent,
        commit_handler=lambda proposed, baseline: seen.append(baseline)
        or True,
    )
    # Another entry changes digit 1 while the dialog is open.
    user_config.save_values({("digit_shortcuts", 1): DIGIT_TWO})
    dialog._get_combo(3).setCurrentIndex(1)
    dialog._get_label_edit(3).setText("tree")

    dialog.save_settings()

    assert seen == [{1: DIGIT_ONE}]


def _commit_stub(config):
    stub = SimpleNamespace(
        _config=config,
        drawing_digit_shortcuts={},
    )
    stub._canonical_digit_mapping = LabelingWidget._canonical_digit_mapping
    stub.describe_config_error = LabelingWidget.describe_config_error
    return stub


def test_widget_commit_merges_untouched_digits(session):
    config, target, _path = session
    user_config.save_values({("digit_shortcuts", 1): DIGIT_ONE})
    stub = _commit_stub(config)
    stub.drawing_digit_shortcuts = {1: DIGIT_ONE}

    ok, message = LabelingWidget._commit_digit_shortcuts(
        stub, {1: DIGIT_ONE, 2: DIGIT_TWO}, {1: DIGIT_ONE}
    )

    assert ok is True, message
    data = _read(target)
    assert data["digit_shortcuts"][1] == DIGIT_ONE
    assert data["digit_shortcuts"][2] == DIGIT_TWO


def test_widget_commit_reports_a_same_digit_conflict(session):
    config, target, _path = session
    user_config.save_values({("digit_shortcuts", 1): DIGIT_ONE})
    stub = _commit_stub(config)
    stub.drawing_digit_shortcuts = {1: DIGIT_ONE}
    # Another entry changes digit 1 while the dialog is open...
    user_config.save_values({("digit_shortcuts", 1): DIGIT_THREE})

    # ...and the dialog, which still shows the old value, submits an edit.
    ok, message = LabelingWidget._commit_digit_shortcuts(
        stub, {1: DIGIT_TWO}, {1: DIGIT_ONE}
    )

    assert ok is False
    assert "digit_shortcuts.1" in message
    assert _read(target)["digit_shortcuts"][1] == DIGIT_THREE
    assert stub.drawing_digit_shortcuts == {1: DIGIT_ONE}


def test_widget_commit_keeps_a_digit_changed_while_the_dialog_was_open(
    session,
):
    config, target, _path = session
    user_config.save_values({("digit_shortcuts", 1): DIGIT_ONE})
    stub = _commit_stub(config)
    stub.drawing_digit_shortcuts = {1: DIGIT_ONE}
    # Another entry sets digit 2 while this dialog is open; the dialog's
    # snapshot does not contain it.
    user_config.save_values({("digit_shortcuts", 2): DIGIT_THREE})

    ok, message = LabelingWidget._commit_digit_shortcuts(
        stub, {1: DIGIT_ONE, 3: DIGIT_TWO}, {1: DIGIT_ONE}
    )

    assert ok is True, message
    assert stub.drawing_digit_shortcuts == {
        1: DIGIT_ONE,
        2: DIGIT_THREE,
        3: DIGIT_TWO,
    }
    assert _read(target)["digit_shortcuts"][2] == DIGIT_THREE


def test_widget_commit_can_clear_a_digit(session):
    config, target, _path = session
    user_config.save_values({("digit_shortcuts", 1): DIGIT_ONE})
    stub = _commit_stub(config)
    stub.drawing_digit_shortcuts = {1: DIGIT_ONE}

    ok, message = LabelingWidget._commit_digit_shortcuts(
        stub, {}, {1: DIGIT_ONE}
    )

    assert ok is True, message
    assert 1 not in _read(target)["digit_shortcuts"]
