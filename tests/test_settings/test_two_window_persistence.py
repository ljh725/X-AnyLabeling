"""Two settings windows sharing one configuration target.

These tests use real ``SettingsDialog`` instances with independent drafts, so
they cover the window-level interleaving that the controller tests only
approximate: digits saved in one window, a draft open in the other, cancel
scope, cross-window conflicts and restart visibility.
"""

import copy
import os
import shutil
import uuid

import pytest
import yaml

from PyQt6 import QtWidgets

from anylabeling import user_config
from anylabeling.config import normalize_user_config
from anylabeling.views.labeling.settings.controller import SettingsController
from anylabeling.views.labeling.settings.dialog import SettingsDialog
from anylabeling.views.labeling.settings.schema import load_template_config

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
DIGIT_ONE = {"mode": "rectangle", "label": "car"}


def _workspace():
    path = os.path.join(
        REPO_ROOT, ".tmp", "two-window-persistence", uuid.uuid4().hex
    )
    os.makedirs(path, exist_ok=True)
    return path


#: Every dialog opened by this module, so the fixture cleans up all of them
#: even when a test keeps its own local list.
_OPEN_DIALOGS = []


@pytest.fixture
def config_session():
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
    del _OPEN_DIALOGS[:]
    try:
        yield config, target
    finally:
        for dialog, controller in list(_OPEN_DIALOGS):
            # Drop failed drafts before closing so teardown never opens a
            # blocking "retry / discard" prompt in the offscreen session.
            controller.begin_session()
            dialog.close()
        del _OPEN_DIALOGS[:]
        QtWidgets.QApplication.instance().processEvents()
        user_config.end_session()
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def no_modal_config_dialogs(monkeypatch):
    """Keep the offscreen tests from opening blocking message boxes."""

    monkeypatch.setattr(
        SettingsDialog,
        "_offer_reload_after_conflict",
        lambda self, error: None,
    )
    monkeypatch.setattr(
        SettingsDialog, "_offer_backup_restore", lambda self, error: None
    )


def _open_window(config, dialogs=None):
    controller = SettingsController(
        config=config,
        apply_callback=lambda _key, _value: None,
        save_delay_ms=1000,
        defer_runtime_apply=True,
    )
    dialog = SettingsDialog(None, controller)
    dialog.show()
    QtWidgets.QApplication.instance().processEvents()
    _OPEN_DIALOGS.append((dialog, controller))
    if dialogs is not None:
        dialogs.append((dialog, controller))
    return dialog, controller


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_digits_and_shortcut_saved_in_second_window_survive_first(
    config_session,
):
    config, target = config_session
    dialogs = []
    _dialog_a, controller_a = _open_window(config, dialogs)
    _dialog_b, controller_b = _open_window(config, dialogs)

    user_config.save_values({("digit_shortcuts", 1): DIGIT_ONE})
    controller_b.update_field(
        "shortcuts.open", "Ctrl+Shift+O", schedule_save=False
    )
    controller_b.save_now()
    assert controller_b.last_error is None

    controller_a.update_field("canvas.epsilon", 9.5, schedule_save=False)
    controller_a.refresh_from_committed()
    assert controller_a.get_value("shortcuts.open") == "Ctrl+Shift+O"
    assert controller_a.get_value("canvas.epsilon") == 9.5
    controller_a.save_now()

    data = _read(target)
    assert data["digit_shortcuts"][1] == DIGIT_ONE
    assert data["shortcuts"]["open"] == "Ctrl+Shift+O"
    assert data["canvas"]["epsilon"] == 9.5


def test_cancel_in_one_window_keeps_the_other_windows_changes(
    config_session,
):
    config, target = config_session
    dialogs = []
    dialog_a, controller_a = _open_window(config, dialogs)
    _dialog_b, controller_b = _open_window(config, dialogs)

    original_epsilon = controller_a.get_value("canvas.epsilon")
    controller_a.update_field("canvas.epsilon", 9.5, schedule_save=False)
    controller_b.update_field(
        "canvas.label_font_size", 22, schedule_save=False
    )
    controller_b.save_now()
    assert controller_b.last_error is None

    dialog_a.close()
    QtWidgets.QApplication.instance().processEvents()

    data = _read(target)
    assert data["canvas"]["label_font_size"] == 22
    assert data["canvas"]["epsilon"] == original_epsilon
    assert controller_a.get_value("canvas.epsilon") == original_epsilon


