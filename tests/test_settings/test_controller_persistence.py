"""Field-level persistence behaviour of the settings controller."""

import copy
import os
import shutil
import uuid

import pytest
import yaml

from anylabeling import user_config
from anylabeling.config import normalize_user_config
from anylabeling.views.labeling.settings.controller import SettingsController
from anylabeling.views.labeling.settings.schema import load_template_config

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def _workspace():
    path = os.path.join(
        REPO_ROOT, ".tmp", "controller-persistence", uuid.uuid4().hex
    )
    os.makedirs(path, exist_ok=True)
    return path


@pytest.fixture
def app_config():
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


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _controller(config, failures=None):
    controller = SettingsController(
        config=config,
        apply_callback=lambda _key, _value: None,
        save_delay_ms=1000,
        defer_runtime_apply=True,
    )
    failed = []
    controller.save_failed.connect(failed.append)
    controller._test_failures = failures
    controller._test_failed = failed
    return controller


def test_general_save_keeps_digit_mapping_saved_earlier(app_config):
    config, target, _path = app_config
    digit_entry = {"mode": "rectangle", "label": "car"}
    user_config.save_values({("digit_shortcuts", 1): digit_entry})

    controller = _controller(config)
    controller.update_field("model_hub", "modelscope", schedule_save=False)
    controller.save_now()

    data = _read(target)
    assert data["digit_shortcuts"][1] == digit_entry
    assert data["model_hub"] == "modelscope"
    assert controller.last_saved_keys == ["model_hub"]


def test_save_submits_only_fields_modified_in_this_draft(app_config):
    config, target, _path = app_config
    user_config.save_values({"shortcuts.open": "Ctrl+Shift+O"})
    controller = _controller(config)
    controller.begin_session()

    original_font = controller.get_value("canvas.label_font_size")
    controller.update_field("canvas.epsilon", 9.5, schedule_save=False)
    controller.update_field(
        "canvas.label_font_size", original_font + 2, schedule_save=False
    )
    controller.update_field(
        "canvas.label_font_size", original_font, schedule_save=False
    )
    controller.save_now()

    data = _read(target)
    assert data["canvas"]["epsilon"] == 9.5
    assert data["canvas"]["label_font_size"] == original_font
    assert data["shortcuts"]["open"] == "Ctrl+Shift+O"
    assert controller.last_saved_keys == ["canvas.epsilon"]


def test_conflicting_external_change_is_reported_and_draft_kept(app_config):
    config, target, _path = app_config
    controller = _controller(config)
    controller.update_field("canvas.epsilon", 9.0, schedule_save=False)

    user_config.save_values({"canvas.epsilon": 9.5})
    controller.save_now()

    assert controller._test_failed, "conflict must surface as save_failed"
    assert controller.last_error is not None
    assert "canvas.epsilon" in str(controller.last_error)
    assert controller.has_modified_fields()
    assert controller.get_value("canvas.epsilon") == 9.0
    assert _read(target)["canvas"]["epsilon"] == 9.5


def test_failed_write_keeps_draft_and_retry_succeeds(app_config):
    config, target, _path = app_config
    real_save = user_config.save_patch
    attempts = {"count": 0}

    def flaky_save(patch):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise user_config.ConfigWriteError("simulated disk failure")
        return real_save(patch)

    controller = _controller(config)
    controller._save_callback = flaky_save
    controller.update_field("canvas.epsilon", 9.0, schedule_save=False)
    controller.save_now()

    assert controller._test_failed
    assert controller.has_modified_fields()
    assert _read(target)["canvas"]["epsilon"] != 9.0

    controller.save_now()
    assert controller.last_error is None
    assert not controller.has_modified_fields()
    assert _read(target)["canvas"]["epsilon"] == 9.0


def test_no_modified_fields_does_not_touch_the_file(app_config):
    _config, target, _path = app_config
    user_config.save_values({"canvas.epsilon": 8.5})
    before = os.path.getmtime(target)
    controller = _controller(_config)
    controller.save_now()
    assert os.path.getmtime(target) == before
    assert controller.last_saved_keys == []


