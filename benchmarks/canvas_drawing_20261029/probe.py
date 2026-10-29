"""Boot the genuine application using an isolated profile for benchmarks."""
import copy
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE / ".deps"), str(ROOT)]
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_API"] = "pyqt6"
os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"

from PyQt6 import QtCore, QtWidgets
import anylabeling.resources.resources  # Register the real application icons.

PROFILE = HERE / "profile"
PROFILE.mkdir(exist_ok=True)
(PROFILE / "config.yaml").write_text("{}", encoding="utf-8")
settings_class = QtCore.QSettings
QtCore.QSettings = lambda *args, **kwargs: settings_class(str(PROFILE / "settings.ini"), settings_class.Format.IniFormat)

from anylabeling import config as app_config
app_config._work_directory = str(PROFILE)
app_config.current_config_file = str(PROFILE / "config.yaml")
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.mainwindow import MainWindow

if __name__ == "__main__":
    app = QtWidgets.QApplication([])
    config = copy.deepcopy(load_template_config())
    config.update(theme="light", exif_scan_enabled=False)
    window = MainWindow(app, config=config)
    window.resize(1600, 1000)
    window.show()
    app.processEvents()
    print("REAL_MAINWINDOW_OK", flush=True)
    widget = window.labeling_widget.view
    print("Canvas", widget.canvas.size().width(), widget.canvas.size().height(), flush=True)
    widget.dirty = False
    window.close()
    app.processEvents()
