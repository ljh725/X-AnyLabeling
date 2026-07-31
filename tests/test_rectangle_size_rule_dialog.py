"""Tests for the standalone rectangle-size rule configuration dialog."""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

import pytest

from anylabeling.views.labeling.rectangle_size.config_codec import (
    RectangleSizeConfigError,
)
from anylabeling.views.labeling.rectangle_size.models import RectangleSizeRule
from anylabeling.views.labeling.widgets.rectangle_size_rule_dialog import (
    RectangleSizeRuleDialog,
    RectangleSizeRuleTable,
)


def _rule(
    label: str = "person",
    *,
    width: float | None = 36.0,
    height: float | None = 36.0,
    mode: str = "all",
    enabled: bool = True,
) -> RectangleSizeRule:
    """Return one editable rule model."""
    return RectangleSizeRule(
        label=label,
        min_width_px=width,
        min_height_px=height,
        trigger_mode=mode,
        enabled=enabled,
    )


def _editor(
    table: RectangleSizeRuleTable,
    row: int,
    column: int,
) -> QtWidgets.QWidget:
    """Return a required cell editor."""
    editor = table.table.cellWidget(row, column)
    assert editor is not None
    return editor


def _set_text(
    table: RectangleSizeRuleTable,
    row: int,
    column: int,
    value: str,
) -> None:
    """Set text on one line-edit cell."""
    editor = _editor(table, row, column)
    assert isinstance(editor, QtWidgets.QLineEdit)
    editor.setText(value)


def test_table_round_trips_multiple_rules(qapp) -> None:
    """The table should preserve optional dimensions, modes, and enabled state."""
    rules = (
        _rule(),
        _rule(
            "face",
            width=None,
            height=18.5,
            mode="any",
            enabled=False,
        ),
    )

    table = RectangleSizeRuleTable(rules)

    assert table.rules() == rules
    assert table.table.rowCount() == 2


def test_blank_threshold_becomes_none(qapp) -> None:
    """A blank W/H field should opt that dimension out of evaluation."""
    table = RectangleSizeRuleTable([_rule(height=22.0)])

    _set_text(table, 0, 2, "")

    assert table.rules() == (_rule(width=None, height=22.0),)


def test_add_and_remove_rows(qapp) -> None:
    """Users should be able to manage any number of category rows."""
    table = RectangleSizeRuleTable([_rule()])

    table.add_empty_rule()
    _set_text(table, 1, 1, "face")
    _set_text(table, 1, 2, "12")
    assert [rule.label for rule in table.rules()] == ["person", "face"]

    table.remove_row(0)

    assert table.rules() == (
        _rule("face", width=12.0, height=None, mode="any"),
    )


def test_duplicate_labels_are_rejected_even_when_disabled(qapp) -> None:
    """One exact label must map to only one configuration row."""
    table = RectangleSizeRuleTable([_rule()])
    table.add_empty_rule()
    _set_text(table, 1, 1, "person")
    enabled_item = table.table.item(1, 0)
    enabled_item.setCheckState(QtCore.Qt.CheckState.Unchecked)

    with pytest.raises(RectangleSizeConfigError, match="duplicate label"):
        table.rules()


def test_enabled_rule_requires_at_least_one_threshold(qapp) -> None:
    """An active row with both dimensions blank is incomplete."""
    table = RectangleSizeRuleTable()
    table.add_empty_rule()
    _set_text(table, 0, 1, "person")

    with pytest.raises(
        RectangleSizeConfigError,
        match="at least one W/H threshold",
    ):
        table.rules()


def test_disabled_rule_may_have_no_threshold(qapp) -> None:
    """Disabled rows may remain configured without an active dimension."""
    table = RectangleSizeRuleTable()
    table.add_empty_rule()
    _set_text(table, 0, 1, "person")
    enabled_item = table.table.item(0, 0)
    enabled_item.setCheckState(QtCore.Qt.CheckState.Unchecked)

    assert table.rules() == (
        _rule(
            width=None,
            height=None,
            mode="any",
            enabled=False,
        ),
    )


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "bad"])
def test_threshold_must_be_positive_and_finite(qapp, value: str) -> None:
    """Invalid numeric text must not cross the dialog data boundary."""
    table = RectangleSizeRuleTable([_rule()])
    _set_text(table, 0, 2, value)

    with pytest.raises(RectangleSizeConfigError, match="positive finite"):
        table.rules()


def test_set_rules_is_atomic_when_new_input_is_invalid(qapp) -> None:
    """A failed programmatic replacement must leave old rows untouched."""
    original = (_rule(),)
    table = RectangleSizeRuleTable(original)
    duplicates = (_rule("face"), _rule("face"))

    with pytest.raises(RectangleSizeConfigError, match="duplicate label"):
        table.set_rules(duplicates)

    assert table.rules() == original


def test_dialog_invalid_apply_stays_open_and_emits_nothing(qapp) -> None:
    """Inline validation feedback should preserve the editable dialog state."""
    dialog = RectangleSizeRuleDialog()
    dialog.rule_table.add_empty_rule()
    emissions = []
    dialog.rules_applied.connect(emissions.append)

    dialog._apply_and_accept()

    assert dialog.result() == QtWidgets.QDialog.DialogCode.Rejected
    assert dialog.accepted_rules is None
    assert emissions == []
    assert dialog.error_label.isVisibleTo(dialog)
    assert "Cannot apply rules" in dialog.error_label.text()