def test_refresh_keeps_draft_values_and_updates_untouched_fields(app_config):
    config, _target, _path = app_config
    controller = _controller(config)
    controller.update_field("canvas.epsilon", 9.0, schedule_save=False)
    user_config.save_values({"canvas.label_font_size": 20})

    controller.refresh_from_committed()

    assert controller.get_value("canvas.epsilon") == 9.0
    assert controller.get_value("canvas.label_font_size") == 20


def test_runtime_apply_failure_keeps_the_saved_document(app_config):
    """Task 4.2: persistence succeeds even when the session cannot apply it."""

    config, target, _path = app_config
    state = {"fail": True}

    def apply_callback(key, _value):
        if state["fail"] and key == "canvas.epsilon":
            raise RuntimeError("simulated runtime failure")

    controller = SettingsController(
        config=config,
        apply_callback=apply_callback,
        save_delay_ms=1000,
        defer_runtime_apply=True,
    )
    failures = []
    successes = []
    controller.apply_failed.connect(
        lambda message, keys: failures.append((message, list(keys)))
    )
    controller.save_succeeded.connect(lambda: successes.append(True))

    controller.update_field("canvas.epsilon", 9.0, schedule_save=False)
    controller.save_now()

    assert successes, "the document was saved and must be reported as saved"
    assert controller.last_error is None
    assert not controller.has_modified_fields()
    assert _read(target)["canvas"]["epsilon"] == 9.0
    assert failures and failures[0][1] == ["canvas.epsilon"]
    assert controller.has_pending_apply()
    assert controller.apply_failed_keys == ["canvas.epsilon"]

    state["fail"] = False
    assert controller.retry_apply() is True
    assert not controller.has_pending_apply()


def test_retry_apply_reports_a_persistent_failure(app_config):
    config, _target, _path = app_config

    def apply_callback(_key, _value):
        raise RuntimeError("still broken")

    controller = SettingsController(
        config=config,
        apply_callback=apply_callback,
        save_delay_ms=1000,
        defer_runtime_apply=True,
    )
    controller.update_field("canvas.epsilon", 9.0, schedule_save=False)
    controller.save_now()

    assert controller.has_pending_apply()
    assert controller.retry_apply() is False
    assert controller.has_pending_apply()
    # The committed value stays saved; a reload keeps the file as the truth.
    assert _read(_target)["canvas"]["epsilon"] == 9.0


def test_dialog_reports_a_runtime_apply_failure_as_saved(
    app_config, monkeypatch
):
    """The dialog must not present a runtime failure as an unsaved draft."""

    from anylabeling.views.labeling.settings.dialog import SettingsDialog

    config, target, _path = app_config

    def apply_callback(key, _value):
        if key == "canvas.epsilon":
            raise RuntimeError("runtime exploded")

    controller = SettingsController(
        config=config,
        apply_callback=apply_callback,
        save_delay_ms=1000,
        defer_runtime_apply=True,
    )
    dialog = SettingsDialog(None, controller)
    dialog.show()
    try:
        controller.update_field("canvas.epsilon", 9.0, schedule_save=False)
        controller.save_now()

        status = dialog.status_label.text()
        assert "Saved, but not applied" in status
        assert _read(target)["canvas"]["epsilon"] == 9.0
        assert controller.has_pending_apply()
        assert not controller.has_modified_fields()

        monkeypatch.setattr(
            controller, "_apply_callback", lambda _key, _value: None
        )
        assert controller.retry_apply() is True
        assert not controller.has_pending_apply()
    finally:
        dialog.close()


def test_reload_session_rereads_a_file_written_elsewhere(app_config):
    config, target, _path = app_config
    controller = _controller(config)
    controller.update_field("canvas.epsilon", 9.0, schedule_save=False)
    controller.update_field("canvas.label_font_size", 20, schedule_save=False)

    document = _read(target)
    document["canvas"]["epsilon"] = 8.75
    with open(target, "w", encoding="utf-8") as handle:
        yaml.safe_dump(document, handle)

    assert controller.reload_session() is True
    # Reloading is the explicit "give up this draft" action, so both fields
    # come from the file: the external epsilon and the stored font size.
    assert controller.get_value("canvas.epsilon") == 8.75
    assert (
        controller.get_value("canvas.label_font_size")
        == document["canvas"]["label_font_size"]
    )
    assert not controller.has_modified_fields()
