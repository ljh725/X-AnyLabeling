import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

from anylabeling.services.dense_review.models import ReviewConfig
from anylabeling.views.labeling.dense_review.config_dialog import (
    DenseReviewConfigDialog,
)


@pytest.fixture(scope="module")
def app():
    application = (
        QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    )
    application.setQuitOnLastWindowClosed(False)
    yield application


def test_config_dialog_round_trip_and_validation(app):
    dialog = DenseReviewConfigDialog(
        ["A", "B", "C"],
        ReviewConfig(),
    )
    dialog._append_batch("A/B", ("A", "B"))
    dialog._append_rule("A", "visible", "只标可见部分")
    dialog.default_rule_combo.setCurrentIndex(
        dialog.default_rule_combo.findData("unknown")
    )
    config = dialog.config()
    assert config.validate() == ()
    assert config.batches[0].labels == ("A", "B")
    assert config.rules.box_rule("A") == "visible"
    assert config.rules.note("A") == "只标可见部分"

    dialog._append_batch("A/C", ("A", "C"))
    dialog._validate()
    assert dialog.ok_button.isEnabled() is False
    assert "A" in dialog.validation_label.text()
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_config_dialog_coverage_settings(app):
    dialog = DenseReviewConfigDialog(["A"], ReviewConfig())
    dialog.columns_spin.setValue(5)
    dialog.rows_spin.setValue(3)
    dialog.overlap_spin.setValue(25)
    config = dialog.config()
    assert config.coverage.columns == 5
    assert config.coverage.rows == 3
    assert abs(config.coverage.overlap - 0.25) < 1e-9
    dialog.close()
    dialog.deleteLater()
    app.processEvents()
