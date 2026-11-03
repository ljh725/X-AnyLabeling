import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--disable-gpu --no-sandbox --disable-software-rasterizer"
)

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: E402

PATH = "D:/X-AnyLabeling-4.2.1/reports/ui_review_20261103/mockup.html"
OUT = "D:/X-AnyLabeling-4.2.1/reports/ui_review_20261103/mockup-preview.png"

app = QtWidgets.QApplication(sys.argv)
QtGui.QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
view = QWebEngineView()
view.resize(1300, 2400)
view.show()


def after_load(ok):
    if not ok or not view.url().toLocalFile().endswith("mockup.html"):
        return
    page = view.page()
    page.runJavaScript(
        "document.body.classList.add('show-after');document.getElementById('insp-after').checked=true;"
        "document.getElementById('dense-after').checked=true;"
    )
    QtCore.QTimer.singleShot(1200, shot)


def shot():
    view.grab().save(OUT)
    print("saved", OUT)
    app.quit()


view.loadFinished.connect(after_load)
view.load(QtCore.QUrl.fromLocalFile(PATH))
QtCore.QTimer.singleShot(15000, app.quit)
app.exec()
