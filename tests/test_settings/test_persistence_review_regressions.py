"""Behavioral regressions from the settings persistence review."""

import copy
import os
import shutil
import uuid
from types import SimpleNamespace

import pytest
import yaml
from PyQt6 import QtGui, QtWidgets

from anylabeling import config as app_config
from anylabeling import user_config
from anylabeling.views.labeling.settings.controller import SettingsController
from anylabeling.views.labeling.settings.runtime_applier import (
    SettingsRuntimeApplier,
)


@pytest.fixture
def profile():
    root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        ".tmp",
        "settings-review-regressions",
        uuid.uuid4().hex,
    )
    os.makedirs(root, exist_ok=True)
    controllers = []

    def start(document=None, overrides=None, apply_callback=None):
        target = os.path.join(root, "config.yaml")
        write(
            target,
            app_config.get_default_config() if document is None else document,
        )
        app_config.set_work_directory(root)
        config = app_config.get_config(target, overrides)
        controller = SettingsController(
            config,
            apply_callback=apply_callback,
            defer_runtime_apply=True,
        )
        controllers.append(controller)
        return config, target, controller

    yield start
    for controller in controllers:
        controller.close_session()
        controller.deleteLater()
    user_config.end_session()
    shutil.rmtree(root, ignore_errors=True)


def write(path, document):
    with open(path, "w", encoding="utf-8") as stream:
        yaml.safe_dump(document, stream, allow_unicode=True)


def read(path):
    with open(path, encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def edit(controller, key, value):
    controller.update_field(key, value, schedule_save=False)
    controller.save_now()
    assert controller.last_error is None


def test_ui_can_save_a_default_field_absent_from_the_document(profile):
    config, target, controller = profile({})
    edit(controller, "canvas.epsilon", 9.5)
    assert read(target) == {"canvas": {"epsilon": 9.5}}
    assert config["canvas"]["epsilon"] == 9.5


def test_ui_can_replace_one_transient_value_without_persisting_the_rest(
    profile,
):
    config, target, controller = profile(
        overrides={"canvas": {"epsilon": 9.9}, "labels": ["temporary"]}
    )
    edit(controller, "canvas.epsilon", 9.5)
    edit(controller, "model_hub", "modelscope")
    controller.reload_session()
    assert config["canvas"]["epsilon"] == 9.5
    assert config["labels"] == ["temporary"]
    assert read(target)["canvas"]["epsilon"] == 9.5
    assert read(target)["labels"] != ["temporary"]


@pytest.mark.parametrize("external", [False, True])
def test_peer_update_then_unrelated_save_advances_the_untouched_baseline(
    profile, external
):
    config, target, controller = profile()
    if external:
        document = read(target)
        document["canvas"]["label_font_size"] = 20
        write(target, document)
    else:
        user_config.save_values({"canvas.label_font_size": 20})
    edit(controller, "canvas.epsilon", 9.5)
    assert controller.get_value("canvas.label_font_size") == 20
    edit(controller, "canvas.label_font_size", 22)
    assert read(target)["canvas"]["label_font_size"] == 22


def test_a_modified_draft_keeps_its_original_persistent_baseline(profile):
    config, target, controller = profile({})
    controller.update_field("canvas.epsilon", 9.5, schedule_save=False)
    user_config.save_values({"canvas.epsilon": 9.0})
    controller.save_now()
    assert isinstance(controller.last_error, user_config.ConfigConflict)
    assert controller.get_value("canvas.epsilon") == 9.5
    assert read(target)["canvas"]["epsilon"] == 9.0


def test_unrelated_save_and_reopening_keep_a_runtime_failure_until_retry(
    profile,
):
    unavailable = {"value": True}

    def apply(key, value):
        if key == "canvas.epsilon" and unavailable["value"]:
            raise RuntimeError("runtime temporarily unavailable")

    config, target, controller = profile(apply_callback=apply)
    edit(controller, "canvas.epsilon", 9.5)
    assert controller.apply_failed_keys == ["canvas.epsilon"]
    edit(controller, "model_hub", "modelscope")
    assert controller.apply_failed_keys == ["canvas.epsilon"]
    controller.begin_session()
    assert controller.apply_failed_keys == ["canvas.epsilon"]
    controller.reload_session()
    assert controller.apply_failed_keys == ["canvas.epsilon"]
    unavailable["value"] = False
    assert controller.retry_apply()
    assert not controller.has_pending_apply()


def test_reloading_an_unchanged_file_rolls_back_a_live_preview(profile):
    applied = {}
    config, target, controller = profile(
        apply_callback=lambda key, value: applied.update({key: value})
    )
    key = "shape.line_width"
    original = config["shape"]["line_width"]
    controller._preview_keys.add(key)
    controller.update_field(key, original + 1, schedule_save=False)
    assert applied[key] == original + 1
    controller.reload_session()
    assert applied[key] == original
    assert not controller.has_modified_fields()


@pytest.mark.parametrize("removal", ["digit", "mapping", "file"])
def test_reload_removes_deleted_fields_and_uses_template_defaults(
    profile, removal
):
    document = copy.deepcopy(app_config.get_default_config())
    document["digit_shortcuts"] = {
        1: {"mode": "rectangle", "label": "car"},
        2: {"mode": "polygon", "label": "road"},
    }
    config, target, controller = profile(document)
    if removal == "digit":
        del document["digit_shortcuts"][1]
        expected = document["digit_shortcuts"]
        write(target, document)
    elif removal == "mapping":
        del document["digit_shortcuts"]
        expected = app_config.get_default_config()["digit_shortcuts"]
        write(target, document)
    else:
        os.unlink(target)
        expected = app_config.get_default_config()["digit_shortcuts"]
    controller.reload_session()
    assert config["digit_shortcuts"] == expected
    if removal == "file":
        assert not os.path.exists(target)


@pytest.mark.parametrize("operation", ["save", "reload", "peer_save"])
def test_adopted_shortcut_reaches_the_real_qaction(profile, operation):
    config, target, controller = profile()
    host = QtWidgets.QWidget()
    action = QtGui.QAction(host)
    action.setShortcut(config["shortcuts"]["open"])
    runtime = SettingsRuntimeApplier(
        SimpleNamespace(
            _config=config,
            auto_labeling_widget=SimpleNamespace(
                update_shortcut_button_texts=lambda value: None
            ),
            label_instruction=SimpleNamespace(setText=lambda value: None),
            get_labeling_instruction=lambda: "",
        )
    )
    runtime._shortcut_action_map = {"shortcuts.open": action}
    controller._apply_callback = lambda key, value: (
        runtime.apply_change(key, value)
        if key.startswith("shortcuts.")
        else None
    )
    wanted = "Ctrl+Alt+Shift+F12"
    if operation == "peer_save":
        user_config.save_values({"shortcuts.open": wanted})
    else:
        document = read(target)
        document["shortcuts"]["open"] = wanted
        write(target, document)
        if operation == "save":
            edit(controller, "canvas.epsilon", 9.5)
        else:
            controller.reload_session()
    assert action.shortcut().toString() == wanted
    host.deleteLater()
