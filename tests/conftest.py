"""Shared pytest configuration and fixtures for X-AnyLabeling tests.

This module centralises:

* the ``--slow`` option (the ``slow`` marker is declared in ``pyproject.toml``
  but had no matching option, so ``pytest --slow`` used to error), and the
  collection hook that skips ``@pytest.mark.slow`` tests unless ``--slow``
  is passed;
* the headless Qt platform (set before any PyQt import);
* small reusable fixtures so individual test files stop re-declaring their
  own ``MockShape`` / ``QApplication`` boilerplate.

It is intentionally compatible with the existing ``unittest.TestCase``
style tests (they keep working unchanged).
"""

import os

# Headless Qt — must be set before PyQt6 is imported anywhere.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

# Non-test scripts / standalone runners living under tests/ that would
# break collection:
# * test_models/rmbg_v_1_4.py imports skimage at module top (not a test)
# * test_inspector_direct.py / test_inspector_standalone.py are standalone
#   __main__ scripts that duplicate test_inspector_validation.py and use a
#   broken importlib loader (relative imports fail). The canonical pytest
#   version is test_inspector_validation.py.
# Paths are relative to this conftest's directory.
collect_ignore_glob = [
    "test_models/rmbg_v_1_4.py",
    "test_inspector_direct.py",
    "test_inspector_standalone.py",
]


def pytest_addoption(parser):
    """Register the --slow flag referenced by the `slow` marker."""
    parser.addoption(
        "--slow",
        action="store_true",
        default=False,
        help="run tests marked slow (skipped by default)",
    )


def pytest_collection_modifyitems(config, items):
    """Skip @pytest.mark.slow tests unless --slow is passed."""
    if config.getoption("--slow"):
        return
    skip_slow = pytest.mark.skip(reason="needs --slow to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


@pytest.fixture(scope="session")
def qapp():
    """Session-wide QApplication for headless widget tests."""
    from PyQt6 import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def canvas(qapp):
    """A bare Canvas with show_labels enabled (no pixmap required)."""
    from anylabeling.views.labeling.widgets.canvas import Canvas

    c = Canvas()
    c.show_labels = True
    return c


class MockShape:
    """Minimal shape stand-in for canvas/widget interaction tests.

    Mirrors the attributes read by ``Canvas.is_shape_interactive`` /
    ``_should_draw_standard_label`` and by the auto-focus / inspector code
    paths (``visible``, ``hidden_by_filter``, ``selected``, ``group_id``,
    ``label``, ``shape_type``, ``description``, ``points``).
    """

    def __init__(
        self,
        visible=True,
        hidden_by_filter=False,
        group_id=None,
        label="person",
        shape_type="rectangle",
        selected=False,
    ):
        self.visible = visible
        self.hidden_by_filter = hidden_by_filter
        self.group_id = group_id
        self.label = label
        self.shape_type = shape_type
        self.selected = selected
        self.description = ""
        self.points = []
