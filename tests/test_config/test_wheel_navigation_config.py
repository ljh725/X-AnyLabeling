"""``canvas.wheel_navigation_mode`` defaults, validation and settings wiring."""

import pytest

from anylabeling import config as app_config
from anylabeling.views.labeling.settings.runtime_applier import (
    SettingsRuntimeApplier,
)
from anylabeling.views.labeling.settings.schema import (
    SETTING_FIELD_MAP,
    SETTINGS_KEYS,
)


def test_missing_mode_defaults_to_direct(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    config = app_config.get_config("canvas: {}")
    assert config["canvas"]["wheel_navigation_mode"] == "direct"


@pytest.mark.parametrize("mode", ["direct", "traditional"])
def test_valid_mode_is_preserved(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    config = app_config.get_config(
        "canvas:\n  wheel_navigation_mode: " + mode
    )
    assert config["canvas"]["wheel_navigation_mode"] == mode


def test_invalid_mode_falls_back_to_direct(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    config = app_config.get_config(
        "canvas:\n  wheel_navigation_mode: unsupported"
    )
    assert config["canvas"]["wheel_navigation_mode"] == "direct"


def test_setting_field_is_registered_with_both_options():
    assert "canvas.wheel_navigation_mode" in SETTINGS_KEYS
    field = SETTING_FIELD_MAP["canvas.wheel_navigation_mode"]
    assert field.control == "enum"
    assert field.options == ("direct", "traditional")
    assert field.description


def test_runtime_applier_forwards_the_mode():
    class Widget:
        def __init__(self):
            self.applied = []

        def apply_wheel_navigation_mode(self, value):
            self.applied.append(value)

    applier = SettingsRuntimeApplier.__new__(SettingsRuntimeApplier)
    applier._widget = Widget()

    applier.apply_change("canvas.wheel_navigation_mode", "traditional")

    assert applier._widget.applied == ["traditional"]
