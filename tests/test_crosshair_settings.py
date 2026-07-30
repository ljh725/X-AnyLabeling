"""Tests for the unified crosshair settings entry and runtime application."""

from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from anylabeling.views.labeling import widgets
from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.settings.runtime_applier import (
    SettingsRuntimeApplier,
)


def test_crosshair_entry_routes_to_unified_setting() -> None:
    """The View-menu adapter must target the canonical crosshair field."""
    calls = []
    widget = SimpleNamespace(
        open_settings_dialog=lambda **kwargs: calls.append(kwargs)
    )

    LabelingWidget.open_crosshair_settings(widget)

    assert calls == [{"setting_key": "canvas.crosshair.show"}]


def test_open_settings_dialog_navigates_after_showing() -> None:
    """An existing settings dialog is shown and positioned at the field."""
    dialog = MagicMock()
    widget = SimpleNamespace(
        _settings_controller=object(),
        _settings_dialog=dialog,
    )

    LabelingWidget.open_settings_dialog(
        widget,
        setting_key="canvas.crosshair.show",
    )

    assert dialog.method_calls == [
        call.show(),
        call.navigate_to_setting("canvas.crosshair.show"),
        call.raise_(),
        call.activateWindow(),
    ]


def test_open_settings_dialog_returns_without_controller() -> None:
    """Settings remain unavailable until their controller is initialized."""
    dialog = MagicMock()
    widget = SimpleNamespace(
        _settings_controller=None,
        _settings_dialog=dialog,
    )

    LabelingWidget.open_settings_dialog(
        widget,
        setting_key="canvas.crosshair.show",
    )

    dialog.show.assert_not_called()


def test_runtime_applier_has_no_crosshair_cache_side_effect() -> None:
    """Applying saved settings updates Canvas without recreating stale state."""
    canvas = MagicMock()
    widget = SimpleNamespace(
        _config={
            "canvas": {
                "crosshair": {
                    "show": True,
                    "width": 3.5,
                    "color": "#123ABC",
                    "opacity": 0.75,
                }
            }
        },
        canvas=canvas,
    )
    applier = SimpleNamespace(_widget=widget)

    SettingsRuntimeApplier.apply_canvas_crosshair(applier)

    canvas.set_cross_line.assert_called_once_with(
        True,
        3.5,
        "#123ABC",
        0.75,
    )
    assert not hasattr(widget, "crosshair_settings")


def test_legacy_crosshair_dialog_is_not_exported() -> None:
    """The removed standalone dialog must not remain lazily importable."""
    assert "CrosshairSettingsDialog" not in widgets.__all__
    with pytest.raises(AttributeError):
        getattr(widgets, "CrosshairSettingsDialog")
