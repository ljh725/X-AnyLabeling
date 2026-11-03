"""Shared Qt application for the test session.

Keeping one QApplication alive for the whole session avoids dangling
wrappers when module-scoped windows are torn down between suites.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app