def test_dialog_valid_apply_emits_one_immutable_snapshot(qapp) -> None:
    """A fully valid table should publish once and close as accepted."""
    rules = (
        _rule("person", width=36.0, height=None, mode="any"),
        _rule("face", width=None, height=20.0, mode="all"),
    )
    dialog = RectangleSizeRuleDialog(rules)
    emissions = []
    dialog.rules_applied.connect(emissions.append)

    dialog._apply_and_accept()

    assert dialog.result() == QtWidgets.QDialog.DialogCode.Accepted
    assert dialog.accepted_rules == rules
    assert emissions == [rules]


def test_help_text_explains_inclusive_boundary_and_blank_dimension(
    qapp,
) -> None:
    """The visible guidance should expose the two non-obvious rule semantics."""
    dialog = RectangleSizeRuleDialog()
    help_label = dialog.findChild(
        QtWidgets.QLabel,
        "rectangleSizeRuleHelp",
    )

    assert help_label is not None
    assert "less than or equal" in help_label.text()
    assert "Blank dimensions are ignored" in help_label.text()


def test_category_editor_keeps_usable_width_with_all_columns(qapp) -> None:
    """Fixed parameter columns must not squeeze the category editor away."""
    dialog = RectangleSizeRuleDialog([_rule()])
    dialog.show()
    qapp.processEvents()

    assert dialog.rule_table.table.columnWidth(1) >= 180
    assert dialog.rule_table.table.columnWidth(2) >= 130
    assert dialog.rule_table.table.columnWidth(3) >= 130
    assert dialog.rule_table.table.columnWidth(4) >= 170


def test_compiled_chinese_translation_contains_rule_semantics(qapp) -> None:
    """Compiled resources should expose the new dialog in Chinese."""
    from anylabeling.resources import resources as _resources  # noqa: F401

    translator = QtCore.QTranslator()
    assert translator.load(":/languages/translations/zh_CN.qm")
    qapp.installTranslator(translator)
    try:
        dialog = RectangleSizeRuleDialog()
        help_label = dialog.findChild(
            QtWidgets.QLabel,
            "rectangleSizeRuleHelp",
        )

        assert dialog.windowTitle() == "矩形框像素规则"
        assert help_label is not None
        assert "小于等于阈值" in help_label.text()
        assert "留空的维度不参与判断" in help_label.text()
    finally:
        qapp.removeTranslator(translator)


@pytest.mark.parametrize(
    ("language", "expected_row", "expected_message"),
    [
        ("zh_CN", "规则第 1 行", "类别不能为空"),
        ("ja_JP", "ルール行 1", "ラベルを空にすることはできません"),
        ("ko_KR", "규칙 1행", "라벨은 비워 둘 수 없습니다"),
    ],
)
def test_compiled_locales_translate_validation_feedback(
    qapp,
    language: str,
    expected_row: str,
    expected_message: str,
) -> None:
    """Validation feedback should not leak parser English into localized UI."""
    from anylabeling.resources import resources as _resources  # noqa: F401

    translator = QtCore.QTranslator()
    assert translator.load(f":/languages/translations/{language}.qm")
    qapp.installTranslator(translator)
    try:
        dialog = RectangleSizeRuleDialog()
        dialog.rule_table.add_empty_rule()
        dialog._apply_and_accept()

        assert expected_row in dialog.error_label.text()
        assert expected_message in dialog.error_label.text()
        assert "Rule row" not in dialog.error_label.text()
    finally:
        qapp.removeTranslator(translator)


@pytest.mark.parametrize(
    ("language", "expected_overlay"),
    [
        ("zh_CN", "最大边 %.1f px < %g px"),
        ("ja_JP", "最大辺 %.1f px < %g px"),
        ("ko_KR", "최대 변 %.1f px < %g px"),
    ],
)
def test_compiled_locales_use_canvas_context_for_overlay(
    qapp,
    language: str,
    expected_overlay: str,
) -> None:
    """Canvas translations must resolve from their actual runtime context."""
    from anylabeling.resources import resources as _resources  # noqa: F401

    translator = QtCore.QTranslator()
    assert translator.load(f":/languages/translations/{language}.qm")
    qapp.installTranslator(translator)
    try:
        translated = QtCore.QCoreApplication.translate(
            "Canvas",
            "Max edge %.1f px < %g px",
        )

        assert translated == expected_overlay
    finally:
        qapp.removeTranslator(translator)


@pytest.mark.parametrize(
    ("language", "expected_action"),
    [
        ("zh_CN", "显示矩形尺寸异常"),
        ("ja_JP", "矩形サイズ異常を表示"),
        ("ko_KR", "사각형 크기 이상 표시"),
    ],
)
def test_compiled_locales_translate_main_flow_action(
    qapp,
    language: str,
    expected_action: str,
) -> None:
    """The stage-ten toggle should resolve from compiled language resources."""
    from anylabeling.resources import resources as _resources  # noqa: F401

    translator = QtCore.QTranslator()
    assert translator.load(f":/languages/translations/{language}.qm")
    qapp.installTranslator(translator)
    try:
        translated = QtCore.QCoreApplication.translate(
            "LabelingWidget",
            "Show Rectangle Size Violations",
        )

        assert translated == expected_action
    finally:
        qapp.removeTranslator(translator)