def test_conflict_between_two_windows_keeps_first_value(
    config_session, monkeypatch
):
    config, target = config_session
    dialogs = []
    _dialog_a, controller_a = _open_window(config, dialogs)
    dialog_b, controller_b = _open_window(config, dialogs)
    monkeypatch.setattr(
        SettingsDialog,
        "_offer_reload_after_conflict",
        lambda self, error: None,
    )
    monkeypatch.setattr(
        SettingsDialog, "_confirm_close_with_failed_save", lambda self: True
    )

    controller_a.update_field("canvas.epsilon", 9.0, schedule_save=False)
    controller_b.update_field("canvas.epsilon", 9.5, schedule_save=False)
    controller_a.save_now()
    controller_b.save_now()

    assert controller_b.last_error is not None
    assert "canvas.epsilon" in str(controller_b.last_error)
    assert controller_b.has_modified_fields()
    assert controller_b.get_value("canvas.epsilon") == 9.5
    assert _read(target)["canvas"]["epsilon"] == 9.0
    dialog_b.close()
    QtWidgets.QApplication.instance().processEvents()


def test_restart_after_two_windows_sees_every_saved_field(config_session):
    config, target = config_session
    dialogs = []
    _dialog_a, controller_a = _open_window(config, dialogs)
    _dialog_b, controller_b = _open_window(config, dialogs)

    user_config.save_values({("digit_shortcuts", 2): DIGIT_ONE})
    controller_a.update_field("model_hub", "modelscope", schedule_save=False)
    controller_a.save_now()
    controller_b.update_field("canvas.epsilon", 9.5, schedule_save=False)
    controller_b.save_now()

    user_config.end_session()
    reloaded = copy.deepcopy(load_template_config())
    disk = _read(target)
    from anylabeling.config import update_dict

    update_dict(reloaded, normalize_user_config(disk))
    _dialog_c, controller_c = _open_window(reloaded, dialogs)

    assert controller_c.get_value("digit_shortcuts")[2] == DIGIT_ONE
    assert controller_c.get_value("model_hub") == "modelscope"
    assert controller_c.get_value("canvas.epsilon") == 9.5


def test_old_draft_cannot_replace_a_field_written_externally(config_session):
    """The P1 gap: an unrelated save must not absorb a foreign value."""

    config, target = config_session
    dialogs = []
    _dialog_a, controller_a = _open_window(config, dialogs)
    _dialog_b, controller_b = _open_window(config, dialogs)

    controller_a.update_field("canvas.epsilon", 9.0, schedule_save=False)

    # Another process writes epsilon directly to the file.
    document = _read(target)
    document["canvas"]["epsilon"] = 9.5
    with open(target, "w", encoding="utf-8") as handle:
        yaml.safe_dump(document, handle)

    # A different entry saves an unrelated field first.  The committed view
    # must adopt the external epsilon, keeping this window's baseline stale.
    controller_b.update_field(
        "canvas.label_font_size", 22, schedule_save=False
    )
    controller_b.save_now()
    assert controller_b.last_error is None
    # The committed view adopted the external value; the open draft keeps the
    # value the user typed so it can be compared when that draft is saved.
    assert config["canvas"]["epsilon"] == 9.5
    assert controller_a.get_value("canvas.epsilon") == 9.0

    controller_a.save_now()

    assert controller_a.last_error is not None
    assert "canvas.epsilon" in str(controller_a.last_error)
    assert controller_a.has_modified_fields()
    assert _read(target)["canvas"]["epsilon"] == 9.5
    assert _read(target)["canvas"]["label_font_size"] == 22


def test_untouched_field_can_be_edited_after_a_save(config_session):
    """Task 4.1: rebuilding the draft after a save must sync its baselines."""

    config, target = config_session
    dialogs = []
    _dialog, controller = _open_window(config, dialogs)

    controller.update_field("canvas.epsilon", 9.0, schedule_save=False)
    controller.save_now()
    assert controller.last_error is None

    controller.update_field(
        "canvas.label_font_size", 22, schedule_save=False
    )
    controller.save_now()

    assert controller.last_error is None
    data = _read(target)
    assert data["canvas"]["epsilon"] == 9.0
    assert data["canvas"]["label_font_size"] == 22


def test_conflict_reload_reads_the_file_again(config_session):
    """Reloading after a conflict must read the disk, not the stale memory."""

    config, target = config_session
    dialogs = []
    dialog, controller = _open_window(config, dialogs)
    controller.update_field("canvas.epsilon", 9.9, schedule_save=False)

    document = _read(target)
    document["canvas"]["epsilon"] = 8.75
    with open(target, "w", encoding="utf-8") as handle:
        yaml.safe_dump(document, handle)

    controller.save_now()
    assert controller.last_error is not None

    dialog.reload_committed_values()

    assert controller.get_value("canvas.epsilon") == 8.75
    assert not controller.has_modified_fields()
    controller.update_field("canvas.epsilon", 9.1, schedule_save=False)
    controller.save_now()
    assert controller.last_error is None
    assert _read(target)["canvas"]["epsilon"] == 9.1
