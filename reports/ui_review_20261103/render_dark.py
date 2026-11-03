"""Render both workbenches with the dark theme for contrast checks."""

import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = "D:/X-AnyLabeling-4.2.1"
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

import render_ui  # noqa: E402

OUTDIR = os.environ.get("UI_REVIEW_OUT", HERE)
from anylabeling.views.labeling.utils.theme import (  # noqa: E402
    get_app_stylesheet,
    get_dark_palette,
    init_theme,
)


def pump(app, times=20):
    for _ in range(times):
        app.processEvents()
        time.sleep(0.01)


def main():
    init_theme("dark")
    image_path = render_ui.build_dataset()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    QtGui.QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    app.setFont(QtGui.QFont("Microsoft YaHei", 9))
    app.setStyle("Fusion")
    palette = get_dark_palette()
    if palette is not None:
        app.setPalette(palette)
    app.setStyleSheet(get_app_stylesheet())
    window = render_ui.build_window(app, HERE)
    view = window.labeling_widget.view
    view.load_file(image_path)
    pump(app)

    view.open_inspector()
    pump(app)
    dialog = view.inspector_dialog
    dialog.setMinimumSize(1200, 820)
    dialog.resize(1200, 820)
    pump(app)
    dialog.scope_combo.setCurrentIndex(0)
    dialog.start_button.click()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and dialog.report is None:
        app.processEvents()
        time.sleep(0.02)
    pump(app, 30)
    if dialog.issue_table.rowCount():
        dialog.issue_table.selectRow(0)
        pump(app)
    dialog.grab().save(os.path.join(OUTDIR, "06_inspector_dark.png"))
    dialog.close()

    view.open_dense_review()
    pump(app)
    workspace = view.dense_review_workspace
    workspace.setMinimumSize(1280, 860)
    workspace.resize(1280, 860)
    pump(app, 40)
    workspace.grab().save(os.path.join(OUTDIR, "08_dense_dark.png"))
    print("saved dark renders")


if __name__ == "__main__":
    main()
