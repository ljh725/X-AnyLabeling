"""Main-window smoke test for rectangle-size validation integration."""

from __future__ import annotations

import copy

from PyQt6 import QtCore, QtWidgets

from anylabeling.config import get_default_config
from anylabeling.views.labeling import label_widget as label_widget_module
from anylabeling.views.labeling.rectangle_size.models import RectangleSizeRule
from anylabeling.views.labeling.shape import Shape


def _small_person() -> Shape:
    """Return one rectangle that violates the migrated default rule."""
    shape = Shape(label="person", shape_type="rectangle")
    shape.points = [QtCore.QPointF(10.0, 10.0), QtCore.QPointF(30.0, 30.0)]
    return shape


def test_labeling_widget_exposes_working_main_flow_actions(
    qapp,
    monkeypatch,
) -> None:
    """Menu toggle should activate the real Monitor-to-Canvas data flow."""
    persisted = []
    monkeypatch.setattr(
        label_widget_module,
        "save_config",
        lambda config: persisted.append(copy.deepcopy(config)),
    )
    config = copy.deepcopy(get_default_config())
    from anylabeling.services.auto_labeling import model_manager

    monkeypatch.setattr(model_manager, "get_config", lambda: config)
    main_window = QtWidgets.QMainWindow()
    wrapper = QtWidgets.QWidget()
    wrapper.parent = main_window
    widget = label_widget_module.LabelingWidget(
        parent=wrapper,
        config=config,
    )
    try:
        assert widget.actions.show_rectangle_size_violations.isCheckable()
        assert not widget.actions.show_rectangle_size_violations.isChecked()
        assert widget.actions.configure_rectangle_size_rules.isEnabled()
        assert widget.rectangle_size_controller.enabled is False

        shape = _small_person()
        widget.canvas.load_shapes([shape], replace=True)
        widget.actions.show_rectangle_size_violations.trigger()
        qapp.processEvents()

        assert widget.rectangle_size_controller.enabled is True
        assert widget.canvas.show_rectangle_size_violations is True
        assert len(widget.canvas.rectangle_size_issues) == 1
        assert config["show_rectangle_size_violations"] is True
        assert persisted[-1]["show_rectangle_size_violations"] is True
        assert widget.dirty is False

        class AcceptedRuleDialog:
            """Deterministic accepted dialog for the menu-action boundary."""

            def __init__(self, rules, parent) -> None:
                self.initial_rules = rules
                self.parent = parent
                self.accepted_rules = (
                    RectangleSizeRule(
                        label="face",
                        min_width_px=12.0,
                    ),
                )

            def exec(self) -> QtWidgets.QDialog.DialogCode:
                return QtWidgets.QDialog.DialogCode.Accepted

        monkeypatch.setattr(
            label_widget_module,
            "RectangleSizeRuleDialog",
            AcceptedRuleDialog,
        )
        widget.actions.configure_rectangle_size_rules.trigger()
        qapp.processEvents()

        assert widget.rectangle_size_controller.rules == (
            RectangleSizeRule(label="face", min_width_px=12.0),
        )
        assert config["rectangle_size_rules"][0]["label"] == "face"
        assert widget.canvas.rectangle_size_issues == ()
        assert widget.dirty is False
    finally:
        widget.rectangle_size_controller.monitor.clear_shapes()
        widget.close()
        widget.deleteLater()
        wrapper.deleteLater()
        main_window.deleteLater()
        qapp.processEvents()
